#!/usr/bin/env python3
"""mirror_sync - keep the D:\\Default Project execution copy truthful.

The scheduled tasks and watchdogs execute from the mirror clone, not
from this workspace. A lane that commits here but forgets to sync the
mirror ships stale kernels silently (root cause of the PERSEPHONE
state-root incident staying invisible for hours - lesson L035's cousin).

Modes:
    --hook      post-commit mode: sync exactly the paths named by HEAD.
                Never raises, never blocks (post-commit cannot fail).
    --sync      full pass: copy every committed-clean file that differs;
                skip other lanes' uncommitted WIP.
    --audit     report only; pair with --strict to exit non-zero on drift.

Deletions are reported, never automatic. Stdlib only.
"""

import os
import subprocess
import sys

MIRROR = os.environ.get("MIRROR_HOME", "D:\\Default Project")
SKIP_DIRS = {".git", "node_modules", "__pycache__", "data", "runs",
             "dist", "bin", "engine"}


def git(*args):
    return subprocess.run(["git", *args], capture_output=True,
                          text=True, encoding="utf-8").stdout


def same(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                ca, cb = fa.read(1 << 20), fb.read(1 << 20)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def copy_one(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".sync-tmp"
    with open(tmp, "wb") as fo, open(src, "rb") as fi:
        fo.write(fi.read())
    os.replace(tmp, dst)


def workspace_root():
    return git("rev-parse", "--show-toplevel").strip()


def dirty_paths():
    out = set()
    for line in git("status", "--porcelain").splitlines():
        if len(line) > 3:
            out.add(line[3:].strip().strip('"').replace("/", os.sep))
    return out


def committed_paths(rev="HEAD"):
    out = []
    for line in git("show", "--name-status", "--format=", rev).splitlines():
        parts = line.split("\t")
        if parts and parts[0].startswith(("A", "M", "R")):
            out.append(parts[-1].replace("/", os.sep))
    return out


def hook_mode(ws):
    """Sync just-committed paths. Always exit 0."""
    try:
        if not os.path.isdir(MIRROR):
            print(f"[mirror] {MIRROR} absent - nothing to converge here")
            return 0
        n = 0
        for f in committed_paths():
            src = os.path.join(ws, f)
            if not os.path.isfile(src):
                continue                        # deleted in this commit
            try:
                copy_one(src, os.path.join(MIRROR, f))
                n += 1
            except OSError as exc:
                print(f"[mirror] warn: {f}: {exc}", file=sys.stderr)
        if n:
            print(f"[mirror] post-commit synced {n} file(s)")
    except Exception as exc:                       # noqa: BLE001
        print(f"[mirror] hook skipped: {exc}", file=sys.stderr)
    return 0


def full_pass(ws, apply_fixes=True, strict=False):
    if not os.path.isdir(MIRROR):
        print(f"SKIP {MIRROR} not present on this machine")
        return 0
    tracked = [t.replace("/", os.sep)
               for t in git("ls-files").splitlines() if t]
    dirty = dirty_paths()

    def is_wip(rel):
        r = rel.replace(os.sep, "/")
        d = {x.replace(os.sep, "/") for x in dirty}
        return r in d or any(r.startswith(x + "/") for x in d)

    synced = wip = drift = 0
    drifted = []
    for f in tracked:
        rel = f.replace(os.sep, "/")
        if is_wip(rel):
            wip += 1
            continue
        src = os.path.join(ws, f)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(MIRROR, f)
        if not os.path.isfile(dst):
            drift += 1
            if apply_fixes:
                copy_one(src, dst)
            else:
                drifted.append(rel)
            continue
        if not same(src, dst):
            drift += 1
            if apply_fixes:
                copy_one(src, dst)
            else:
                drifted.append(rel)
        elif apply_fixes:
            synced += 1
    print(f"tracked={len(tracked)}  clean-synced={synced}  "
          f"wip-skipped={wip}  drift={'fixed' if apply_fixes else 'found'}"
          f"={drift}")
    if not apply_fixes and drifted:
        for f in drifted[:20]:
            print(f"  drift: {f}")
        if len(drifted) > 20:
            print(f"  ... and {len(drifted) - 20} more")
    if strict and drift:
        return 1
    return 0


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    ws = workspace_root()
    if "--hook" in args:
        return hook_mode(ws)
    if "--sync" in args:
        return full_pass(ws, apply_fixes=True)
    if "--audit" in args:
        return full_pass(ws, apply_fixes=False, strict="--strict" in args)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
