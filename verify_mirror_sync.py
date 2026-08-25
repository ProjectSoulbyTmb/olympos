#!/usr/bin/env python3
"""verify_mirror_sync - gate for the execution-mirror convergence tool.

Boots throwaway git repos + mirrors (env-isolated via MIRROR_HOME) and
asserts every mode does exactly what it claims:

  hook      committed paths land in the mirror; deletions stay
            report-only; absent mirror is a clean no-op
  sync      drift is repaired byte-for-byte; WIP (dirty worktree) files
            are never touched; missing mirror skips green
  audit     --strict exits 1 on drift, 0 when converged

Exits non-zero on any failure. Stdlib only.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "mirror_sync.py")
RESULTS = []


def check(name):
    def wrap(fn):
        def run():
            try:
                ok, detail = fn()
            except Exception as exc:            # noqa: BLE001 - evidence
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            RESULTS.append((name, bool(ok)))
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
                  + (f" - {detail}" if detail and not ok else ""))
        return run
    return wrap


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                       text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr.strip()}")
    return r.stdout


def run_tool(repo, mirror, *mode_args):
    env = dict(os.environ, MIRROR_HOME=mirror)
    return subprocess.run(
        [sys.executable, "-u", TOOL, *mode_args],
        capture_output=True, text=True, timeout=120, cwd=repo, env=env)


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def make_repo():
    repo = tempfile.mkdtemp(prefix="msync-repo-")
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "gate@olympos.local")
    git(repo, "config", "user.name", "gate")
    with open(os.path.join(repo, "a.txt"), "wb") as fh:
        fh.write(b"v1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "seed")
    return repo


@check("hook syncs committed paths to mirror")
def t_hook_syncs_commit():
    repo = make_repo()
    mirror = tempfile.mkdtemp(prefix="msync-mir-")
    problems = []
    try:
        r = run_tool(repo, mirror, "--hook")
        if r.returncode != 0:
            problems.append(f"seed hook rc={r.returncode} {r.stderr}")
        elif read(os.path.join(mirror, "a.txt")) != b"v1\n":
            problems.append("seed path a.txt not synced")

        with open(os.path.join(repo, "b.txt"), "wb") as fh:
            fh.write(b"hello\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "add b")
        r = run_tool(repo, mirror, "--hook")
        if r.returncode != 0:
            problems.append(f"hook rc={r.returncode} {r.stderr}")
        elif read(os.path.join(mirror, "b.txt")) != b"hello\n":
            problems.append(f"b.txt missing; mirror={os.listdir(mirror)}")
    except Exception as exc:                    # noqa: BLE001
        problems.append(repr(exc))
    return not problems, "; ".join(problems)


@check("hook deletion is report-only")
def t_hook_deletion_report_only():
    repo = make_repo()
    mirror = tempfile.mkdtemp(prefix="msync-mir-")
    run_tool(repo, mirror, "--hook")               # seed mirror state
    os.remove(os.path.join(repo, "a.txt"))
    git(repo, "commit", "-aqm", "drop a")
    r = run_tool(repo, mirror, "--hook")
    if r.returncode != 0:
        return False, f"rc={r.returncode}"
    if not os.path.isfile(os.path.join(mirror, "a.txt")):
        return False, "deletion auto-propagated (must stay report-only)"
    return True, ""


@check("sync repairs drift; WIP stays untouched")
def t_sync_fixes_drift_skips_wip():
    repo = make_repo()
    mirror = tempfile.mkdtemp(prefix="msync-mir-")
    problems = []
    try:
        run_tool(repo, mirror, "--hook")           # converge first
        with open(os.path.join(repo, "a.txt"), "wb") as fh:
            fh.write(b"v2\n")
        git(repo, "commit", "-aqm", "v2")
        r = run_tool(repo, mirror, "--audit", "--strict")
        if r.returncode != 1:
            problems.append(f"strict audit rc={r.returncode}")

        with open(os.path.join(repo, "b.txt"), "wb") as fh:
            fh.write(b"wip\n")                      # untracked WIP
        r = run_tool(repo, mirror, "--sync")
        if r.returncode != 0:
            problems.append(f"sync rc={r.returncode} {r.stderr}")
        elif read(os.path.join(mirror, "a.txt")) != b"v2\n":
            problems.append(
                f"a.txt={read(os.path.join(mirror, 'a.txt'))!r}")
        elif os.path.exists(os.path.join(mirror, "b.txt")):
            problems.append("WIP b.txt was copied")

        r = run_tool(repo, mirror, "--audit", "--strict")
        if r.returncode != 0:
            problems.append("converged audit still red")
    except Exception as exc:                    # noqa: BLE001
        problems.append(repr(exc))
    return not problems, "; ".join(problems)


@check("absent mirror skips green in every mode")
def t_absent_mirror_skip():
    repo = make_repo()
    ghost = os.path.join(tempfile.mkdtemp(prefix="msync-none-"), "nope")
    for args in (("--audit",), ("--sync",), ("--hook",)):
        r = run_tool(repo, ghost, *args)
        assert r.returncode == 0, f"{args} rc={r.returncode}"
        assert "SKIP" in r.stdout or "absent" in r.stdout, r.stdout
    return True, ""


def main() -> int:
    print("verify_mirror_sync")
    print("-" * 60)
    t_hook_syncs_commit()
    t_hook_deletion_report_only()
    t_sync_fixes_drift_skips_wip()
    t_absent_mirror_skip()
    print("-" * 60)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("MIRROR SYNC OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
