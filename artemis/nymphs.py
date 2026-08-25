"""ARTEMIS's nymphs - the huntress's retinue.

Mythologically, Artemis hunts with her nymphs; operationally, each
nymph owns a slice of the signature board so every sweep is a named
worker with a clear beat - no orphan duties, no double-claiming
(pinned by the verify suite).

Advanced automation rides DAEDELUS: every nymph can be woven from the
'nymph-hunter' blueprint, gated inside an ATLAS jail guest against a
synthetic sick workspace, and fault-injected drills prove the
fix-pass converges her back if she ever ships blind. A drill is proof,
not patrol - sweeps stay cheap and local; drills run on demand or on
a bounded cadence via config {"drill_every_sweeps": N}.
"""

import time
from collections import namedtuple

Nymph = namedtuple("Nymph", "name domain signatures")

# The retinue (name, beat, owned signatures).
NYMPHS = (
    Nymph("daphne", "code hunts", ("compile-break",)),
    Nymph("cyrene", "network hunts", ("retired-port-squatter",)),
    Nymph("arethusa", "bus hunts", ("corrupt-letters", "stale-lock")),
    Nymph("britomartis", "integrity hunts",
          ("ledger-corruption", "missing-baseline")),
    Nymph("taygete", "liveness hunts", ("stale-organ",)),
    Nymph("maera", "git hygiene",
          ("tracked-artifacts", "gitignore-drift")),
)

_BY_NAME = {n.name: n for n in NYMPHS}


def get(name):
    return _BY_NAME.get(name)


def coverage():
    """signature -> nymph name. Every signature claimed exactly once."""
    claims = {}
    for nymph in NYMPHS:
        for sig in nymph.signatures:
            if sig in claims:
                raise RuntimeError(
                    f"{sig} claimed by both {claims[sig]} "
                    f"and {nymph.name}")
            claims[sig] = nymph.name
    return claims


def dispatch(hunt_module):
    """Yield (nymph_name, sig_name, hunt_fn, repair_fn) for the whole
    board, in nymph order. Raises when the roster drifts out of sync
    with the kernel's registry - a duty nobody owns is an incident."""
    registry = {name: (fn, rep) for name, fn, rep
                in hunt_module.SIGNATURES}
    claims = coverage()
    missing = sorted(set(registry) - set(claims))
    stale = sorted(set(claims) - set(registry))
    if missing or stale:
        raise RuntimeError("roster drift - unowned: "
                           f"{missing}; phantom: {stale}")
    for nymph in NYMPHS:
        for sig in nymph.signatures:
            fn, repair = registry[sig]
            yield nymph.name, sig, fn, repair


# ------------------------------------------------------------- drills

def drill(ctx=None, lanes=2, workshop_factory=None):
    """Prove every nymph through the DAEDELUS workshop.

    Each nymph is woven from the 'nymph-hunter' blueprint into her own
    ATLAS jail guest and must pass her self-test gate against a
    synthetic sick workspace. Fault-free builds here are the deployment
    gate; fault-injected drills (spec faults=["mute_locks"] ...) ride
    the same machinery offline whenever you want convergence proof.

    Returns {"results": [...], "degraded": bool}. Never raises -
    an unavailable workshop degrades to a recorded T3 finding.
    """
    from artemis import hunt

    ctx = hunt.make_ctx(**(ctx or {}))
    results, degraded, why = [], False, None
    ws = None
    try:
        ws = (workshop_factory or _make_workshop)(lanes=lanes)
    except Exception as exc:         # noqa: BLE001 - degrade, don't die
        degraded, why = True, f"{type(exc).__name__}: {exc}"

    if ws is not None:
        try:
            specs = [{"blueprint": "nymph-hunter",
                      "name": f"nymph-{n.name}",
                      "params": {"NYMPH_NAME": n.name},
                      "attempts": 2}
                     for n in NYMPHS]
            jids = [ws.submit(s)["id"] for s in specs]
            # drain_parallel weaves at most `lanes` jobs per call -
            # keep cycling until every nymph's job reaches a verdict
            got = {}
            deadline = time.time() + 300
            while len(got) < len(jids) and time.time() < deadline:
                drained = ws.drain_parallel(max_jobs=lanes)
                for r in drained["results"]:
                    rid = r.get("id")
                    if rid is None:
                        continue
                    if r.get("retrying"):
                        got.pop(rid, None)   # back in queue - wait
                    else:
                        got[rid] = r
                if not drained["results"] and not ws.queue:
                    break
            for nid, n in zip(jids, NYMPHS):
                r = got.get(nid)
                if r is None:
                    ok, detail = False, "no verdict before deadline"
                else:
                    ok = bool(r.get("ok"))
                    detail = ""
                    if ok:
                        detail = "gate green in jail"
                    else:
                        # gates speak on stdout; keep the first useful
                        # FAIL line so a red drill is diagnosable
                        for src in (r.get("error"), r.get("stderr"),
                                    r.get("stdout")):
                            text = str(src or "")
                            line = next((ln.strip() for ln in
                                         text.splitlines()
                                         if "FAIL" in ln or ln.strip()),
                                        "")
                            if line:
                                detail = line[:200]
                                break
                results.append({
                    "nymph": n.name, "ok": ok,
                    "job": nid,
                    "attempts": (r or {}).get("attempts"),
                    "detail": detail})
                hunt.record(ctx, {
                    "nymph": n.name, "signature": "drill",
                    "target": f"nymph-hunter/{n.name}",
                    "detail": detail,
                    "severity": "T3" if ok else "T1",
                    "repairable": False},
                    "gate-green" if ok else "gate-red")
        except Exception as exc:     # noqa: BLE001 - degrade loudly
            degraded, why = True, f"{type(exc).__name__}: {exc}"
        finally:
            restore_workshop_paths()

    if degraded:
        for n in NYMPHS:
            results.append({"nymph": n.name, "ok": None,
                            "job": None, "attempts": None,
                            "detail": f"workshop unavailable - {why}"})
        hunt.record(ctx, {
            "nymph": "-", "signature": "drill-degraded",
            "target": "daedalus",
            "detail": f"workshop unavailable: {why}",
            "severity": "T3", "repairable": False},
            "degraded")

    green = sum(1 for r in results if r["ok"])
    summary = {"drill": True, "green": green, "total": len(NYMPHS),
               "degraded": degraded, "why": why, "results": results}
    hunt.log(f"drill: {green}/{len(NYMPHS)} nymphs proven"
             + (" (workshop unavailable)" if degraded else ""))
    return summary


def _make_workshop(lanes=2):
    """Build a sandboxed Workshop whose guests/artifacts live under
    data/artemis/drill/ so drills never touch shared organ state.
    Paths are restored by restore_workshop_paths() after the drain."""
    import os

    from atlas.kernel import Hypervisor
    import atlas.content as ac
    import daedalus.content as dc
    from daedalus.kernel import Workshop

    base = os.path.join(here(), "data", "artemis", "drill")
    guests = os.path.join(base, "guests")

    saved_d = {f: getattr(dc, f) for f in
               ("DATA_DIR", "AUDIT_PATH", "ARTIFACTS_DIR",
                "REPAIR_STATS_PATH")}
    saved_a = {"GUESTS_DIR": ac.GUESTS_DIR,
               "AUDIT_PATH": ac.AUDIT_PATH}
    dc.DATA_DIR = os.path.join(base, "daedalus")
    dc.AUDIT_PATH = os.path.join(dc.DATA_DIR, "audit.jsonl")
    dc.ARTIFACTS_DIR = os.path.join(dc.DATA_DIR, "artifacts")
    dc.REPAIR_STATS_PATH = os.path.join(dc.DATA_DIR,
                                        "repair_stats.json")
    ac.GUESTS_DIR = guests
    ac.AUDIT_PATH = os.path.join(base, "atlas-audit.jsonl")
    os.makedirs(guests, exist_ok=True)
    _PENDING.append((dc, saved_d, ac, saved_a))

    hv = Hypervisor()
    return Workshop(hypervisor=hv,
                    lanes=max(1, min(int(lanes), 6)))


_PENDING = []


def restore_workshop_paths():
    """Put daedalus/atlas content paths back after a drill."""
    while _PENDING:
        dc, saved_d, ac, saved_a = _PENDING.pop()
        for f, v in saved_a.items():
            setattr(ac, f, v)
        for f, v in saved_d.items():
            setattr(dc, f, v)


def here():
    import os
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
