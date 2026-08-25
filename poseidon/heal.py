"""POSEIDON healing - the tide mends its own wounds.

Every real cycle opens with a light self-repair pass (``auto_pass``):
a damaged writer berth is rebuilt from scratch, orphaned throwaway
indexes are swept, a torn ledger tail (crash mid-append) is trimmed,
and a quarantine earned by broken infrastructure is probed - if the
water runs green again the lane reopens early instead of waiting out
the whole cooldown. The breaker stays honest: probes only clear a
quarantine, they never silence a failure; a persistent cause simply
re-trips it after FAIL_LIMIT fresh attempts.

Pushes heal themselves too (kernel._push_with_heal): a non-fast-
forward rejection adopts origin's copy of the private branch - FLOW.md
gives ``auto/poseidon`` exactly one writer, us - then replays the
snapshot whose source content still waits untouched in the root drift
and pushes again. Transient network errors get one spaced retry.
Nothing is ever force-pushed; a reconcile that cannot land cleanly
raises and lets the quarantine breaker do its job.

Operator surface:

    python -m poseidon heal            # diagnose only
    python -m poseidon heal --deep     # + object-database fsck
    python -m poseidon heal --apply    # diagnose + repair
"""

import glob
import json
import os
import shutil
import stat
import time

from forseti.locker import LaneLock, status as lane_status

from .kernel import (BRANCH, IDX_MAX_AGE_S, LANE, LOCK_STALE_S,
                     _git)


# ------------------------------------------------------------ parts

def _force_rmtree(path):
    """Windows: git marks worktree .git stubs read-only; clear and go."""
    def _relax(fn, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=_relax)


def wt_state(eng):
    """missing | corrupt | ready for the writer berth."""
    dot_git = os.path.join(eng.worktree, ".git")
    if not os.path.exists(dot_git):
        return "missing"
    out = _git(eng.worktree, "rev-parse", "--is-inside-work-tree",
               check=False)
    return "ready" if out.strip() == "true" else "corrupt"


def fix_berth(eng, applied):
    """Rebuild a corrupt berth, berth a missing one. True when ready."""
    st = wt_state(eng)
    if st == "ready":
        return True
    if st == "corrupt":
        _force_rmtree(eng.worktree)
        _git(eng.root, "worktree", "prune", check=False)
        applied.append("berth-corrupt-rebuilt")
    else:
        applied.append("berth-missing-created")
    eng.ensure_worktree()
    return wt_state(eng) == "ready"


def sweep_indexes(eng, applied, age_limit=IDX_MAX_AGE_S):
    """Throwaway snapshot indexes orphaned by a crash. Fresh files may
    belong to a live sibling tide - only age earns the sweep."""
    now = time.time()
    for path in glob.glob(os.path.join(eng.data_dir, "idx-*")):
        try:
            if now - os.path.getmtime(path) > age_limit:
                os.unlink(path)
                applied.append(
                    "idx-swept:%s" % os.path.basename(path))
        except OSError:
            pass


def repair_ledger_tail(path):
    """Trim ONE torn trailing ledger line. Mid-file rot is left for an
    operator - silent rewrites would hide worse damage. True on trim."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return False
    lines = raw.splitlines()
    if not lines:
        return False
    try:
        json.loads(lines[-1])
        return False                       # tail intact
    except ValueError:
        pass
    good = []
    for ln in lines[:-1]:
        try:
            json.loads(ln)
        except ValueError:
            return False                   # deeper rot: hands off
        good.append(ln)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(good) + ("\n" if good else ""))
    os.replace(tmp, path)
    return True


def probes(eng):
    """Cheap green-water checks behind early quarantine release."""
    p = {}
    p["repo"] = _git(eng.root, "rev-parse", "--is-inside-work-tree",
                     check=False).strip() == "true"
    try:
        eng.refresh_remote(force=True)
        p["origin"] = True
    except Exception:                      # noqa: BLE001 - probe
        p["origin"] = False
    lane = lane_status(LANE, root=eng._lock_root)
    lock = LaneLock(LANE, root=eng._lock_root,
                    stale_s=LOCK_STALE_S)
    p["lane"] = bool(lane.get("free")) or lock._is_stale()
    p["berth"] = wt_state(eng) == "ready"
    return p


def maybe_resume(eng, applied):
    """Early release when quarantine infrastructure healed underneath."""
    st = eng._load_state()
    if not eng.quarantined(st):
        return None
    pr = probes(eng)
    if all(pr.values()):
        eng.resume()
        applied.append("quarantine-cleared:probes-green")
    return pr


# ----------------------------------------------------------- passes

def auto_pass(eng):
    """The always-on light pass inside every tide cycle. Never raises."""
    rep = {"applied": [], "errors": []}

    def ledger_step():
        if os.path.exists(eng.ledger_path) and \
                repair_ledger_tail(eng.ledger_path):
            rep["applied"].append("ledger-tail-trimmed")

    def quarantine_step():
        pr = maybe_resume(eng, rep["applied"])
        if pr is not None:
            rep["quarantine_probes"] = pr

    for step in (
        lambda: fix_berth(eng, rep["applied"]),
        lambda: sweep_indexes(eng, rep["applied"]),
        ledger_step,
        quarantine_step,
    ):
        try:
            step()
        except Exception as exc:           # noqa: BLE001 - soft
            rep["errors"].append(str(exc)[:120])
    return rep


def diagnose(eng, deep=False):
    """Facts about the water; every finding carries its own verdict."""
    def add(fid, ok, detail=""):
        findings.append({"id": fid, "ok": bool(ok), "detail": detail})

    findings = []
    add("root-repo",
        _git(eng.root, "rev-parse", "--is-inside-work-tree",
             check=False).strip() == "true")
    st = wt_state(eng)
    add("writer-berth", st == "ready", st)

    counts = _git(eng.root, "rev-list", "--left-right", "--count",
                  "%s...origin/main" % BRANCH, check=False).split()
    if len(counts) == 2:
        add("branch-known", True,
            "ahead=%s behind=%s" % tuple(counts))
    else:
        have = _git(eng.root, "rev-parse", "--verify", "--quiet",
                    BRANCH, check=False)
        # virgin water: no berth branch yet is health, not sickness
        add("branch-known", not have,
            "virgin" if not have else "refs unresolvable")

    counts = _git(eng.root, "rev-list", "--left-right", "--count",
                  "main...origin/main", check=False).split()
    ahead, behind = (counts + ["?", "?"])[:2]
    # main must only ever move by pull: local-only commits are a
    # doctrine violation - reported, never reset (never destroy)
    add("mirror-synced", ahead in ("0", "?"),
        "ahead=%s behind=%s" % (ahead, behind))

    lane = lane_status(LANE, root=eng._lock_root)
    add("lane-free", bool(lane.get("free")),
        "" if lane.get("free") else
        "held pid=%s age_s=%s" % (lane.get("pid"),
                                  lane.get("age_s", "?")))

    torn = False
    try:
        with open(eng.ledger_path, encoding="utf-8") as fh:
            rows = fh.read().splitlines()
        torn = bool(rows) and _is_broken_json(rows[-1])
    except OSError:
        pass
    add("ledger-intact", not torn, "torn tail" if torn else "")

    stale_idx = [p for p in glob.glob(
        os.path.join(eng.data_dir, "idx-*"))
        if time.time() - os.path.getmtime(p) > IDX_MAX_AGE_S]
    add("temp-indexes", not stale_idx,
        ",".join(os.path.basename(p) for p in stale_idx))

    quar = eng.quarantined()
    reason = eng._load_state().get("reason", "")
    add("quarantine", not quar, reason if quar else "")

    if deep:
        ok = _git(eng.root, "fsck", "--connectivity-only",
                  "--no-dangling", check=False)
        add("object-db", "error" not in ok.lower(), ok[:120])

    return {"healthy": all(f["ok"] for f in findings),
            "findings": findings}


def _is_broken_json(line):
    try:
        json.loads(line)
        return False
    except ValueError:
        return True


def repair(eng, apply=False, deep=False):
    """Diagnose, optionally mend, re-diagnose so ``healthy`` is honest."""
    diag = diagnose(eng, deep=deep)
    out = {"healthy": diag["healthy"],
           "findings": diag["findings"],
           "applied": [], "errors": []}
    if not apply:
        return out
    try:
        fix_berth(eng, out["applied"])
    except Exception as exc:               # noqa: BLE001 - report
        out["errors"].append("berth: %s" % str(exc)[:120])
    try:
        sweep_indexes(eng, out["applied"])
    except Exception as exc:               # noqa: BLE001 - report
        out["errors"].append("indexes: %s" % str(exc)[:120])
    try:
        if os.path.exists(eng.ledger_path) and \
                repair_ledger_tail(eng.ledger_path):
            out["applied"].append("ledger-tail-trimmed")
    except Exception as exc:               # noqa: BLE001 - report
        out["errors"].append("ledger: %s" % str(exc)[:120])
    try:
        maybe_resume(eng, out["applied"])
    except Exception as exc:               # noqa: BLE001 - report
        out["errors"].append("quarantine: %s" % str(exc)[:120])
    out["healthy"] = diagnose(eng)["healthy"]
    return out
