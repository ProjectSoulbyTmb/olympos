"""DAEDALUS blueprint: sla-pulse - owned-time SLO quarantine/revive.

Batch V9 enterprise hardening. The house time rule ("no organ invents
its own timer") made executable for the OS's own services:

  Pulse owns the clock - organs never read wall time; the harness
  injects a FakeClock and drives beats, so SLO behavior is provable
  deterministically (A6 pattern with named states).
  States are law - healthy -> late (misses accruing) -> quarantined
  at slo_max_late -> revived after revive_after cool-down beats.
  Vitals are sorted, state-named rows: {organ, state, last_beat,
  misses} - GAIA consumes exactly this shape.

Extension shape: register(executors) wires fleet vitals onto APOLLO;
commissioning binds real 441xx service probes behind beat()."""

import sys

PULSE = '''"""Sla pulse - injected-clock SLOs with quarantine and revival."""


class FakeClock(object):
    def __init__(self):
        self.beat = 0


class Pulse(object):
    def __init__(self, clock):
        self.clock = clock
        self.organs = {}

    def register(self, organ, every_beats, slo_max_late,
                 revive_after):
        self.organs[organ] = {
            "organ": organ, "every": int(every_beats),
            "slo": int(slo_max_late), "revive": int(revive_after),
            "counter": 0, "misses": 0, "state": "healthy",
            "revive_at": None, "last_beat": None}

    def beat(self):
        """One pulse tick: clock advances; schedule is evaluated."""
        self.clock.beat += 1
        t = self.clock.beat
        for o in self.organs.values():
            if o["state"] == "quarantined":
                if t >= o["revive_at"]:
                    o["state"] = "healthy"
                    o["counter"] = 0
                    o["misses"] = 0
                continue
            o["counter"] += 1
            if o["counter"] >= o["every"]:
                o["counter"] = 0
                o["last_beat"] = t
                o["misses"] = 0
            else:
                o["misses"] += 1
                if o["misses"] >= o["slo"]:
                    o["state"] = "quarantined"
                    o["revive_at"] = t + o["revive"]

    def vitals(self):
        return [dict(state=o["state"], organ=o["organ"],
                     last_beat=o["last_beat"],
                     misses=o["misses"])
                for o in sorted(self.organs.values(),
                                key=lambda x: x["organ"])]


def register(executors):
    """APOLLO drop-in adapter: fleet vitals land here."""

    def _vitals(session, cmd, ctx):
        return {"ok": True, "data": (ctx.get("pulse")
                                     or Pulse(FakeClock()))
                .vitals()}
    executors[("fleet", "vitals")] = _vitals
'''

GATE = '''"""Self-test gate for sla-pulse (exit 0 = green)."""

import sys

from sla_pulse import FakeClock, Pulse


def main():
    clock = FakeClock()
    p = Pulse(clock)

    # diligent organ: every beat, never late
    p.register("apollo", every_beats=1, slo_max_late=3,
               revive_after=4)
    # lazy organ: due every 5th beat but SLO demands 3 -> dies first
    p.register("kinema-host", every_beats=5, slo_max_late=3,
               revive_after=4)

    for _ in range(3):
        p.beat()
    v = {r["organ"]: r for r in p.vitals()}
    assert v["apollo"]["state"] == "healthy", v["apollo"]
    assert v["apollo"]["last_beat"] == 3, v["apollo"]
    assert v["kinema-host"]["state"] == "quarantined", \\
        v["kinema-host"]
    assert v["kinema-host"]["misses"] == 3

    # revival lands exactly on beat 7 (3 quarantine beats + 4 cool-
    # down): still down through beat 6, healthy at the 7th tick
    p.beat(); p.beat(); p.beat()          # beats 4,5,6
    v = {r["organ"]: r for r in p.vitals()}
    assert v["kinema-host"]["state"] == "quarantined", v["kinema-host"]
    p.beat()                               # beat 7
    v = {r["organ"]: r for r in p.vitals()}
    assert v["kinema-host"]["state"] == "healthy", v["kinema-host"]
    assert v["kinema-host"]["misses"] == 0

    # revival is not amnesia: missing again re-quarantines by the law
    for _ in range(3):
        p.beat()
    v = {r["organ"]: r for r in p.vitals()}
    assert v["kinema-host"]["state"] == "quarantined"

    # vitals rows are sorted and shape-complete for GAIA
    rows = p.vitals()
    assert [r["organ"] for r in rows] == \\
        sorted(r["organ"] for r in rows)
    assert all(set(r) == {"state", "organ", "last_beat", "misses"}
               for r in rows)

    print("sla-pulse gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"sla_pulse.py": PULSE, "verify_slapulse.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # quarantine trigger gutted -> sick organs stay 'healthy' forever;
    # the state assertion goes red at the exact beat (independent)
    "slo_blind": ("sla_pulse.py",
                  'if o["misses"] >= o["slo"]:\n'
                  '                    o["state"] = "quarantined"\n'
                  '                    o["revive_at"] = t + '
                  'o["revive"]',
                  'pass'),
}

BLUEPRINT = {
    "description": "VOLTAGE sla-pulse: injected-clock SLOs, "
                   "quarantine + revival, GAIA-shaped vitals",
    "files": FILES,
    "gate": [sys.executable, "verify_slapulse.py"],
    "faults": dict(FAULTS),
}
