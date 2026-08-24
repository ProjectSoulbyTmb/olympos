"""POSEIDON subfleet - one private worktree per kernel, ready to sail.

FLOW.md gives every automator its own checkout under .worktrees/<name>
on branch auto/<name>. The fleet registry turns that doctrine into a
single command: every kernel on the tree gets a writer berth - created
idempotently, synced against origin/main, and reported as a table.

    python -m poseidon fleet start          # berth every kernel
    python -m poseidon fleet sync           # absorb origin/main
    python -m poseidon fleet status         # who is where

Speed rules:
  - ONE shared fetch at the root per invocation (worktrees share a
    single object store, so one fetch updates every berth's view),
  - berth operations then run in parallel threads over purely local
    git work,
  - ``sync`` lazily births any missing berth first: one command always
    leaves the whole fleet current.

Berths are ignored by git (see .gitignore) so a full fleet never
pollutes the tide's drift sweep.
"""

import os
from concurrent.futures import ThreadPoolExecutor

from .kernel import TideEngine, _git

# every kernel organ on the tree that owns a writer berth
FLEET = ("atlas", "buskit", "daedalus", "forseti", "gaia", "hades",
         "hypnos", "norn", "poseidon", "ptah", "ratatosk",
         "safeguards", "sindri", "vulcan", "zeus")

FLEET_WORKERS = 8


def _names(only):
    if not only:
        return list(FLEET)
    wanted = {n.strip() for n in only.split(",") if n.strip()}
    unknown = wanted - set(FLEET)
    if unknown:
        raise SystemExit("unknown kernels: %s (fleet: %s)"
                         % (", ".join(sorted(unknown)),
                            ", ".join(FLEET)))
    return [n for n in FLEET if n in wanted]


def _run_parallel(fn, names):
    out = {}
    with ThreadPoolExecutor(max_workers=min(FLEET_WORKERS,
                                            max(1, len(names)))) as ex:
        futures = {name: ex.submit(fn, name) for name in names}
        for name, fut in futures.items():
            try:
                out[name] = fut.result()
            except Exception as exc:          # noqa: BLE001 - report
                out[name] = "error: %s" % str(exc)[:160]
    return out


def start(eng, only=None):
    names = _names(only)
    results = _run_parallel(lambda n: (eng.ensure_worktree(n), n)[1],
                            names)
    for name in names:
        print("berthed: %-12s -> auto/%s" % (name, results[name]))
    return names


def sync(eng, only=None):
    names = _names(only)
    eng.refresh_remote()  # one fetch feeds every berth

    def absorb(name):
        eng.ensure_worktree(name)   # lazy birth: sync implies ready
        eng.sync_branch(name)
        return "synced"

    results = _run_parallel(absorb, names)
    for name in names:
        print("%-12s %s" % (name, results[name]))
    return results


def status(eng, only=None):
    names = _names(only)
    eng.refresh_remote()

    def inspect(name):
        path = eng.wt_path(name)
        ready = os.path.exists(os.path.join(path, ".git"))
        row = {"branch": eng.branch_of(name), "ready": ready}
        if not ready:
            return row
        dirty = _git(path, "status", "--porcelain", check=False)
        row["dirty"] = bool(dirty.strip())
        counts = _git(eng.root, "rev-list", "--left-right",
                      "--count",
                      "origin/main...auto/%s" % name, check=False)
        parts = counts.split()
        if len(parts) == 2:
            row["behind_main"], row["ahead_main"] = \
                int(parts[0]), int(parts[1])
        return row

    rows = _run_parallel(inspect, names)
    for name in names:
        print("%-12s %s" % (name, rows[name]))
    return rows


def run(cmd, eng=None, only=None):
    eng = eng or TideEngine()
    return {"start": start, "sync": sync, "status": status}[cmd](
        eng, only=only)
