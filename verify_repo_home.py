r"""REPO HOME verify - proves the D:\-only policy machinery works.

Pure-logic suite against the guard module: no live machine state, no
D: drive needed (allowed roots are injected), no network. The audit
CLI stays out of CI on purpose - it reads real disk state and would
pin gates red until legacy checkouts are retired.

    python verify_repo_home.py     (exit 0 = all green)
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "safeguards", "repo_home_guard.py")
PY = sys.executable

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def run_guard(*args, extra_root=None):
    import os as _os
    env = dict(_os.environ)
    if extra_root:
        env["REPO_HOME_EXTRA"] = extra_root
    else:
        env.pop("REPO_HOME_EXTRA", None)
    return subprocess.run([PY, GUARD, *args], capture_output=True,
                          text=True, timeout=60, env=env)


# injected roots: Q:\ stands in for the operator's drive so this gate
# never depends on what disks the runner happens to have
ROOTS = ["q:\\"]


@check
def allowed_root_accepts_own_tree():
    g = __import__("safeguards.repo_home_guard",
                   fromlist=["is_allowed"])
    # whole-drive policy: everything on the drive passes
    assert g.is_allowed(r"Q:\repos\thing", ROOTS)
    assert g.is_allowed("Q:\\", ROOTS)                    # root itself
    assert g.is_allowed(r"q:\REPOS\Thing", ROOTS)         # case-insens
    # sub-root policy: prefix boundaries hold ("Q:\repos" must not
    # admit sibling "Q:\reposx")
    sub = ["q:\\repos"]
    assert g.is_allowed(r"Q:\repos\thing", sub)
    assert not g.is_allowed(r"Q:\reposx\thing", sub)


@check
def other_drives_and_unc_denied():
    g = __import__("safeguards.repo_home_guard",
                   fromlist=["is_allowed"])
    for p in (r"C:\Users\x\repo", r"E:\repo", r"D:\but-roots-are-q",
              r"\\server\share\repo"):
        assert not g.is_allowed(p, ROOTS), p


@check
def relative_paths_resolve_before_judging():
    g = __import__("safeguards.repo_home_guard",
                   fromlist=["is_allowed", "normalize"])
    # a relative path is judged by where it lands, not its spelling:
    # cwd is on C: here, so "somewhere/repo" must be denied even
    # though the literal string mentions no drive at all
    assert not g.is_allowed(os.path.join("somewhere", "repo"), ROOTS)
    assert g.normalize("somewhere").startswith(
        g.normalize(os.getcwd())[:3])


@check
def clone_destinations_parsed():
    g = __import__("safeguards.repo_home_guard",
                   fromlist=["destinations"])
    # explicit dest judged; source URL never a candidate
    d = g.destinations(["clone", "https://github.com/a/b.git",
                        r"C:\tmp\b"])
    assert d == [r"C:\tmp\b"], d
    # single-arg clone derives name under cwd
    d = g.destinations(["clone", "https://github.com/a/b.git"])
    assert len(d) == 1 and d[0].endswith("b"), d
    # -C shifts the base for derived names
    d = g.destinations(["-C", r"Q:\repos", "clone", "x/y"])
    assert d == [os.path.join(r"Q:\repos", "y")], d
    # worktree add / init / submodule add shapes
    assert g.destinations(["worktree", "add", r"C:\wt", "main"]) \
        == [r"C:\wt"]
    assert g.destinations(["init", r"E:\fresh"]) == [r"E:\fresh"]
    assert g.destinations(["submodule", "add", "//host/r.git",
                           r"C:\sub\r"]) == [r"C:\sub\r"]
    # ordinary verbs mint nothing
    assert g.destinations(["status"]) == []
    assert g.destinations(["commit", "-m", "msg"]) == []


@check
def judge_refuses_only_bad_destination():
    g = __import__("safeguards.repo_home_guard", fromlist=["judge"])
    ok, viol = g.judge(["clone", r"Q:\seed.git", r"Q:\newhome"],
                       ROOTS)
    assert ok and not viol
    ok, viol = g.judge(["clone", r"C:\anywhere\seed.git",
                        r"C:\nope\seed"], ROOTS)
    assert not ok and viol == [r"C:\nope\seed"]
    # cloning FROM C: INTO Q: stays legal - source never judged
    ok, viol = g.judge(["clone", r"C:\anywhere\seed.git",
                        r"Q:\fine\seed"], ROOTS)
    assert ok and not viol


@check
def cli_check_exit_codes():
    r = run_guard("check", r"Q:\good", extra_root="Q:\\")
    assert r.returncode == 0 and "ALLOWED" in r.stdout, r.stdout
    r = run_guard("check", r"C:\Users\x\bad")
    assert r.returncode != 0 and "DENIED" in r.stdout \
        and "repo home" in r.stdout, r.stdout
    r = run_guard("policy")
    assert r.returncode == 0 \
        and "d:\\" in r.stdout.lower(), r.stdout


@check
def cli_audit_scans_fixture_roots():
    outer = tempfile.mkdtemp(prefix="repo-home-audit-")
    try:
        inside = os.path.join(outer, "home", "proj")
        outside = os.path.join(outer, "elsewhere", "stray")
        for d in (inside, outside):
            os.makedirs(os.path.join(d, ".git"))
        import json
        roots = os.path.join(outer, "home") + "," + outside
        # inject the fixture 'home' as an allowed extra so the only
        # violation left is the stray repo outside it
        r = run_guard("audit", "--roots", roots, "--json",
                      extra_root=os.path.join(outer, "home"))
        assert r.returncode != 0, "violation must fail the audit"
        data = json.loads(r.stdout)
        repos = {x["repo"].lower() for x in data["repos"]}
        assert inside.lower() in repos and outside.lower() in repos
        assert data["violations"] == 1
    finally:
        shutil.rmtree(outer, ignore_errors=True)


@check
def profile_shim_exists_and_declares_policy():
    shim = os.path.join(HERE, "safeguards", "repo_home_profile.ps1")
    text = open(shim, encoding="utf-8").read()
    assert "function global:git" in text, "shim must intercept git"
    for verb in ("'clone'", "'init'", "'worktree'", "'submodule'"):
        assert verb in text, f"shim must cover {verb}"
    assert "d:\\" in text.lower(), "policy root must be declared"


def main():
    print("=" * 64)
    print("REPO HOME VERIFY - one localside home: D:\\")
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
