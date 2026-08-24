"""POSEIDON subfleet - one private worktree per kernel, ready to sail.

FLOW.md gives every automator its own checkout under .worktrees/<name>
on branch auto/<name>. The fleet registry turns that doctrine into a
single command: every kernel on the tree gets a writer berth - created
idempotently, synced against origin/main, and reported as a table.

    python -m poseidon fleet start          # berth every kernel
    python -m poseidon fleet sync           # absorb origin/main
    python -m poseidon fleet status         # who is where

Berths are ignored by git (see .gitignore) so a full fleet never
pollutes the tide's drift sweep.
"""

import os

from .kernel import TideEngine, _git
# every kernel organ on the tree that owns a writer berth
FLEET = ("atlas", "buskit", "daedalus", "forseti", "gaia", "hades",
         "hypnos", "norn", "poseidon", "ptah", "ratatosk",
         "safeguards", "sindri", "vulcan", "zeus")


def _names(only):
    if not only:
        return FLEET
    wanted = {n.strip() for n in only.split(",") if n.strip()}
    unknown = wanted - set(FLEET)
    if unknown:
        raise SystemExit("unknown kernels: %s (fleet: %s)"
                         % (", ".join(sorted(unknown)),
                            ", ".join(FLEET)))
    return [n for n in FLEET if n in wanted]


def start(eng, only=None):
    names = _names(only)
    for name in names:
        eng.ensure_worktree(name)
        print("berthed: %-12s -> auto/%s" % (name, name))
    return names


def sync(eng, only=None):
    names = _names(only)
    results = {}
    for name in names:
        try:
            eng.sync_branch(name)
            results[name] = "synced"
        except RuntimeError as exc:
            results[name] = "conflict: %s" % exc
        print("%-12s %s" % (name, results[name]))
    return results


def status(eng, only=None):
    names = _names(only)
    _git(eng.root, "fetch", "origin", "--prune", check=False,
         timeout=120.0)
    rows = {}
    for name in names:
        path = eng.wt_path(name)
        ready = os.path.exists(os.path.join(path, ".git"))
        row = {"branch": eng.branch_of(name), "ready": ready}
        if ready:
            dirty = _git(path, "status", "--porcelain",
                         check=False)
            row["dirty"] = bool(dirty.strip())
            counts = _git(eng.root, "rev-list", "--left-right",
                          "--count", "origin/main...auto/%s" % name,
                          check=False)
            parts = counts.split()
            if len(parts) == 2:
                row["behind_main"], row["ahead_main"] = \
                    int(parts[0]), int(parts[1])
        rows[name] = row
        print("%-12s %s" % (name, row))
    return rows


def run(cmd, eng=None, only=None):
    eng = eng or TideEngine()
    return {"start": start, "sync": sync, "status": status}[cmd](
        eng, only=only)
