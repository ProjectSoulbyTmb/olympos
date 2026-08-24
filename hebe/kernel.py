"""HEBE kernel - the Legal & Document Scribe that never drops a line.

Charter (operator's standing L2 grant - see content.STANDING_GRANT):
  - FULL DICTATION PRIVILEGES: HEBE may create or amend any file inside
    the workspace without asking - except the load-bearing walls
    (``.git/``, ``.worktrees/``) and every credential carrier; secret
    formations are refused at the pen, never written.
  - FULL AUTONOMY: no confirmation gate. She boots, records the oath,
    seeds the license if the tree lacks one, drains her inbox, and
    ships what she wrote through the sanctioned lane.
  - AUTO COMMIT AND PUSH: dictated paths - only those paths - are
    snapshotted via a throwaway index (the root index/working tree is
    never touched mid-cycle), carried onto ``auto/hebe`` in a private
    worktree, pushed under FORSETI's ``push-main`` lock, opened as a
    PR and squash-merged; then the mirror settles.

Legal knowledge: a codified corpus lives in ``content.py`` (licenses,
notices, classification, trade-secret discipline, NDA anatomy,
open-sourcing checklist, trademark boundary, DMCA recipe) surfaced by
``advise`` and applied by ``license``/``seal-ip``.

Failure stance: "quarantine, never destroy". Refusals leave the tree
untouched and land in the ledger; three consecutive failed cycles trip
the breaker for a cooldown; ``resume`` reopens the lane.

State lives under ``hebe/data/``: decrees.jsonl ledger, state.json;
tracked records live in ``hebe/records/`` (oaths.jsonl,
ip-register.jsonl) and ship WITH the repository.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time

from forseti.locker import LaneLock, status as lane_status
from ratatosk.bus import beat, publish

from . import content as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
LEDGER_PATH = os.path.join(DATA_DIR, "decrees.jsonl")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

# Fixed lanes the scribe always owes to git when they are dirty.
ALWAYS_OWED = ("LICENSE", C.OATHS_REL, C.IP_REGISTER_REL)

_SECRET_FILE_RES = tuple(re.compile(p) for p in C.SECRET_FILE_PATTERNS)
_SECRET_CONTENT_RES = tuple(re.compile(p)
                            for p in C.SECRET_CONTENT_PATTERNS)


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
    return proc.stdout.rstrip()


def _chunks(items, size):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Refusal(Exception):
    """A dictation the scribe will not take."""


# ------------------------------------------------------------ engine

class Scribe:
    def __init__(self, root=ROOT, mode=C.DEFAULT_MODE,
                 interval=C.CADENCE_S, bus=True, gh="gh"):
        self.root = os.path.abspath(root)
        self.worktree = os.path.join(self.root, C.WORKTREE_REL)
        self.mode = mode if mode in C.MERGE_MODES else C.DEFAULT_MODE
        self.interval = float(interval)
        self.bus = bool(bus)
        self.gh = gh
        self.data_dir = os.path.join(
            self.root, os.path.relpath(DATA_DIR, ROOT))
        self.inbox_dir = os.path.join(self.root, C.INBOX_REL)
        self.filed_dir = os.path.join(self.root, C.FILED_REL)
        self.records_dir = os.path.join(self.root, C.RECORDS_REL)
        self.ledger_path = os.path.join(self.data_dir, "decrees.jsonl")
        self.state_path = os.path.join(self.data_dir, "state.json")
        self.oaths_path = os.path.join(self.root, C.OATHS_REL)
        self.ip_path = os.path.join(self.root, C.IP_REGISTER_REL)
        self._lock_root = os.path.join(self.root, "data", "post")
        # paths this process has touched and owes to the lane
        self.pending = []

    # ---------------- state / ledgers ----------------

    def _load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {"seq": 0, "row": 0, "last_shipped_row": 0,
                    "failures": 0, "quarantine_until": 0.0,
                    "reason": ""}

    def _save_state(self, st):
        os.makedirs(self.data_dir, exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.state_path)

    def _append_ledger(self, path, row):
        """Append one JSONL row; rotate when the ledger grows fat."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            if os.path.getsize(path) > C.LEDGER_MAX_BYTES:
                for i in range(C.LEDGER_ROTATIONS - 1, 0, -1):
                    src = "%s.%d" % (path, i)
                    if os.path.exists(src):
                        os.replace(src, "%s.%d" % (path, i + 1))
                os.replace(path, path + ".1")
        except OSError:
            pass
        row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    def _ledger(self, row):
        """Append a decree row, stamped with the persistent row
        counter - the counter is how the lane remembers its debts
        across process restarts."""
        st = self._load_state()
        row["row"] = int(st.get("row", 0)) + 1
        st["row"] = row["row"]
        self._save_state(st)
        self._append_ledger(self.ledger_path, row)

    def owed_paths(self):
        """Paths the lane owes: everything written since the last
        successful ship (per the ledger's row numbers) plus the fixed
        record lanes. Refusals never appear; git has the final say."""
        st = self._load_state()
        last = int(st.get("last_shipped_row", 0))
        cands = set(ALWAYS_OWED)
        try:
            with open(self.ledger_path, encoding="utf-8") as fh:
                for ln in fh.read().splitlines():
                    if not ln.strip():
                        continue
                    try:
                        r = json.loads(ln)
                    except ValueError:
                        continue
                    if r.get("verdict") != "written":
                        continue
                    if int(r.get("row", 0)) > last:
                        p = r.get("path")
                        if p:
                            cands.add(p)
        except OSError:
            pass
        return sorted(c.replace("\\", "/") for c in cands)

    def _say(self, kind, payload):
        if not self.bus:
            return
        beat(C.ORGAN, note=kind)
        publish(C.TOPIC, payload, frm=C.ORGAN, kind=kind)

    def quarantined(self, st=None):
        st = st or self._load_state()
        return time.time() < float(st.get("quarantine_until", 0.0))

    # ---------------- scope law ----------------

    @staticmethod
    def classify_refusal(rel):
        """Return a refusal reason, or None when dictation is lawful."""
        rel = str(rel).replace("\\", "/").strip().lstrip("/")
        if not rel or rel.endswith("/"):
            return "empty-or-directory-path"
        if ":" in rel.split("/")[0] or rel.startswith("//"):
            return "absolute-or-foreign-path"
        parts = rel.split("/")
        for i in range(len(parts)):
            if parts[i] == "..":
                return "parent-traversal"
            if parts[i] in C.DENY_DIRS:
                return "load-bearing-wall:%s" % parts[i]
        for rx in _SECRET_FILE_RES:
            if rx.search(rel):
                return "credential-carrier-filename"
        return None

    @staticmethod
    def content_refusal(text):
        for rx in _SECRET_CONTENT_RES:
            m = rx.search(text)
            if m:
                return "secret-formation:%s..." % m.group(0)[:12]
        return None

    def _resolve(self, rel):
        target = os.path.realpath(os.path.join(self.root, rel))
        root_real = os.path.realpath(self.root)
        if target != root_real and not \
                target.startswith(root_real + os.sep):
            raise Refusal("escapes-workspace-root")
        return target

    # ---------------- dictation ----------------

    def dictate(self, rel, text, title="", classification="internal",
                record=True):
        """Write ``text`` to ``rel`` under full dictation privileges.
        Returns the decree row. Raises Refusal - never writes - when
        the walls, credential carriers or secret formations say no;
        every refusal is journaled (witness doctrine)."""
        reason = self.classify_refusal(rel)
        if reason:
            if record:
                self.refuse(rel, reason)
            raise Refusal(reason)
        text = str(text)
        if not text.endswith("\n"):
            text += "\n"
        reason = self.content_refusal(text)
        if reason:
            if record:
                self.refuse(rel, reason)
            raise Refusal(reason)
        cls = classification if classification in C.CLASSIFICATIONS \
            else "internal"
        try:
            target = self._resolve(rel)
        except Refusal:
            if record:
                self.refuse(rel, "escapes-workspace-root")
            raise
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".hebe-tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, target)
        row = {"verb": "dictate", "path": rel.replace("\\", "/"),
               "title": title[:80], "bytes": len(text),
               "sha256": _sha256_text(text), "classification": cls,
               "verdict": "written"}
        if record:
            st = self._load_state()
            row["seq"] = st["seq"]
            self._ledger(dict(row))
        if rel.replace("\\", "/") not in self.pending:
            self.pending.append(rel.replace("\\", "/"))
        return row

    def refuse(self, rel, reason):
        st = self._load_state()
        self._ledger({"seq": st["seq"], "verb": "dictate",
                      "path": str(rel).replace("\\", "/"),
                      "verdict": "refused", "reason": reason})

    # ---------------- legal duties ----------------

    def seed_license(self, spdx=None, holder=None, year=""):
        """First-cycle duty: give the platform its copyright shield."""
        lic_rel = "LICENSE"
        if os.path.exists(os.path.join(self.root, lic_rel)):
            return None
        spdx = spdx or C.DEFAULT_LICENSE
        holder = holder or C.DEFAULT_HOLDER
        year = year or time.strftime("%Y")
        text = C.license_text(spdx, year=year, holder=holder)
        row = self.dictate(lic_rel, text, title="platform license",
                           classification="public")
        row["verb"] = "seed-license"
        row["spdx"] = spdx
        return row

    def ensure_oath(self):
        """Record the standing grant exactly once (tracked ledger)."""
        try:
            with open(self.oaths_path, encoding="utf-8") as fh:
                for ln in fh.read().splitlines():
                    try:
                        r = json.loads(ln)
                        g = r.get("grant") or {}
                        if g.get("grant_class") == \
                                C.STANDING_GRANT["grant_class"] \
                                and g.get("standing"):
                            return None
                    except ValueError:
                        continue
        except OSError:
            pass
        row = {"kind": "oath", "grant": C.STANDING_GRANT,
               "text": C.OATH_TEXT}
        self._append_ledger(self.oaths_path, dict(row))
        rec = os.path.relpath(self.oaths_path, self.root).replace("\\", "/")
        if rec not in self.pending:
            self.pending.append(rec)
        return row

    def seal_ip(self, rel, classification="internal"):
        """Append an IP-register row sealing the asset's current form."""
        target = os.path.join(self.root, rel)
        digest = ""
        try:
            with open(target, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            pass
        row = {"kind": "ip-seal", "path": rel.replace("\\", "/"),
               "classification": classification,
               "sha256": digest}
        self._append_ledger(self.ip_path, dict(row))
        reg = os.path.relpath(self.ip_path, self.root).replace("\\", "/")
        if reg not in self.pending:
            self.pending.append(reg)
        return row

    def register_protected_assets(self):
        """First boot only: seal the house asset list so the IP
        register starts populated. Later boots leave history alone."""
        try:
            if os.path.getsize(self.ip_path) > 0:
                return []
        except OSError:
            pass
        rows = []
        for rel, cls in C.PROTECTED_ASSETS:
            rows.append(self.seal_ip(rel, cls))
        return rows

    # ---------------- knowledge ----------------

    def advise(self, topic=None):
        if topic is None:
            return {"topics": C.knowledge_topics(),
                    "licenses": sorted(C.LICENSES),
                    "disclaimer": C.DISCLAIMER}
        entries = C.KNOWLEDGE.get(topic)
        if entries is None:
            return {}
        return {"topic": topic, "entries": list(entries),
                "disclaimer": C.DISCLAIMER}

    # ---------------- reading ----------------

    def pending_letters(self):
        if not os.path.isdir(self.inbox_dir):
            return []
        out = []
        for name in sorted(os.listdir(self.inbox_dir)):
            p = os.path.join(self.inbox_dir, name)
            if os.path.isfile(p) and name.endswith(".json"):
                out.append(name)
        return out

    def drain_inbox(self):
        """Claim-run-file every drop-in letter. Returns report rows."""
        rows = []
        for name in self.pending_letters():
            src = os.path.join(self.inbox_dir, name)
            stamp = time.strftime("%Y%m%dT%H%M%S")
            dst = os.path.join(self.filed_dir, "%s-%s"
                               % (stamp, name))
            verdict = {"letter": name}
            try:
                with open(src, encoding="utf-8") as fh:
                    letter = json.load(fh)
                action = letter.get("action", "dictate")
                if action == "license":
                    r = self.seed_license(letter.get("spdx"),
                                          letter.get("holder"))
                    verdict.update({"action": action,
                                    "verdict": "written" if r
                                    else "already-covered"})
                elif action == "seal-ip":
                    r = self.seal_ip(letter["path"],
                                     letter.get("classification",
                                                "internal"))
                    verdict.update({"action": action,
                                    "verdict": "sealed"})
                else:
                    r = self.dictate(letter["path"],
                                     letter.get("text", ""),
                                     title=letter.get("title", ""),
                                     classification=letter.get(
                                         "classification",
                                         "internal"))
                    verdict.update({"action": "dictate",
                                    "path": r["path"],
                                    "verdict": "written"})
            except Refusal as exc:
                verdict.update({"verdict": "refused",
                                "reason": str(exc)})
            except Exception as exc:              # noqa: BLE001 - gate
                verdict.update({"verdict": "failed",
                                "reason": ("%s: %s"
                                           % (type(exc).__name__,
                                              exc))[:200]})
            os.makedirs(self.filed_dir, exist_ok=True)
            try:
                os.replace(src, dst)
            except OSError:
                pass
            rows.append(verdict)
        return rows

    # ---------------- snapshot (throwaway index, scoped) ----------------

    def scoped_drift(self, paths):
        out = _git(self.root, "status", "--porcelain",
                   "--untracked-files=all", "--no-renames")
        want = set(paths)
        tracked, untracked = [], []
        for ln in out.splitlines():
            if len(ln) < 4:
                continue
            path = ln[3:].strip().strip('"').replace("\\", "/")
            if path in want:
                (untracked if ln.startswith("??") else
                 tracked).append(path)
        return {"tracked": tracked, "untracked": untracked}

    def snapshot_scoped(self, paths, message):
        """Commit ONLY ``paths`` into a throwaway-index commit; the
        root index/working tree is never touched. The snapshot is
        parented on the writer branch tip whenever the lane exists,
        so consecutive decrees are increments of HEBE's own history
        and can never self-conflict. Returns (tree, commit) or None
        when those paths add nothing new."""
        idx = os.path.join(self.data_dir, "idx-%d" % os.getpid())
        env = {"GIT_INDEX_FILE": idx}
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            if os.path.exists(os.path.join(self.worktree, ".git")):
                base = _git(self.worktree, "rev-parse", "HEAD")
            else:
                base = _git(self.root, "rev-parse", "HEAD")
            _git(self.root, "read-tree", base, env_extra=env)
            for batch in _chunks(paths, C.RESTORE_BATCH):
                _git(self.root, "add", "-A", "--", *batch,
                     env_extra=env)
            tree = _git(self.root, "write-tree", env_extra=env)
            if tree == _git(self.root,
                            "rev-parse", "%s^{tree}" % base):
                return None
            commit = _git(self.root, "commit-tree", tree, "-p",
                          base, "-m", message, env_extra=env)
            return tree, commit
        finally:
            try:
                os.unlink(idx)
            except OSError:
                pass

    # ---------------- worktree lane ----------------

    def ensure_worktree(self):
        if os.path.exists(os.path.join(self.worktree, ".git")):
            return
        have = _git(self.root, "rev-parse", "--verify",
                    "--quiet", C.BRANCH, check=False)
        args = (["worktree", "add", self.worktree, C.BRANCH] if have
                else ["worktree", "add", "-b", C.BRANCH, self.worktree])
        _git(self.root, *args)
        if not _git(self.worktree, "config", "user.email", check=False):
            _git(self.worktree, "config", "user.name", "hebe")
            _git(self.worktree, "config", "user.email",
                 "hebe@yggdrasil.local")

    def sync_branch(self):
        _git(self.worktree, "fetch", "origin", "--prune",
             timeout=C.GIT_TIMEOUT_S)
        code = subprocess.run(
            ["git", "-C", self.worktree, "pull", "--ff-only",
             "origin", "main"],
            capture_output=True, text=True, timeout=C.GIT_TIMEOUT_S)
        if code.returncode != 0:
            merged = subprocess.run(
                ["git", "-C", self.worktree, "merge", "origin/main",
                 "--no-edit"],
                capture_output=True, text=True, timeout=C.GIT_TIMEOUT_S)
            if merged.returncode != 0:
                _git(self.worktree, "merge", "--abort", check=False)
                raise RuntimeError("cannot sync %s with main: %s"
                                   % (C.BRANCH,
                                      merged.stderr.strip()[:200]))

    def advance_branch(self, commit):
        """Fast-forward the writer lane onto a snapshot commit that
        already names the current tip as its parent - decrees stack
        as clean increments, never as replayed patches."""
        proc = subprocess.run(
            ["git", "-C", self.worktree, "merge", "--ff-only",
             commit],
            capture_output=True, text=True, timeout=C.GIT_TIMEOUT_S)
        if proc.returncode == 0:
            return _git(self.worktree, "rev-parse", "HEAD^{tree}")
        raise RuntimeError("lane refused fast-forward: %s"
                           % proc.stderr.strip()[:200])

    def push_branch(self):
        _git(self.worktree, "push", "-u", "origin", C.BRANCH,
             timeout=C.GIT_TIMEOUT_S)

    # ---------------- PR layer ----------------

    def _gh(self, *args):
        proc = subprocess.run([self.gh] + list(args),
                              capture_output=True, text=True,
                              timeout=C.GIT_TIMEOUT_S)
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
            existing = self._gh("pr", "list", "--head", C.BRANCH,
                                "--state", "open", "--json", "number",
                                "-q", ".[0].number")
        except RuntimeError:
            pass
        pr = existing or self._gh(
            "pr", "create", "--base", "main", "--head", C.BRANCH,
            "--title", subject,
            "--body", "HEBE automated decree per FLOW.md protocol.")
        if self.mode == "review":
            return str(pr)
        self._gh("pr", "merge", str(pr), "--squash", "--delete-branch")
        return str(pr)

    # ---------------- settling the mirror ----------------

    def _unlink_quiet(self, rel):
        try:
            os.unlink(os.path.join(self.root, rel))
        except OSError:
            pass

    def settle_mirror(self, drift):
        """Root gives up its copy only after origin holds the content."""
        for batch in _chunks(drift["tracked"], C.RESTORE_BATCH):
            _git(self.root, "checkout", "--", *batch)
        for p in drift["untracked"]:
            self._unlink_quiet(p)
        _git(self.root, "pull", "--ff-only", "origin", "main",
             timeout=C.GIT_TIMEOUT_S)

    def _sync_mirror_soft(self, report):
        try:
            out = _git(self.root, "pull", "--ff-only", "origin", "main",
                       timeout=C.GIT_TIMEOUT_S, check=False)
            report["pull"] = (out.splitlines() or [""])[0][:120]
        except Exception as exc:              # noqa: BLE001 - soft
            report["pull"] = "refused: %s" % str(exc)[:120]

    # ---------------- cycle ----------------

    def once(self, dry_run=False):
        """One decree cycle. Returns a report dict (also ledgers on
        real runs)."""
        t0 = time.time()
        st = self._load_state()
        report = {"mode": self.mode, "verdict": "idle", "seq": st["seq"],
                  "pending_letters": len(self.pending_letters()),
                  "license_present": os.path.exists(
                      os.path.join(self.root, "LICENSE"))}

        if self.quarantined(st):
            report["verdict"] = "quarantined"
            report["reason"] = st.get("reason", "")
            self._say("decree-idle", report)
            return report

        if dry_run:
            report["verdict"] = "dry-run"
            report["plan"] = {
                "letters": self.pending_letters(),
                "will_seed_license": not report["license_present"]}
            return report

        self.pending = []
        self.ensure_oath()
        self.seed_license()
        self.register_protected_assets()
        filed = self.drain_inbox()
        report["filed"] = filed

        st = self._load_state()   # refresh: dictations moved the state
        paths = self.owed_paths()
        report["paths"] = paths
        if not paths:
            report["verdict"] = "still-water"
            self._sync_mirror_soft(report)
            self._say("decree-idle", report)
            return report

        drift = self.scoped_drift(paths)
        n = len(drift["tracked"]) + len(drift["untracked"])
        if n == 0:
            # everything dictated lives in gitignored territory: the
            # debt is consumed, nothing can ever ship for these rows
            report["verdict"] = "unrecorded"
            report["reason"] = ("dictated paths are gitignored; "
                                "nothing to ship")
            st["last_shipped_row"] = int(st.get("row", 0))
            self._save_state(st)
            self._ledger(dict(report))
            self._say("decree-idle", report)
            return report

        seq_next = st["seq"] + 1
        subject = ("hebe: decree %d records %d document%s"
                   % (seq_next, n, "" if n == 1 else "s"))
        areas = ", ".join(sorted({p.split("/")[0] for p in paths}))[:40]
        if areas:
            subject += " (%s)" % areas
        subject = subject[:C.SUBJECT_MAX]

        lock = LaneLock(C.LANE, stale_s=C.LOCK_STALE_S,
                        note="hebe decree", root=self._lock_root)
        if not lock.acquire(timeout=C.LOCK_WAIT_S):
            report["verdict"] = "lane-busy"
            report["holder"] = lane_status(C.LANE, root=self._lock_root)
            self._ledger(dict(report))
            self._say("decree-failed", report)
            return report
        try:
            self.ensure_worktree()
            self.sync_branch()
            snap = self.snapshot_scoped(paths, subject)
            if snap is None:
                # nothing new versus the lane tip: if that tip is
                # itself unmerged we are WAITING, not idle - and a
                # waiting scribe neither consumes her debt nor counts
                # a failure (the breaker is for real faults).
                ahead = _git(self.worktree, "rev-list", "--count",
                             "origin/main..HEAD", check=False)
                if ahead and int(ahead or 0) > 0:
                    report["verdict"] = "awaiting-merge"
                    self._ledger(dict(report))
                    self._say("decree-idle", report)
                    return report
                report["verdict"] = "still-water"
                st["last_shipped_row"] = int(st.get("row", 0))
                self._save_state(st)
                self._sync_mirror_soft(report)
                return report
            self.advance_branch(snap[1])
            self.push_branch()
            pr = self.ship_pr(subject)
            st["seq"] = seq_next
            st["last_shipped_row"] = int(st.get("row", 0))
            report.update({"verdict": "shipped", "seq": seq_next,
                           "commit": snap[1][:12], "subject": subject,
                           "pr": pr, "merged": self.mode == "squash"})
            if self.mode == "squash":
                self.settle_mirror(drift)
                report["settled"] = True
            st["failures"] = 0
            st["reason"] = ""
            self._save_state(st)
            self._ledger(dict(report))
            self._say("decree", report)
            return report
        except Exception as exc:              # noqa: BLE001 - gate
            report["verdict"] = "failed"
            report["error"] = ("%s: %s" % (type(exc).__name__,
                                           exc))[:300]
            st["failures"] = int(st.get("failures", 0)) + 1
            if st["failures"] >= C.FAIL_LIMIT:
                st["quarantine_until"] = time.time() + \
                    C.QUARANTINE_COOLDOWN_S
                st["reason"] = report["error"]
            self._save_state(st)
            self._ledger(dict(report))
            self._say("decree-failed", report)
            return report
        finally:
            lock.release()

    def watch(self, max_cycles=0):
        c = 0
        while True:
            rep = self.once()
            print("[%s] decree verdict=%s paths=%s"
                  % (time.strftime("%H:%M:%S"), rep.get("verdict"),
                     len(rep.get("paths", []))), flush=True)
            c += 1
            if max_cycles and c >= max_cycles:
                return 0
            time.sleep(max(5.0, self.interval))

    def resume(self):
        st = self._load_state()
        st["failures"] = 0
        st["quarantine_until"] = 0.0
        st["reason"] = ""
        self._save_state(st)
        return st

    def status(self):
        st = self._load_state()

        def tail(path, k=5):
            try:
                with open(path, encoding="utf-8") as fh:
                    return [json.loads(x) for x in
                            fh.read().splitlines()[-k:] if x.strip()]
            except (OSError, ValueError):
                return []

        oaths = tail(self.oaths_path, 50)
        seals = tail(self.ip_path, 200)
        return {
            "root": self.root,
            "branch": C.BRANCH,
            "worktree": self.worktree,
            "worktree_ready": os.path.exists(
                os.path.join(self.worktree, ".git")),
            "mode": self.mode,
            "interval_s": self.interval,
            "seq": st.get("seq", 0),
            "failures": st.get("failures", 0),
            "quarantined": self.quarantined(st),
            "quarantine_reason": st.get("reason", ""),
            "standing_grant": C.STANDING_GRANT,
            "oaths_recorded": len(oaths),
            "ip_seals": len(seals),
            "inbox_pending": len(self.pending_letters()),
            "owed_paths": len(self.owed_paths()),
            "license_present": os.path.exists(
                os.path.join(self.root, "LICENSE")),
            "lane": lane_status(C.LANE, root=self._lock_root),
            "recent_decrees": tail(self.ledger_path),
        }


if __name__ == "__main__":  # pragma: no cover
    print(__doc__)
    sys.exit(2)
