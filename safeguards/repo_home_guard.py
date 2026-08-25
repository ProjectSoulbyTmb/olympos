r"""REPO HOME GUARD - one localside home for repositories: D:\

Operator policy (2026-08-24, in force until revoked): every git
repository cloned, initialized, or created as a worktree on this
machine lives under D:\. No exceptions without an operator edit to
REPO_HOME below.

Born from a real incident: the same remote (olympos) was checked out
in TWO places (OneDrive Documents + D:\THOTH). The copies diverged,
a lane branch carried squash-duplicates of merged PRs, and two
writers shared one worktree. Split brains are not a hygiene problem;
they are a correctness problem.

Surfaces:
  - this module      canonical policy + check/audit CLI (gates, CI)
  - repo_home_profile.ps1   shell shim refusing violating clone/init/
                     worktree/submodule-add at the door (fast path;
                     this module stays the authority)

Usage:
    python safeguards/repo_home_guard.py check <path> [path...]
    python safeguards/repo_home_guard.py audit [--roots a,b,c] [--json]
    python safeguards/repo_home_guard.py policy

Exit 0 = compliant. Exit 1 = violation found / bad invocation.

audit is an operator tool on purpose and is NOT wired into doctor:
it inspects live machine state, so it would pin CI red until legacy
checkouts are retired. Run it by hand after policy changes.
"""

import json
import os
import sys

# ---------------------------------------------------------------- policy
# The single allowed localside repository home. Operator-set 2026-08-24.
# To change or revoke: edit this constant via PR (never via env var in
# production paths - env overrides are for tests only).
REPO_HOME = "D:\\"

# Test/escape hatch. Production code must not rely on it being set.
_EXTRA = os.environ.get("REPO_HOME_EXTRA", "")


def allowed_roots():
    """Normalized allowlist: REPO_HOME plus test-only extras."""
    roots = [REPO_HOME]
    roots.extend(r for r in _EXTRA.split(";") if r.strip())
    return [normalize(r) for r in roots]


def normalize(path):
    """Absolute, backslash-normalized, case-folded path string."""
    return os.path.normpath(os.path.abspath(path)).lower()


def is_allowed(path, roots=None):
    """True iff resolved path lives under an allowed root.

    Drive-letter based, case-insensitive. UNC paths (\\\\host\\share)
    are never allowed - they are not this machine's localside home.
    """
    if roots is None:
        roots = allowed_roots()
    p = normalize(path)
    if p.startswith("\\\\"):          # UNC - not localside at all
        return False
    for root in roots:
        if p == root or p.startswith(root.rstrip("\\") + "\\"):
            return True
    return False


# ------------------------------------------------- git destination parsing
_VALUE_OPTS = {"-c", "-C", "--git-dir", "--work-tree", "--namespace",
               "--super-prefix"}


def _positionals(args):
    """Split raw git argv into (cwd_hint, verb_tokens, positionals).

    cwd_hint honors leading `git -C <dir>` so `git -C C:\\tmp init`
    judges the right base. Only pre-verb global options are parsed;
    anything after the verb is treated as the subcommand's own args.
    """
    cwd_hint = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-C":
            cwd_hint = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        if a in _VALUE_OPTS:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        break                        # first non-option: the git verb
    return cwd_hint, args[i:], args[i + 1:]


def _repo_name_from_source(src):
    s = src.rstrip("/")
    name = s.replace("\\", "/").rsplit("/", 1)[-1]
    if ":" in name and "/" not in src:       # scp-like host:path
        name = name.rsplit(":", 1)[-1]
    return name[:-4] if name.lower().endswith(".git") else name


def destinations(git_args):
    """Candidate filesystem destinations a git invocation would create.

    Covers the verbs that mint a new repository/worktree on disk:
    clone, init, `worktree add`, `submodule add`. Returns [] for
    everything else (including clone SOURCE urls - cloning FROM an
    unallowed path is fine; only the destination is judged).
    """
    cwd_hint, tail, _pos = _positionals(list(git_args))
    if not tail:
        return []
    verb = tail[0].lower()
    rest = [a for a in tail[1:]]

    def positional_after(sub):
        it = iter(rest)
        for a in it:
            if a.lower() == sub:
                break
            if a.startswith("-"):
                continue
        return list(it)

    base = cwd_hint if cwd_hint else os.getcwd()

    if verb == "clone":
        pos = [a for a in rest if not a.startswith("-")]
        if len(pos) >= 2:
            return [pos[1]]
        if len(pos) == 1:
            return [os.path.join(base, _repo_name_from_source(pos[0]))]
        return []
    if verb == "init":
        pos = [a for a in rest if not a.startswith("-")]
        return [pos[0]] if pos else [base]
    if verb == "worktree":
        sub_pos = positional_after("add")
        sub_pos = [a for a in sub_pos if not a.startswith("-")]
        return sub_pos[:1]
    if verb == "submodule":
        sub_pos = [a for a in positional_after("add")
                   if not a.startswith("-")]
        if len(sub_pos) >= 2:
            return [sub_pos[1]]
        if len(sub_pos) == 1:
            return [os.path.join(base,
                                 _repo_name_from_source(sub_pos[0]))]
        return []
    return []


def judge(git_args, roots=None):
    """(ok, violations) for one git argv line."""
    viol = [d for d in destinations(git_args) if not is_allowed(d, roots)]
    return (not viol), viol


# ------------------------------------------------------------------ audit
def find_repos(root, maxdepth=3):
    """Depth-bounded scan for directories containing .git."""
    hits = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= maxdepth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if d not in ("node_modules", ".worktrees",
                                    "$RECYCLE.BIN", "System Volume "
                                    "Information")]
        if ".git" in dirnames or ".git" in filenames:
            hits.append(dirpath)
            dirnames[:] = []         # do not descend into repos
    return hits


def default_probe_roots():
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    onedrive = os.path.join(home, "OneDrive", "Documents")
    roots = [os.getcwd(), docs, onedrive, home]
    seen, out = set(), []
    for r in roots:
        if r.lower() not in seen and os.path.isdir(r):
            seen.add(r.lower())
            out.append(r)
    return out


# -------------------------------------------------------------------- cli
def _policy_line():
    return ("policy: local repositories live under "
            f"{', '.join(allowed_roots())} "
            "(safeguards/repo_home_guard.py REPO_HOME; operator-set "
            "2026-08-24)")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("check", "audit", "policy"):
        print(__doc__)
        return 1

    if argv[0] == "policy":
        print(_policy_line())
        return 0

    if argv[0] == "check":
        targets = argv[1:]
        if not targets:
            print("usage: check <path> [path...]")
            return 1
        bad = [t for t in targets if not is_allowed(t)]
        for t in targets:
            mark = "ALLOWED" if t not in bad else "DENIED"
            print(f"{mark:8} {t}")
        if bad:
            print(f"[FAIL] {len(bad)} path(s) outside repo home. "
                  f"{_policy_line()}")
            return 1
        return 0

    # audit
    as_json = "--json" in argv
    roots_arg = None
    if "--roots" in argv:
        i = argv.index("--roots")
        roots_arg = [r for r in argv[i + 1].split(",") if r.strip()]
    probes = roots_arg or default_probe_roots()
    findings = []
    for probe in probes:
        for repo in find_repos(probe):
            findings.append({"repo": repo,
                             "allowed": is_allowed(repo)})
    violations = [f for f in findings if not f["allowed"]]
    if as_json:
        print(json.dumps({"probes": probes,
                          "repos": findings,
                          "violations": len(violations)}, indent=2))
    else:
        for f in findings:
            mark = "ok     " if f["allowed"] else "VIOLATE"
            print(f"{mark} {f['repo']}")
        print(f"- audited {len(probes)} root(s), {len(findings)} "
              f"repo(s), {len(violations)} outside repo home")
        if violations:
            print(_policy_line())
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
