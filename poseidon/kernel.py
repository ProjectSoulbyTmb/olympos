"""POSEIDON kernel - the tide engine that never lets work stand still.

Doctrine obeyed (FLOW.md):
  - the root checkout is an integration mirror; POSEIDON never commits
    on main here and never pushes main directly,
  - every change ships through the writer lane: a private worktree on
    ``auto/poseidon``, pushed, opened as a PR, merged squash,
  - pushes are arbitrated by FORSETI's ``push-main`` lane lock so the
    tide cannot race another writer,

Mechanics per cycle:
  1. read drift (porcelain status) from the root checkout
  2. snapshot it with a throwaway index (GIT_INDEX_FILE plumbing):
     the root working tree and index are never touched by this step
  3. sync the poseidon worktree with origin/main, cherry-pick the
     snapshot onto ``auto/poseidon``
  4. hold FORSETI's lane only for shared water: push, PR/merge,
     then settle the mirror - guarded, so a path a writer edited
     after the snapshot is skipped, never clobbered

Speed rules: one shared fetch per cycle feeds every berth in the
fleet; private worktree work runs outside the arbitration lane; the
watch loop sprints after shipped tides and backs off exponentially
after failures.

Failure stance: "quarantine, never destroy". The drift stays in the
root working tree until a merge proves it is safe to settle; any
failed cycle leaves the workspace exactly as it was found. Three
consecutive failures quarantine shipping for a cooldown; ``resume``
(or the cooldown elapsing) reopens the lane.

Self-healing is built into the automation itself: every cycle opens
with a light repair pass (``heal.auto_pass`` - rebuild a damaged berth,
sweep orphaned throwaway indexes, trim a torn ledger tail, probe-release
a quarantine whose cause has cleared), and each push carries its own
auto-fixes (``_push_with_heal`` - non-fast-forward rejections adopt
origin's copy of this single-writer branch and replay the snapshot from
its untouched source in the root drift; transient network errors retry
once after a backoff). Nothing is force-pushed; ``python -m poseidon
heal [--apply|--deep]`` exposes the deeper diagnostics.

States live under ``poseidon/data/``: ``tides.jsonl`` ledger and
``state.json`` (tide sequence, failure count, quarantine window).
"""

import json
import os
import random
import subprocess
import sys
import time

from forseti.locker import LaneLock, status as lane_status
from ratatosk.bus import beat, publish

VERSION = 1

ORGAN = "poseidon"
TOPIC = "poseidon"

BRANCH = "auto/poseidon"
WORKTREE_REL = os.path.join(".worktrees", "poseidon")
LANE = "push-main"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(HERE, "data")
LEDGER_PATH = os.path.join(DATA_DIR, "tides.jsonl")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

# Runtime churn this organ itself produces - plus the writer
# worktrees - must never join the sweep, even if unignored somewhere.
SWEEP_EXCLUDES = (".worktrees", "poseidon/data")

CADENCE_S = 300.0          # watch-loop nap between tides (idle)
ACTIVE_DELAY_S = 20.0      # quick follow-up after a shipped tide
FAIL_BACKOFF_BASE_S = 120.0  # exponential seed after a failed tide
FETCH_MIN_GAP_S = 45.0     # throttle: never re-fetch more often
JITTER_FRACTION = 0.15     # de-synchronize parallel tides +/- 15%
LOCK_WAIT_S = 60.0         # max wait for the FORSETI lane
LOCK_STALE_S = 900.0       # our section may legally run long
GIT_TIMEOUT_S = 300.0      # network ops (fetch/push/gh)
FAIL_LIMIT = 3             # consecutive failures -> quarantine
QUARANTINE_COOLDOWN_S = 1800.0
LEDGER_MAX_BYTES = 2_000_000
LEDGER_ROTATIONS = 3
RESTORE_BATCH = 40         # paths per checkout call
SUBJECT_MAX = 72
IDX_MAX_AGE_S = 3600.0     # orphaned throwaway indexes earn a sweep

# push self-healing: one spaced retry for transient transport errors,
# branch adoption + snapshot replay for non-fast-forward rejections


def _env_float(name, fallback):
    try:
        return float(os.environ.get(name, fallback))
    except (TypeError, ValueError):
        return fallback


RETRY_BACKOFF_S = _env_float("POSEIDON_RETRY_BACKOFF_S", 5.0)

PUSH_NONFF_MARKERS = ("non-fast-forward", "fetch first",
                      "failed to push")
TRANSIENT_MARKERS = ("timed out", "timeout", "could not resolve host",
                     "connection", "rpc failed", "ssl", "tls",
                     "rate limit", "network", "broken pipe",
                     "early eof", "502", "503", "504")


def is_transient(text):
    """Transport-grade noise worth one retry, not a verdict."""
    t = str(text).lower()
    return any(m in t for m in TRANSIENT_MARKERS)


MERGE_MODES = ("squash", "review", "local")


# ---------------------------------------------------------------- git

def _git(root, *args, timeout=120.0, check=True, env_extra=None):
    """Run git in ``root``; stdout on success, RuntimeError on failure."""
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        ["git", "-C", root] + [str(a) for a in args],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError("git %s failed: %s"
                           % (" ".join(args[:2]),
                              (proc.stderr or proc.stdout).strip()[:400]))
    # rstrip only: porcelain's LEADING status column is meaningful
    return proc.stdout.rstrip()


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _canon(text):
    """EOL-insensitive content identity for settle guards."""
    return text.replace("\r\n", "\n").rstrip()


class Snapshot:
    """A committed image of the drift, safe to carry across checkouts."""

    def __init__(self, tree, commit, tracked, untracked):
        self.tree = tree
        self.commit = commit
        self.tracked = tracked      # modified/deleted vs HEAD
        self.untracked = untracked  # new files (removed at settle)


# ------------------------------------------------------------ engine

class TideEngine:
    def __init__(self, root=ROOT, mode="squash", interval=CADENCE_S,
                 bus=True, gh="gh"):
        self.root = os.path.abspath(root)
        self.worktree = os.path.join(self.root, WORKTREE_REL)
        self.mode = mode if mode in MERGE_MODES else "squash"
        self.interval = float(interval)
        self.bus = bool(bus)
        self.gh = gh
        self.data_dir = os.path.join(
            self.root, os.path.relpath(DATA_DIR, ROOT))
        self.ledger_path = os.path.join(self.data_dir, "tides.jsonl")
        self.state_path = os.path.join(self.data_dir, "state.json")
        self._lock_root = os.path.join(self.root, "data", "post")
        self._last_fetch = 0.0  # monotonic throttle for refresh_remote

    # ---------------- state ----------------

    def _load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {"seq": 0, "failures": 0, "quarantine_until": 0.0,
                    "reason": ""}

    def _save_state(self, st):
        os.makedirs(self.data_dir, exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.state_path)

    def _ledger(self, row):
        os.makedirs(self.data_dir, exist_ok=True)
        try:
            if os.path.getsize(self.ledger_path) > LEDGER_MAX_BYTES:
                for i in range(LEDGER_ROTATIONS - 1, 0, -1):
                    src = "%s.%d" % (self.ledger_path, i)
                    if os.path.exists(src):
                        os.replace(src, "%s.%d" % (self.ledger_path, i + 1))
                os.replace(self.ledger_path, self.ledger_path + ".1")
        except OSError:
            pass
        row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(self.ledger_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    def _say(self, kind, payload):
        if not self.bus:
            return
        beat(ORGAN, note=kind)
        publish(TOPIC, payload, frm=ORGAN, kind=kind)

    # ---------------- reading ----------------

    def drift(self):
        """Classified uncommitted change: {"tracked": [...],
        "untracked": [...]}. Rename noise is split via --no-renames."""
        out = _git(self.root, "status", "--porcelain",
                   "--untracked-files=all", "--no-renames")
        tracked, untracked = [], []
        for ln in out.splitlines():
            if len(ln) < 4:
                continue
            path = ln[3:].strip().strip('"')
            if not path:
                continue
            (untracked if ln.startswith("??") else tracked).append(path)
        return {"tracked": tracked, "untracked": untracked}

    @staticmethod
    def _areas(paths):
        counts = {}
        for p in paths:
            top = p.replace("\\", "/").split("/")[0]
            counts[top] = counts.get(top, 0) + 1
        order = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return ", ".join("%s x%d" % (a, n) for a, n in order[:4])

    def message(self, drift, seq_next):
        n = len(drift["tracked"]) + len(drift["untracked"])
        subject = "poseidon: tide %d sweeps %d files" % (seq_next, n)
        areas = self._areas(drift["tracked"] + drift["untracked"])
        if areas:
            subject += " (%s)" % areas
        body_lines = []
        for p in (drift["tracked"] + drift["untracked"])[:20]:
            body_lines.append("- %s" % p.replace("\\", "/"))
        extra = len(drift["tracked"]) + len(drift["untracked"]) - 20
        if extra > 0:
            body_lines.append("- ...and %d more" % extra)
        return subject[:SUBJECT_MAX], "\n".join(body_lines)

    # ---------------- snapshot (throwaway index) ----------------

    def _head_info(self):
        """(sha, tree) of HEAD in one git call."""
        out = _git(self.root, "show", "-s", "--format=%H %T", "HEAD")
        sha, tree = out.split()
        return sha, tree

    def refresh_remote(self, force=False):
        """ONE fetch at the shared root updates remote-tracking refs
        for every worktree in the fleet (they all share one object
        store). Throttled to FETCH_MIN_GAP_S."""
        now = time.monotonic()
        if not force and now - self._last_fetch < FETCH_MIN_GAP_S:
            return False
        _git(self.root, "fetch", "origin", "--prune",
             timeout=GIT_TIMEOUT_S)
        self._last_fetch = now
        return True

    def snapshot(self, drift, message):
        """Commit drift to a temp-index commit WITHOUT touching the
        root index/working tree. Returns a Snapshot or None when the
        tree matches HEAD (nothing real to move)."""
        os.makedirs(self.data_dir, exist_ok=True)
        idx = os.path.join(self.data_dir,
                           "idx-%d" % os.getpid())
        env = {"GIT_INDEX_FILE": idx}
        try:
            head, head_tree = self._head_info()
            _git(self.root, "read-tree", "HEAD", env_extra=env)
            # plain add honors .gitignore; naming ignored paths in
            # pathspec exclusions would trip git's refused-add guard
            _git(self.root, "add", "-A", env_extra=env)
            for ex in SWEEP_EXCLUDES:
                _git(self.root, "update-index", "--force-remove",
                     "-r", "--", ex, check=False, env_extra=env)
            tree = _git(self.root, "write-tree", env_extra=env)
            if tree == head_tree:
                return None
            args = ["commit-tree", tree, "-p", head, "-m", message]
            commit = _git(self.root, *args, env_extra=env)
            return Snapshot(tree, commit,
                            drift["tracked"], drift["untracked"])
        finally:
            try:
                os.unlink(idx)
            except OSError:
                pass

    # ---------------- worktree lane ----------------

    @staticmethod
    def branch_of(name):
        return "auto/%s" % name

    def wt_path(self, name):
        return os.path.join(self.root, ".worktrees", name)

    def ensure_worktree(self, name=ORGAN):
        path = self.wt_path(name)
        branch = self.branch_of(name)
        if os.path.exists(os.path.join(path, ".git")):
            return
        have = _git(self.root, "rev-parse", "--verify",
                    "--quiet", branch, check=False)
        args = (["worktree", "add", path, branch] if have
                else ["worktree", "add", "-b", branch, path])
        _git(self.root, *args)
        if not _git(path, "config", "user.email", check=False):
            _git(path, "config", "user.name", "poseidon")
            _git(path, "config", "user.email",
                 "poseidon@olympos.local")

    def sync_branch(self, name=ORGAN):
        """Absorb origin/main into a berth branch using LOCAL state
        only - the shared fetch (refresh_remote) already updated every
        remote-tracking ref in the fleet's common object store."""
        path = self.wt_path(name)
        code = subprocess.run(
            ["git", "-C", path, "pull", "--ff-only", "origin", "main"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
        if code.returncode != 0:
            merged = subprocess.run(
                ["git", "-C", path, "merge", "origin/main",
                 "--no-edit"],
                capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
            if merged.returncode != 0:
                _git(path, "merge", "--abort", check=False)
                raise RuntimeError("cannot sync %s with main: %s"
                                   % (self.branch_of(name),
                                      merged.stderr.strip()[:200]))

    def cherry_pick(self, snap):
        proc = subprocess.run(
            ["git", "-C", self.worktree, "cherry-pick", "-x",
             snap.commit],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
        if proc.returncode == 0:
            tip_tree = _git(self.worktree, "rev-parse", "HEAD^{tree}")
            return tip_tree
        _git(self.worktree, "cherry-pick", "--abort", check=False)
        raise RuntimeError("cherry-pick conflicted: %s"
                           % proc.stderr.strip()[:200])

    def push_branch(self):
        _git(self.worktree, "push", "-u", "origin", BRANCH,
             timeout=GIT_TIMEOUT_S)

    # ---------------- PR layer (overridable for gates) ----------------

    def _gh(self, *args):
        try:
            return self._gh_call(*args)
        except RuntimeError as exc:
            if is_transient(exc):
                time.sleep(RETRY_BACKOFF_S)
                return self._gh_call(*args)
            raise

    def _gh_call(self, *args):
        proc = subprocess.run([self.gh] + list(args),
                              capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_S)
        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            raise RuntimeError("gh %s failed: %s"
                               % (args[0],
                                  (proc.stderr or out).strip()[:200]))
        return out

    def ship_pr(self, subject):
        if self.mode == "local":
            return None
        existing = ""
        try:
            existing = self._gh("pr", "list", "--head", BRANCH,
                                "--state", "open", "--json", "number",
                                "-q", ".[0].number")
        except RuntimeError:
            pass
        pr = existing or self._gh(
            "pr", "create", "--base", "main", "--head", BRANCH,
            "--title", subject,
            "--body", "POSEIDON automated tide per FLOW.md protocol.")
        if self.mode == "review":
            return str(pr)
        self._gh("pr", "merge", str(pr), "--squash", "--delete-branch")
        return str(pr)

    # ---------------- settling the mirror ----------------

    def _unlink_quiet(self, path):
        try:
            os.unlink(os.path.join(self.root, path))
        except OSError:
            pass

    def settle_mirror(self, snap):
        """Root gives up its copy only now - the content already lives
        on origin. Guarded: a path a writer touched AFTER the snapshot
        (content no longer matches it) is skipped, never clobbered;
        the mirror pull then simply waits for the next quiet tide."""
        result = {"restored": [], "skipped": [], "pulled": False}

        def norm(p):
            return p.replace("\\", "/")

        if snap.tracked:
            diverged = set()
            for batch in _chunks(snap.tracked, RESTORE_BATCH):
                out = _git(self.root, "diff", "--name-only",
                           snap.commit, "--", *batch, check=False)
                diverged.update(norm(x) for x in out.splitlines() if x)
            safe = [p for p in snap.tracked if norm(p) not in diverged]
            result["skipped"].extend(
                p for p in snap.tracked if norm(p) in diverged)
            for batch in _chunks(safe, RESTORE_BATCH):
                _git(self.root, "checkout", "--", *batch)
            result["restored"].extend(safe)

        for p in snap.untracked:
            want = os.path.join(self.root, p)
            if not os.path.exists(want):
                continue  # already gone; incoming main restores it
            try:
                have = _git(self.root, "cat-file", "blob",
                            "%s:%s" % (snap.commit, norm(p)),
                            check=False)
            except RuntimeError:
                continue  # path never landed in the snapshot
            have = None
            try:
                have = _git(self.root, "cat-file", "blob",
                            "%s:%s" % (snap.commit, norm(p)),
                            check=False)
            except RuntimeError:
                continue  # path never landed in the snapshot
            with open(want, encoding="utf-8", errors="replace") as fh:
                # EOL-tolerant: CRLF translation is noise; a semantic
                # writer edit always survives normalization
                same = _canon(fh.read()) == _canon(have)
            # unlink only AFTER our own read handle is closed - a
            # still-open handle makes Windows refuse the delete
            if same:
                self._unlink_quiet(p)
                result["restored"].append(p)
            else:
                result["skipped"].append(p)

        code = subprocess.run(
            ["git", "-C", self.root, "pull", "--ff-only",
             "origin", "main"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
        result["pulled"] = code.returncode == 0
        if not result["pulled"]:
            first = (code.stderr or "").strip().splitlines()
            result["pull_note"] = (first[0] if first else
                                   "mirror ff refused")[:160]
        return result

    # ---------------- cycle ----------------

    def quarantined(self, st=None):
        st = st or self._load_state()
        return time.time() < float(st.get("quarantine_until", 0.0))

    def next_delay(self, verdict, failures=0):
        """Seconds the watch loop should sleep after this verdict:
        sprint after shipped tides, exponential respect after
        failures, calm cadence on still water."""
        if verdict == "shipped":
            base = ACTIVE_DELAY_S
        elif verdict == "failed":
            n = max(1, failures)
            base = min(QUARANTINE_COOLDOWN_S,
                       FAIL_BACKOFF_BASE_S * (2 ** (n - 1)))
        else:
            base = self.interval
        return max(5.0, base)

    def _auto_heal(self):
        """Light self-repair before every real tide. Never fatal."""
        try:
            from . import heal
            return heal.auto_pass(self)
        except Exception as exc:              # noqa: BLE001 - soft
            return {"applied": [],
                    "errors": ["auto-pass: %s" % str(exc)[:120]]}

    def replay_cargo(self, snap):
        """Tier-2 heal replay: overlay ONLY the swept paths from the
        snapshot onto the current tip. Harmless foreign cargo on our
        single-writer branch survives; contested paths take the sweep,
        because the root drift is the newer writer intent."""
        paths = [p.replace("\\", "/")
                 for p in list(snap.tracked) + list(snap.untracked)]
        for batch in _chunks(paths, RESTORE_BATCH):
            _git(self.worktree, "restore", "--source", snap.commit,
                 "--staged", "--worktree", "--", *batch)
        if not _git(self.worktree, "status",
                    "--porcelain").strip():
            return                          # cargo already aboard
        subject = _git(self.worktree, "show", "-s",
                       "--format=%s", snap.commit)[:SUBJECT_MAX]
        _git(self.worktree, "commit", "-m", subject)

    def _push_with_heal(self, snap, report):
        """Push with auto-fixes. A non-fast-forward rejection means
        origin's copy of OUR single-writer branch moved without us
        (crash residue): adopt it, replay the snapshot - its source
        content still waits untouched in the root drift - and push
        again. Transient transport errors retry once after a backoff.
        Never force-pushes; an unclean reconcile raises into the
        quarantine breaker like any other failure."""
        applied = report.setdefault("heal", {}).setdefault(
            "applied", [])
        try:
            self.push_branch()
            return
        except RuntimeError as exc:
            text = str(exc).lower()
            if any(m in text for m in PUSH_NONFF_MARKERS):
                self.refresh_remote(force=True)
                _git(self.worktree, "reset", "--hard",
                     "origin/%s" % BRANCH)
                self.sync_branch()
                try:
                    self.cherry_pick(snap)
                except RuntimeError:
                    self.replay_cargo(snap)
                applied.append(
                    "push-nonff:branch-adopted+cargo-replayed")
                self.push_branch()
            elif is_transient(text):
                time.sleep(RETRY_BACKOFF_S)
                applied.append("push-transient:retried")
                self.push_branch()
            else:
                raise

    def once(self, dry_run=False):
        """One tide. Returns a report dict (also written to ledger on
        real runs). Private worktree work runs OUTSIDE the FORSETI
        lane; only push -> PR/merge -> mirror-settle holds it."""
        st = self._load_state()
        report = {"mode": self.mode, "verdict": "idle", "seq": st["seq"]}

        if dry_run:
            drift = self.drift()
            n_files = len(drift["tracked"]) + len(drift["untracked"])
            report["files"] = n_files
            report["verdict"] = "dry-run"
            report["plan"] = {
                "tracked": drift["tracked"][:50],
                "untracked": drift["untracked"][:50]}
            return report

        report["heal"] = self._auto_heal()
        st = self._load_state()   # the heal pass may have reopened the lane

        if self.quarantined(st):
            report["verdict"] = "quarantined"
            report["reason"] = st.get("reason", "")
            self._say("tide-idle", report)
            return report

        drift = self.drift()
        n_files = len(drift["tracked"]) + len(drift["untracked"])
        report["files"] = n_files

        if n_files == 0:
            self.refresh_remote()
            self._sync_mirror_soft(report)
            report["verdict"] = "still-water"
            self._say("tide-idle", report)
            return report

        lock = None
        try:
            # ---- private waters: no lane needed ------------------
            self.ensure_worktree()
            self.refresh_remote()
            self.sync_branch()
            seq_next = st["seq"] + 1
            subject, body = self.message(drift, seq_next)
            full_msg = subject if not body else subject + "\n\n" + body
            snap = self.snapshot(drift, full_msg)
            if snap is None:
                report["verdict"] = "still-water"
                self._sync_mirror_soft(report)
                return report
            tip_tree = _git(self.worktree,
                            "rev-parse", "HEAD^{tree}")
            if tip_tree == snap.tree:
                # identical content already sits on the branch: we are
                # waiting on a review-mode merge, not on new work.
                report["verdict"] = "awaiting-merge"
                self._ledger(dict(report))
                self._say("tide-idle", report)
                return report
            # a cherry-pick conflict here is a REAL content collision
            # with advanced main: it must fail into the quarantine
            # breaker, never be auto-overridden (gate-enforced)
            self.cherry_pick(snap)

            # ---- shared waters: hold the FORSETI lane ------------
            lock = LaneLock(LANE, stale_s=LOCK_STALE_S,
                            note="poseidon tide", root=self._lock_root)
            if not lock.acquire(timeout=LOCK_WAIT_S):
                report["verdict"] = "lane-busy"
                report["holder"] = lane_status(LANE,
                                               root=self._lock_root)
                self._ledger(dict(report))
                self._say("tide-failed", report)
                return report
            self._push_with_heal(snap, report)
            pr = self.ship_pr(subject)

            st["seq"] = seq_next
            report.update({"verdict": "shipped", "seq": seq_next,
                           "commit": snap.commit[:12], "subject": subject,
                           "pr": pr, "merged": self.mode == "squash"})
            if self.mode == "squash":
                report["settled"] = self.settle_mirror(snap)
            st["failures"] = 0
            st["reason"] = ""
            self._save_state(st)
            self._ledger(dict(report))
            self._say("tide", report)
            return report
        except Exception as exc:                  # noqa: BLE001 - gate
            report["verdict"] = "failed"
            report["error"] = ("%s: %s" % (type(exc).__name__,
                                           exc))[:300]
            st["failures"] = int(st.get("failures", 0)) + 1
            if st["failures"] >= FAIL_LIMIT:
                st["quarantine_until"] = time.time() + \
                    QUARANTINE_COOLDOWN_S
                st["reason"] = report["error"]
            self._save_state(st)
            self._ledger(dict(report))
            self._say("tide-failed", report)
            return report
        finally:
            if lock is not None:
                lock.release()

    def _sync_mirror_soft(self, report):
        """Keep the mirror drinking even on quiet days. A refusal (new
        upstream commits meeting local dirt) is recorded, not fatal."""
        try:
            out = _git(self.root, "pull", "--ff-only", "origin", "main",
                       timeout=GIT_TIMEOUT_S, check=False)
            report["pull"] = (out.splitlines() or [""])[0][:120]
        except Exception as exc:              # noqa: BLE001 - soft
            report["pull"] = "refused: %s" % str(exc)[:120]

    def watch(self, max_cycles=0):
        c = 0
        while True:
            rep = self.once()
            print("[%s] tide verdict=%s files=%s"
                  % (time.strftime("%H:%M:%S"), rep.get("verdict"),
                     rep.get("files", "-")), flush=True)
            c += 1
            if max_cycles and c >= max_cycles:
                return 0
            delay = self.next_delay(rep.get("verdict"),
                                    rep.get("failures",
                                            self._load_state()
                                            .get("failures", 0)))
            jitter = 1.0 + random.uniform(-JITTER_FRACTION,
                                          JITTER_FRACTION)
            time.sleep(max(5.0, delay * jitter))

    def resume(self):
        st = self._load_state()
        st["failures"] = 0
        st["quarantine_until"] = 0.0
        st["reason"] = ""
        self._save_state(st)
        return st

    def status(self):
        st = self._load_state()
        rows = []
        try:
            with open(self.ledger_path, encoding="utf-8") as fh:
                rows = [json.loads(x) for x in
                        fh.read().splitlines()[-5:] if x.strip()]
        except (OSError, ValueError):
            pass
        return {
            "root": self.root,
            "branch": BRANCH,
            "worktree": self.worktree,
            "worktree_ready": os.path.exists(
                os.path.join(self.worktree, ".git")),
            "mode": self.mode,
            "interval_s": self.interval,
            "seq": st.get("seq", 0),
            "failures": st.get("failures", 0),
            "quarantined": self.quarantined(st),
            "quarantine_reason": st.get("reason", ""),
            "lane": lane_status(LANE, root=self._lock_root),
            "recent_tides": rows,
        }


def default_mode():
    return os.environ.get("POSEIDON_MODE", "squash")


def default_interval():
    try:
        return float(os.environ.get("POSEIDON_INTERVAL", CADENCE_S))
    except (TypeError, ValueError):
        return CADENCE_S
