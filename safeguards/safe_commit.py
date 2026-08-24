"""SAFEGUARDS safe-commit - isolated-index commits for shared checkouts.

Incident: a 15-minute GAIA patrol lane kept staged files in the shared
checkout, contaminating another agent's commit with unrelated changes.
Manual fix was a private GIT_INDEX_FILE; this productizes it.

Usage:
    python safeguards/safe_commit.py -m "subject" path [path ...]

Behavior:
- builds a TEMP index seeded from HEAD (never touches .git/index);
- stages exactly the given paths from the worktree;
- refuses if any given path is missing, or if HEAD moves mid-run;
- runs safeguards/check.py --strict over exactly those paths;
- commits and prints the new sha;
- the shared index and any other lane's staged files are untouched.

Exit 0 on success (sha on stdout), 2 on refused/failed commit.
"""

import os
import subprocess
import sys
import tempfile

# operate on whatever checkout we are invoked from - like git itself
ROOT = os.getcwd()
# identity fallback: the checkout that ships this toolkit
HOME_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_identity():
    """Fresh clones on machines without global git identity cannot
    commit. Copy name/email from the toolkit's home repo when the
    working checkout has none. Returns error string or None."""
    missing = [k for k in ("user.name", "user.email")
               if not git("config", "--get", k).stdout.strip()]
    if not missing:
        return None
    for k in missing:
        val = subprocess.run(
            ["git", "-C", HOME_REPO, "config", "--get", k],
            capture_output=True, text=True).stdout.strip()
        if not val:
            return (f"no {k} here or in {HOME_REPO}; set "
                    f"git config --global {k}")
        r = git("config", k, val)
        if r.returncode:
            return f"cannot set {k}: {r.stderr}"
    return None


def git(*args, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, env=env)


def head_sha():
    return git("rev-parse", "HEAD").stdout.strip()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-m" not in argv:
        print("usage: safe_commit.py -m MESSAGE path [path ...]",
              file=sys.stderr)
        return 2
    mi = argv.index("-m")
    message = argv[mi + 1] if len(argv) > mi + 1 else ""
    paths = [a for i, a in enumerate(argv)
             if i != mi and i != mi + 1 and not a.startswith("-")]
    if not message or not paths:
        print("safe_commit: need -m MESSAGE and at least one path",
              file=sys.stderr)
        return 2

    base = head_sha()
    fd, tmp_index = tempfile.mkstemp(prefix="safeg index-", suffix=".idx")
    os.close(fd)
    env = {"GIT_INDEX_FILE": tmp_index}

    try:
        # seed temp index from HEAD so unrelated staged junk is absent
        r = git("read-tree", "HEAD", env_extra=env)
        if r.returncode:
            print(f"safe_commit: read-tree failed: {r.stderr}",
                  file=sys.stderr)
            return 2
        deletions = False
        for p in paths:
            ap = os.path.join(ROOT, p)
            tracked = git("ls-files", "--", p).stdout.strip()
            if os.path.isfile(ap) or os.path.isdir(ap):
                r = git("add", "--", p, env_extra=env)
                if r.returncode:
                    print(f"safe_commit: add failed for {p}: {r.stderr}",
                          file=sys.stderr)
                    return 2
            elif tracked:
                # gone from worktree but tracked -> stage the deletion
                r = git("rm", "--cached", "--quiet", "--", p,
                        env_extra=env)
                if r.returncode:
                    print(f"safe_commit: cannot stage deletion of {p}: "
                          f"{r.stderr}", file=sys.stderr)
                    return 2
                deletions = True
            else:
                print(f"safe_commit: unknown path (not on disk, not "
                      f"tracked): {p}", file=sys.stderr)
                return 2
        if head_sha() != base:
            print("safe_commit: HEAD moved mid-operation; aborting",
                  file=sys.stderr)
            return 2
        err = _ensure_identity()
        if err:
            print(f"safe_commit: {err}", file=sys.stderr)
            return 2
        gate = subprocess.run(
            [sys.executable,
             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "check.py"),
             "--strict", *paths],
            cwd=ROOT, capture_output=True, text=True,
            env={**os.environ, "GIT_INDEX_FILE": tmp_index})
        print(gate.stdout, end="")
        if gate.returncode:
            print("safe_commit: safeguards rejected the change",
                  file=sys.stderr)
            return 2
        r = git("commit", "-m", message, env_extra=env)
        if r.returncode:
            print(f"safe_commit: commit failed:\n{r.stdout}\n{r.stderr}",
                  file=sys.stderr)
            return 2
        sha = head_sha()
        print(sha)
        note = " (+ deletions)" if deletions else ""
        print(f"safe_commit: committed {len(paths)} path(s){note} as "
              f"{sha[:12]} via isolated index", file=sys.stderr)
        return 0
    finally:
        try:
            os.unlink(tmp_index)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
