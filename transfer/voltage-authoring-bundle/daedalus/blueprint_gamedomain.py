"""DAEDALUS blueprint: game-domain - recursion-guarded workshop lane.

Batch V7 studio tier. The `voltage game weave` verb drives DAEDALUS
itself - the one organ that could recurse into its own commander.
This blueprint owns that guard as law:

  Depth cap - commission chains carry their origin; operator-initiated
  work is depth 0, voltage-initiated is depth 1 (= MAX), anything
  deeper is refused with a named error before submission.
  Envelope shape - commissions are structured payloads (blueprint,
  depth, params), never free text; verdicts parse defensively.

Extension shape: register(executors) wires game weave/selftest/
status onto APOLLO's drop-in protocol (status/list-blueprints stay
read-only L0 verbs backed by the workshop catalog)."""

import sys

GUARD = '''"""Workshop guard - the recursion cap for voltage->daedalus calls."""

MAX_COMMISSION_DEPTH = 1


class RecursionRefused(ValueError):
    pass


def commission_envelope(blueprint, origin_chain, params=None):
    """Shape and bound one workshop commission.

    origin_chain: actors from root, e.g. ["operator"] or
    ["operator", "voltage"]. depth = len(chain) - 1."""
    chain = [str(x) for x in (origin_chain or [])]
    if not chain or chain[0] != "operator":
        raise RecursionRefused(
            "commission chains start at 'operator'")
    depth = len(chain) - 1
    if depth > MAX_COMMISSION_DEPTH:
        raise RecursionRefused(
            "recursion cap: depth %d exceeds %d (chain=%r)"
            % (depth, MAX_COMMISSION_DEPTH, chain))
    bp = str(blueprint or "").strip()
    if not bp:
        raise RecursionRefused("blueprint name required")
    return {"origin": "voltage", "depth": depth,
            "blueprint": bp, "params": dict(params or {})}


def parse_verdict(envelope):
    """Defensive read of a workshop reply - never trusts shape."""
    if not isinstance(envelope, dict):
        return {"ok": False, "error": "malformed verdict"}
    err = envelope.get("error")
    if err:
        return {"ok": False, "error": str(err)}
    if not envelope.get("ok"):
        return {"ok": False,
                "error": str(envelope.get("detail")
                             or "workshop refused")}
    art = envelope.get("artifact") or {}
    return {"ok": True,
            "artifact_id": str(art.get("id") or ""),
            "sha256": str(art.get("sha256") or "")}


def register(executors):
    """APOLLO drop-in adapter: game domain lands here. The workshop
    endpoint arrives via ctx (loopback :44105 at commissioning)."""

    def _weave(session, cmd, ctx):
        env = commission_envelope(
            str(cmd.target or ""),
            ["operator", "voltage"],
            params={"seed": cmd.flags.get("seed", "")})
        # Commissioning binds the loopback workshop call here; the
        # guard above already refused anything unlawful.
        return {"ok": True, "queued": env,
                "note": "workshop bind lands at commissioning"}
    executors[("game", "weave")] = _weave

    def _selftest(session, cmd, ctx):
        env = commission_envelope(
            str(cmd.target or ""),
            ["operator", "voltage"])
        return {"ok": True, "selftest": env}
    executors[("game", "selftest")] = _selftest
'''

GATE = '''"""Self-test gate for game-domain (exit 0 = green)."""

import sys

from workshop_guard import (RecursionRefused, commission_envelope,
                            parse_verdict)


def main():
    # operator-initiated: depth 0, lawful
    v0 = commission_envelope("godot-game", ["operator"])
    assert v0["depth"] == 0 and v0["origin"] == "voltage", v0

    # voltage-initiated: depth 1 = exactly at the cap, lawful
    v1 = commission_envelope("godot-game", ["operator", "voltage"],
                             params={"seed": "42"})
    assert v1["depth"] == 1 and v1["params"] == {"seed": "42"}, v1

    # deeper chains are refused by name, before any submission
    for chain in (["operator", "voltage", "apollo"],
                  ["operator", "voltage", "apollo", "voltage"]):
        try:
            commission_envelope("godot-game", chain)
            raise AssertionError("recursion let slip: %r" % chain)
        except RecursionRefused as exc:
            assert "recursion cap" in str(exc), exc

    # malformed commissions refuse cleanly
    for bad in ((None, ["operator"]), ("", ["operator"]),
                ("godot-game", []), ("godot-game", ["rogue"])):
        try:
            commission_envelope(bad[0], bad[1])
            raise AssertionError("bad commission accepted: %r" % (bad,))
        except RecursionRefused:
            pass

    # verdict parsing never trusts shape
    assert parse_verdict({"ok": True,
                          "artifact": {"id": "a-9",
                                       "sha256": "deadbeef"}}
                         )["artifact_id"] == "a-9"
    assert parse_verdict({"ok": False,
                          "error": "gate red"})["ok"] is False
    assert parse_verdict(None)["ok"] is False
    assert parse_verdict("nonsense")["ok"] is False
    assert parse_verdict({})["ok"] is False

    print("game-domain gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"workshop_guard.py": GUARD,
            "verify_workshopguard.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # cap raised to absurdity -> deep chains slip through -> the
    # refusal assertion goes red (independent breaker)
    "depth_uncapped": ("workshop_guard.py",
                       "MAX_COMMISSION_DEPTH = 1",
                       "MAX_COMMISSION_DEPTH = 99"),
}

BLUEPRINT = {
    "description": "VOLTAGE game-domain: recursion-capped workshop "
                   "commissions, defensive verdict parsing",
    "files": FILES,
    "gate": [sys.executable, "verify_workshopguard.py"],
    "faults": dict(FAULTS),
}
