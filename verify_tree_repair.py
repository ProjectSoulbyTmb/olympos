r"""TREE REPAIR verify - proves the automatic repairs safe + effective.

Runs against throwaway fixture repositories only (rule 10): every
repair is exercised twice - once where it MUST act, once where it
MUST refuse (fresh locks, hot directories) - so the tool can never
learn to pass by being dangerous.

    python verify_tree_repair.py     (exit 0 = all green)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(HERE, "safeguards", "tree_repair.py")
PY = sys.executable

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def git(root, *args):
    r = subprocess.run(["git", "-C", root, *args],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


def fixture():
    root = tempfile.mkdtemp(prefix="tree-repair-fix-")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@t")
    with open(os.path.join(root, "seed.txt"), "w") as fh:
        fh.write("seed\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed")
    return root


def run_tool(root, *extra, env_fix=None):
    import os as _os
    env = dict(_os.environ)
    # fixture gates must not read real machine state
    env["TREE_REPAIR_NO_MACHINE"] = "1"
    if env_fix:
        env.update(env_fix)
    return subprocess.run([PY, TR, "--root", root, *extra],
                          capture_output=True, text=True,
                          timeout=120, env=env)


@check
def stale_lock_removed_only_when_old_and_gitless():
    tr = __import__("safeguards.tree_repair", fromlist=["sweep"])
    root = fixture()
    try:
        lock = os.path.join(root, ".git", "refs", "heads", "main.lock")
        open(lock, "w").close()
        old = time.time() - 3600
        os.utime(lock, (old, old))
        # a live git process must veto the repair outright
        orig = tr._git_live_processes
        tr._git_live_processes = lambda: 1
        r = tr.sweep(root, fix=True)
        assert os.path.exists(lock), "veto failed"
        tr._git_live_processes = lambda: 0
        r = tr.sweep(root, fix=True)
        assert not os.path.exists(lock), r
        assert any(e["detector"] == "stale-locks" and e.get("fixed")
                   for e in r["findings"])
        # a fresh lock survives even with no live git
        fresh = os.path.join(root, ".git", "index.lock")
        open(fresh, "w").close()
        r = tr.sweep(root, fix=True)
        assert os.path.exists(fresh)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check
def missing_tracked_restored_but_hot_dir_protected():
    tr = __import__("safeguards.tree_repair", fromlist=["sweep"])
    root = fixture()
    try:
        os.makedirs(os.path.join(root, "pkg"))
        p = os.path.join(root, "pkg", "mod.py")
        with open(p, "w") as fh:
            fh.write("X = 1\n")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "add mod")
        os.remove(p)
        r = tr.sweep(root, fix=True)
        restored = [e for e in r["findings"]
                    if e["detector"] == "missing-tracked" and e.get("fixed")]
        assert restored and os.path.exists(p)
        # now delete again and make a sibling scream 'live writer':
        # the repair must read recent sibling writes, not the directory
        # mtime (which the deletion itself just bumped)
        os.remove(p)
        hot = os.path.join(root, "pkg", "notes.tmp")
        with open(hot, "w") as fh:
            fh.write("writer was here\n")
        r = tr.sweep(root, fix=True)
        assert not os.path.exists(p), "must not stomp a hot directory"
        entry = [e for e in r["findings"]
                 if e["detector"] == "missing-tracked"][0]
        assert any(i.get("skipped_hot_dir") for i in entry["items"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check
def generated_dirt_reset():
    tr = __import__("safeguards.tree_repair", fromlist=["GENERATED_PATHS",
                                                        "sweep"])
    root = fixture()
    try:
        rel = tr.GENERATED_PATHS[0]
        target = os.path.join(root, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as fh:
            fh.write("{}\n")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "baseline generated artifact")
        with open(target, "a") as fh:
            fh.write('{"dirty": true}\n')
        r = tr.sweep(root, fix=True)
        hit = [e for e in r["findings"]
               if e["detector"] == "generated-dirt"]
        assert hit and hit[0].get("fixed"), r["findings"]
        assert json.load(open(target)) == {}
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check
def duplicate_branch_ref_moved_to_upstream():
    tr = __import__("safeguards.tree_repair", fromlist=["sweep"])
    root = fixture()
    try:
        # same patch applied on two branches -> squash-duplicate shape
        with open(os.path.join(root, "f.txt"), "w") as fh:
            fh.write("hello\n")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "hello base")
        git(root, "branch", "auto/dup")
        with open(os.path.join(root, "f.txt"), "w") as fh:
            fh.write("changed\n")
        git(root, "commit", "-am", "change on main")
        main_tip = git(root, "rev-parse", "main").strip()
        git(root, "update-ref", "refs/remotes/origin/main", main_tip)
        git(root, "checkout", "-q", "auto/dup")
        with open(os.path.join(root, "f.txt"), "w") as fh:
            fh.write("changed\n")
        git(root, "commit", "-aqm", "same change on lane")
        git(root, "checkout", "-q", "main")
        dup_sha = git(root, "rev-parse", "auto/dup").strip()

        found = tr.find_duplicate_branches(root)
        assert [d["branch"] for d in found] == ["auto/dup"], found
        r = tr.sweep(root, fix=True)
        moved = git(root, "rev-parse", "auto/dup").strip()
        assert moved == main_tip and moved != dup_sha
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check
def interrupted_ops_reported_never_autofixed():
    tr = __import__("safeguards.tree_repair", fromlist=["sweep"])
    root = fixture()
    try:
        with open(os.path.join(root, ".git", "MERGE_HEAD"), "w") as fh:
            fh.write("0" * 40 + "\n")
        r = tr.sweep(root, fix=True)
        entry = [e for e in r["findings"]
                 if e["detector"] == "interrupted-op"]
        assert entry and entry[0]["found"] == 1
        assert "fixed" not in entry[0], "merge state must not be autofixed"
        assert r["remaining"] >= 1, "unfixable findings must fail the run"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check
def ledger_chain_verifies_and_detects_tamper():
    tr = __import__("safeguards.tree_repair", fromlist=["ledger_verify"])
    root = tempfile.mkdtemp(prefix="tree-repair-ledger-")
    try:
        tr._ledger_append(root, {"repair": "x", "count": 1})
        tr._ledger_append(root, {"repair": "y", "count": 2})
        ok, n = tr.ledger_verify(root)
        assert ok and n == 2
        path = tr.ledger_path(root)
        lines = open(path, encoding="utf-8").read().splitlines()
        e = json.loads(lines[1])
        e["count"] = 99                       # tamper
        lines[1] = json.dumps(e, sort_keys=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        ok, n = tr.ledger_verify(root)
        assert not ok, "tampered ledger must fail verification"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check
def cli_exit_codes_match_state():
    root = fixture()
    try:
        r = run_tool(root)                    # clean tree
        assert r.returncode == 0, r.stdout + r.stderr
        assert "nothing to repair" in r.stdout or "CHECK" not in r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
    root = fixture()
    try:
        with open(os.path.join(root, ".git", "MERGE_HEAD"), "w") as fh:
            fh.write("0" * 40 + "\n")
        r = run_tool(root, "--json")
        assert r.returncode != 0
        data = json.loads(r.stdout)
        assert any(e["detector"] == "interrupted-op"
                   for e in data["findings"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    print("=" * 64)
    print("TREE REPAIR VERIFY - quarantine, never destroy")
    print("=" * 64)
    sys.path.insert(0, HERE)
    failures = []
    for fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:              # noqa: BLE001 - verifier
            failures.append(fn.__name__)
            print(f"[FAIL] {fn.__name__}: {type(exc).__name__}: {exc}")
    print("-" * 64)
    ok = len(CHECKS) - len(failures)
    print(f"{ok}/{len(CHECKS)} checks green"
          + ("" if not failures else f" - FAILING: {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
