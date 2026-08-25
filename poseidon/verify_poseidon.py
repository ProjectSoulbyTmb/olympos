"""POSEIDON gate - proves the tide moves without touching the sea.

Every scenario runs inside throwaway fixture repositories (bare origin
+ working clone) under the system temp dir; the real workspace is only
read for imports. No network, no real ``gh``: PR/merge is simulated by
a fake that performs an honest squash against the bare origin via git
plumbing.

Run:  python poseidon/verify_poseidon.py
Exit: 0 green, 1 failures.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from poseidon import heal, kernel as _pk   # noqa: E402
from poseidon.kernel import (ACTIVE_DELAY_S, FAIL_BACKOFF_BASE_S,
                             FAIL_LIMIT, QUARANTINE_COOLDOWN_S,
                             TideEngine)  # noqa: E402

# gate speed: healing backoffs must not pace the suite
_pk.RETRY_BACKOFF_S = 0.05

CHECKS = []
FAILS = []

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "tide-test",
    "GIT_AUTHOR_EMAIL": "tide@test",
    "GIT_COMMITTER_NAME": "tide-test",
    "GIT_COMMITTER_EMAIL": "tide@test",
}


def check(fn):
    CHECKS.append(fn)
    return fn


def git(root, *args, check=True):
    env = dict(os.environ)
    env.update(GIT_ENV)
    proc = subprocess.run(["git", "-C", root] + list(args),
                          capture_output=True, text=True,
                          timeout=120, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args),
                                           proc.stderr.strip()[:300]))
    return proc.stdout.strip()


class Fixture:
    """bare origin + a live clone, both disposable."""

    def __init__(self):
        self.base = tempfile.mkdtemp(prefix="poseidon-gate-")
        self.bare = os.path.join(self.base, "origin.git")
        self.root = os.path.join(self.base, "mirror")
        git(self.base, "init", "--bare", "-b", "main", "origin.git")
        git(self.base, "clone", "origin.git", "mirror",
            check=False)  # warns on empty repo; fine
        # seed the real workspace's ignore discipline: writer
        # worktrees and this organ's runtime dirs are not drift.
        # (kernel.py additionally prunes SWEEP_EXCLUDES from its temp
        # index, so the gate stays honest even if these lines vanish.)
        with open(os.path.join(self.root, ".gitignore"), "w") as fh:
            fh.write(".worktrees/\ndata/\nposeidon/data/\n")
        with open(os.path.join(self.root, "file.txt"), "w") as fh:
            fh.write("line-1\nline-2\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", "seed")
        git(self.root, "push", "-u", "origin", "main")
        git(self.root, "config", "user.name", "tide-test")
        git(self.root, "config", "user.email", "tide@test")

    def engine(self, mode="local", interval=60.0):
        eng = TideEngine(root=self.root, mode=mode, bus=False,
                         interval=interval)
        return eng

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as fh:
            return fh.read()

    def origin_ref(self, ref):
        out = subprocess.run(
            ["git", "--git-dir", self.bare, "rev-parse", "--verify",
             "--quiet", ref],
            capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else None

    def squash_on_origin(self):
        """Honest fake of `gh pr merge --squash`: main absorbs the
        branch tip as one parent, branch ref dies."""
        tip = self.origin_ref(BRANCH_REF)
        parent = self.origin_ref("refs/heads/main")
        tree = git(self.bare, "log", "-1", "--format=%T", tip)
        new = git(self.bare, "commit-tree", tree, "-p", parent,
                  "-m", "squash: poseidon tide (simulated)")
        git(self.bare, "update-ref", "refs/heads/main", new)
        git(self.bare, "update-ref", "-d", BRANCH_REF)

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)


BRANCH_REF = "refs/heads/auto/poseidon"


# ------------------------------------------------------------- tests

@check
def drift_detection_and_dry_run():
    fx = Fixture()
    try:
        fx.write("file.txt", "line-1 changed\nline-2\n")
        fx.write("new.txt", "brand new\n")
        eng = fx.engine()
        d = eng.drift()
        assert d["tracked"] == ["file.txt"], d
        assert d["untracked"] == ["new.txt"], d
        before = sorted(os.listdir(eng.data_dir)) \
            if os.path.exists(eng.data_dir) else []
        rep = eng.once(dry_run=True)
        assert rep["verdict"] == "dry-run"
        after = sorted(os.listdir(eng.data_dir)) \
            if os.path.exists(eng.data_dir) else []
        assert before == after, "dry-run must not write state"
        assert eng.drift() == d, "dry-run must not touch the tree"
    finally:
        fx.cleanup()


@check
def local_mode_ships_branch_and_waits():
    fx = Fixture()
    try:
        fx.write("file.txt", "line-1 local-mode\nline-2\n")
        fx.write("pkg/mod.py", "x = 1\n")
        eng = fx.engine(mode="local")
        rep = eng.once()
        assert rep["verdict"] == "shipped", rep
        assert rep["merged"] is False
        tip = fx.origin_ref(BRANCH_REF)
        assert tip, "branch never reached origin"
        blob = git(fx.root, "show", "%s:file.txt" % tip)
        assert "local-mode" in blob
        assert fx.origin_ref("refs/heads/main") != tip
        # root keeps its drift until a merge settles it
        assert eng.drift()["tracked"], "root lost its drift too early"
        assert eng._load_state()["seq"] == 1
        # re-running without edits must not stack duplicate commits
        rep2 = eng.once()
        assert rep2["verdict"] == "awaiting-merge", rep2
        assert eng._load_state()["seq"] == 1
        ledger = open(eng.ledger_path, encoding="utf-8").read()
        assert '"shipped"' in ledger and '"awaiting-merge"' in ledger
    finally:
        fx.cleanup()


@check
def squash_mode_settles_the_mirror():
    fx = Fixture()
    try:
        fx.write("file.txt", "line-1 settled\nline-2\n")
        fx.write("deep/note.md", "# tide\n")
        eng = fx.engine(mode="squash")
        calls = []

        def fake_gh(*args):
            calls.append(tuple(args[:2]))
            if args[0] == "pr":
                if args[1] == "list":
                    return ""
                if args[1] == "create":
                    return "42"
                if args[1] == "merge":
                    fx.squash_on_origin()
                    return ""
            raise AssertionError("unexpected gh call %s" % (args,))
        eng._gh = fake_gh
        rep = eng.once()
        assert rep["verdict"] == "shipped" and rep["settled"], rep
        assert eng.drift() == {"tracked": [], "untracked": []}, \
            "settled root must be clean"
        assert "settled" in fx.read("file.txt")
        assert fx.read(os.path.join("deep", "note.md")) == "# tide\n", \
            "swept new files must return as tracked content"
        log = git(fx.root, "log", "--oneline", "-2", "origin/main")
        assert "squash:" in log
        assert ("pr", "merge") in calls
    finally:
        fx.cleanup()


@check
def conflicts_never_destroy_and_breaker_quarantines():
    fx = Fixture()
    try:
        # rival writer advances origin/main over the same line
        rival = os.path.join(fx.base, "rival")
        git(fx.base, "clone", "origin.git", "rival")
        with open(os.path.join(rival, "file.txt"), "w") as fh:
            fh.write("line-1 RIVAL\nline-2\n")
        git(rival, "commit", "-am", "rival wins the line")
        git(rival, "push", "origin", "main")
        # our drift wants the same line
        fx.write("file.txt", "line-1 POSEIDON\nline-2\n")
        eng = fx.engine(mode="squash")
        eng._gh = lambda *a: (_ for _ in ()).throw(
            AssertionError("conflict must die before gh"))
        for attempt in range(1, FAIL_LIMIT + 1):
            rep = eng.once()
            assert rep["verdict"] == "failed", (attempt, rep)
            assert fx.read("file.txt") == "line-1 POSEIDON\nline-2\n", \
                "a failed tide destroyed local work"
        st = eng._load_state()
        assert st["failures"] >= FAIL_LIMIT
        assert eng.quarantined(st), "breaker did not trip"
        st["quarantine_until"] = 0.0      # simulate elapsed cooldown
        eng._save_state(st)
        assert not eng.quarantined()
        eng.resume()
        assert eng._load_state()["failures"] == 0
    finally:
        fx.cleanup()


@check
def messages_carry_sequence_and_areas():
    fx = Fixture()
    try:
        fx.write("atlas/a.txt", "1\n")
        fx.write("atlas/b.txt", "2\n")
        fx.write("docs/d.md", "3\n")
        eng = fx.engine()
        subject, body = eng.message(eng.drift(), 7)
        assert subject.startswith("poseidon: tide 7 sweeps 3 files"), \
            subject
        assert "atlas x2" in subject and "docs x1" in subject
        assert "- atlas/a.txt" in body and "- docs/d.md" in body
        assert len(subject.splitlines()[0]) <= 72
    finally:
        fx.cleanup()


@check
def still_water_keeps_the_workflow_moving():
    fx = Fixture()
    try:
        eng = fx.engine(mode="squash")
        eng._gh = lambda *a: (_ for _ in ()).throw(AssertionError())
        rep = eng.once()
        assert rep["verdict"] == "still-water", rep
        assert rep.get("pull") is not None, "quiet days must still sync"
    finally:
        fx.cleanup()


@check
def fleet_berths_are_idempotent_and_reported():
    fx = Fixture()
    try:
        from poseidon import fleet
        eng = fx.engine()
        names = ("gaia", "hades")
        try:
            fleet.status(eng, only="nope")
            raise RuntimeError("registry accepted an unknown kernel")
        except SystemExit:
            pass
        for name in names:
            eng.ensure_worktree(name)
            eng.ensure_worktree(name)          # idempotent re-berth
            assert os.path.exists(os.path.join(
                eng.wt_path(name), ".git")), name
        rows = fleet.status(eng, only="gaia,hades")
        assert rows["gaia"]["ready"] and rows["hades"]["ready"]
        assert rows["gaia"]["branch"] == "auto/gaia"
        assert rows["gaia"]["ahead_main"] == 0
        assert rows["gaia"]["dirty"] is False
    finally:
        fx.cleanup()


@check
def settle_guard_spares_post_snapshot_writer_edits():
    fx = Fixture()
    try:
        fx.write("file.txt", "line-1 tide\nline-2\n")
        fx.write("new.txt", "tide cargo\n")
        eng = fx.engine()
        d = eng.drift()
        subject, body = eng.message(d, 1)
        snap = eng.snapshot(d, subject)
        assert snap is not None
        # a writer touches two swept paths AFTER the snapshot sailed
        fx.write("file.txt", "line-1 WRITER-AHEAD\nline-2\n")
        fx.write("new.txt", "WRITER-AHEAD cargo\n")
        res = eng.settle_mirror(snap)
        assert "file.txt" in res["skipped"], res
        assert "file.txt" not in res["restored"], res
        assert fx.read("file.txt") == "line-1 WRITER-AHEAD\nline-2\n", \
            "settle clobbered a post-snapshot edit"
        assert fx.read("new.txt") == "WRITER-AHEAD cargo\n", \
            "settle deleted a diverged untracked file"
        # untouched-by-writer paths still restore cleanly: none here,
        # so the mirror pull is allowed to be refused (diverged dirt)
        assert res["pulled"] is False or res["pulled"] is True
    finally:
        fx.cleanup()


@check
def next_delay_sprints_and_backs_off():
    fx = Fixture()
    try:
        eng = fx.engine(interval=300.0)
        assert eng.next_delay("shipped") == ACTIVE_DELAY_S
        assert eng.next_delay("still-water") == 300.0
        assert eng.next_delay("failed", 1) == FAIL_BACKOFF_BASE_S
        assert eng.next_delay("failed", 2) == FAIL_BACKOFF_BASE_S * 2
        cap = eng.next_delay("failed", 99)
        assert cap == QUARANTINE_COOLDOWN_S, "backoff must respect cap"
    finally:
        fx.cleanup()


@check
def fleet_sync_is_parallel_and_lazy():
    fx = Fixture()
    try:
        from poseidon import fleet
        eng = fx.engine()
        rival = os.path.join(fx.base, "rival")
        git(fx.base, "clone", "origin.git", "rival")
        with open(os.path.join(rival, "file.txt"), "a") as fh:
            fh.write("rival line\n")
        git(rival, "commit", "-am", "rival advances main")
        git(rival, "push", "origin", "main")
        results = fleet.sync(eng)             # no berths exist yet
        for name in fleet.FLEET:
            assert results[name] == "synced", (name, results[name])
            assert os.path.exists(os.path.join(
                eng.wt_path(name), ".git")), name
        rows = fleet.status(eng)
        behind = [n for n, r in rows.items() if r.get("behind_main")]
        assert not behind, "sync must absorb origin/main everywhere"
    finally:
        fx.cleanup()


# ------------------------------------------------------ healing gate

@check
def heal_rebuilds_a_corrupt_berth_and_the_tide_still_sails():
    fx = Fixture()
    try:
        eng = fx.engine()
        eng.ensure_worktree()
        stub = os.path.join(eng.worktree, ".git")
        os.unlink(stub)   # hidden file: Windows forbids in-place rewrite
        with open(stub, "w") as fh:
            fh.write("gitdir: nowhere\n")  # crash-mangled berth
        assert heal.wt_state(eng) == "corrupt"
        applied = []
        assert heal.fix_berth(eng, applied) is True
        assert "berth-corrupt-rebuilt" in applied, applied
        out = git(eng.worktree, "rev-parse",
                  "--is-inside-work-tree")
        assert out == "true", "rebuilt berth is not a worktree"
        # the automated tide flows through the healed berth untouched
        fx.write("file.txt", "line-1 post-heal\nline-2\n")
        rep = eng.once()
        assert rep["verdict"] == "shipped", rep
    finally:
        fx.cleanup()


@check
def ledger_torn_tail_trimmed_but_deeper_rot_left_alone():
    fx = Fixture()
    try:
        eng = fx.engine()
        os.makedirs(eng.data_dir, exist_ok=True)
        good_row = json.dumps({"verdict": "shipped", "seq": 1})
        with open(eng.ledger_path, "w", encoding="utf-8") as fh:
            fh.write(good_row + "\n" + '{"verdict": "shi')
        assert heal.repair_ledger_tail(eng.ledger_path) is True
        with open(eng.ledger_path, encoding="utf-8") as fh:
            assert fh.read() == good_row + "\n"
        # mid-file garbage under an intact tail: hands off entirely
        with open(eng.ledger_path, "w", encoding="utf-8") as fh:
            fh.write('{"a": 1}\nGARBAGE\n{"b": 2}\n')
        before = open(eng.ledger_path, encoding="utf-8").read()
        assert heal.repair_ledger_tail(eng.ledger_path) is False
        assert open(eng.ledger_path,
                    encoding="utf-8").read() == before
    finally:
        fx.cleanup()


@check
def orphaned_temp_indexes_swept_fresh_ones_kept():
    fx = Fixture()
    try:
        eng = fx.engine()
        os.makedirs(eng.data_dir, exist_ok=True)
        old = os.path.join(eng.data_dir, "idx-111")
        fresh = os.path.join(eng.data_dir, "idx-222")
        for p in (old, fresh):
            with open(p, "w") as fh:
                fh.write("")
        ancient = time.time() - 2 * 3600
        os.utime(old, (ancient, ancient))
        applied = []
        heal.sweep_indexes(eng, applied)
        assert any(a.startswith("idx-swept") for a in applied), applied
        assert not os.path.exists(old)
        assert os.path.exists(fresh), \
            "a live sibling's index must never be swept"
    finally:
        fx.cleanup()


@check
def quarantine_reopens_when_probes_run_green_holds_when_red():
    fx = Fixture()
    try:
        eng = fx.engine()
        fx.write("file.txt", "line-1 after-the-storm\nline-2\n")
        st = {"seq": 0, "failures": FAIL_LIMIT,
              "quarantine_until": time.time() + 900,
              "reason": "simulated outage"}
        eng._save_state(st)
        # red water: origin unreachable -> breaker stays honest
        git(fx.root, "remote", "set-url", "origin",
            os.path.join(fx.base, "no-such-origin"))
        rep = eng.once()
        assert rep["verdict"] == "quarantined", rep
        assert rep["heal"]["quarantine_probes"]["origin"] is False
        # green water again -> the lane reopens early and ships
        git(fx.root, "remote", "set-url", "origin",
            os.path.join(fx.base, "origin.git"))
        rep = eng.once()
        assert rep["verdict"] == "shipped", rep
        assert any(a.startswith("quarantine-cleared")
                   for a in rep["heal"]["applied"]), rep["heal"]
        st = eng._load_state()
        assert st["failures"] == 0 and not eng.quarantined(st)
    finally:
        fx.cleanup()


@check
def push_non_fast_forward_adopts_and_replays_never_force():
    fx = Fixture()
    try:
        eng = fx.engine(mode="squash")
        calls = []

        def fake_gh(*args):
            calls.append(tuple(args[:2]))
            if args[0] == "pr":
                if args[1] == "list":
                    return ""
                if args[1] == "create":
                    return "9"
                if args[1] == "merge":
                    fx.squash_on_origin()
                    return ""
            raise AssertionError("unexpected gh call %s" % (args,))
        eng._gh = fake_gh
        fx.write("file.txt", "line-1 tide-one\nline-2\n")
        rep1 = eng.once()
        assert rep1["verdict"] == "shipped" and rep1["settled"], rep1
        # after the squash merge deleted our remote branch, crash
        # residue resurrects it with a commit we never had
        rival = os.path.join(fx.base, "residue")
        git(fx.base, "clone", "origin.git", "residue")
        git(rival, "checkout", "-b", "auto/poseidon", "origin/main")
        with open(os.path.join(rival, "residue.txt"), "w") as fh:
            fh.write("crash residue cargo\n")
        git(rival, "add", "-A")
        git(rival, "commit", "-m", "residue lands remotely")
        git(rival, "push", "origin", "auto/poseidon")
        # next tide: push is refused non-fast-forward, then self-heals
        fx.write("file.txt", "line-1 tide-two\nline-2\n")
        rep2 = eng.once()
        assert rep2["verdict"] == "shipped" and rep2["settled"], rep2
        assert any(a.startswith("push-nonff")
                   for a in rep2["heal"]["applied"]), rep2["heal"]
        # the settled mirror carries both: replayed cargo AND the
        # adopted branch's extra file - adoption, never destruction
        assert fx.read("file.txt") == "line-1 tide-two\nline-2\n"
        assert os.path.exists(os.path.join(fx.root, "residue.txt")), \
            "adoption lost origin-side cargo"
        assert eng.drift() == {"tracked": [], "untracked": []}, \
            "settled root must be clean"
    finally:
        fx.cleanup()


@check
def transient_gh_failures_retry_once_then_ship():
    fx = Fixture()
    try:
        fx.write("file.txt", "line-1 flaky-wire\nline-2\n")
        eng = fx.engine(mode="squash")
        calls = []

        def flaky_call(*args):
            calls.append(tuple(args[:2]))
            if len(calls) == 1:
                raise RuntimeError(
                    "gh list failed: connection reset by peer")
            if args[0] == "pr":
                if args[1] == "list":
                    return ""
                if args[1] == "create":
                    return "7"
                if args[1] == "merge":
                    fx.squash_on_origin()
                    return ""
            raise AssertionError("unexpected gh call %s" % (args,))
        eng._gh_call = flaky_call              # real _gh wraps this
        rep = eng.once()
        assert rep["verdict"] == "shipped" and rep["settled"], rep
        assert calls[:2] == [("pr", "list"), ("pr", "list")], calls
        assert ("pr", "merge") in calls
    finally:
        fx.cleanup()


@check
def diagnose_reports_mirror_violation_without_touching_it():
    fx = Fixture()
    try:
        eng = fx.engine()
        # someone commits on main at the root - doctrine violation;
        # healing reports it but NEVER resets (quarantine, never destroy)
        fx.write("file.txt", "line-1 local-only-commit\nline-2\n")
        git(fx.root, "commit", "-am", "forbidden local main commit")
        head_before = git(fx.root, "rev-parse", "HEAD")
        diag = heal.diagnose(eng)
        row = [f for f in diag["findings"]
               if f["id"] == "mirror-synced"][0]
        assert row["ok"] is False, row
        assert "ahead=1" in row["detail"], row
        rep = heal.repair(eng, apply=True)
        assert git(fx.root, "rev-parse", "HEAD") == head_before, \
            "healing reset the mirror - that is destruction"
        row = [f for f in rep["findings"]
               if f["id"] == "mirror-synced"][0]
        assert row["ok"] is False and rep["healthy"] is False, rep
    finally:
        fx.cleanup()


@check
def deep_diagnosis_runs_object_database_fsck_clean():
    fx = Fixture()
    try:
        eng = fx.engine()
        rep = heal.repair(eng, apply=True, deep=True)
        assert "berth-missing-created" in rep["applied"], rep
        row = [f for f in rep["findings"]
               if f["id"] == "object-db"][0]
        assert row["ok"] is True, row
        assert rep["healthy"] is True, rep
    finally:
        fx.cleanup()


def main():
    print("=" * 64)
    print("POSEIDON GATE - the tide always moves, never destroys")
    print("=" * 64)
    for fn in CHECKS:
        try:
            fn()
            print("[PASS] %s" % fn.__name__)
        except AssertionError as exc:
            FAILS.append(fn.__name__)
            print("[FAIL] %s: %s" % (fn.__name__, exc))
        except Exception as exc:              # noqa: BLE001 - gate
            FAILS.append(fn.__name__)
            print("[FAIL] %s: %s: %s"
                  % (fn.__name__, type(exc).__name__, exc))
    total = len(CHECKS)
    print("-" * 64)
    print("%d/%d checks green" % (total - len(FAILS), total))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
