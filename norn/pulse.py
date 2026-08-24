"""NORN PULSE: cadence SLOs for periodic work (XNU timekeeping model).

Organs run on beat multiples; an organ that blows its latency SLO too
many consecutive beats is quarantined automatically and revived after
a cool-down - the same autonomic contract as Venus's heart.js, in
Python, for supervisor pollers / updater watch loops / warden patrols.
"""

import time


class Organ:
    def __init__(self, name, fn, every_beats=1,
                 slo_max_ms=None, slo_max_late=3, revive_after=10):
        self.name = name
        self.fn = fn
        self.every_beats = max(1, int(every_beats))
        self.slo_max_ms = slo_max_ms
        self.slo_max_late = max(1, int(slo_max_late))
        self.revive_after = max(1, int(revive_after))
        self.state = "alive"          # alive | quarantined
        self.consecutive_late = 0
        self.quarantine_reason = None
        self.revive_in = 0
        self.runs = 0
        self.late_runs = 0
        self.last_ms = 0.0
        self.last_error = None

    def snapshot(self):
        total = self.runs or 1
        return {"state": self.state,
                "late_ratio": round(self.late_runs / total, 3),
                "last_ms": round(self.last_ms, 2),
                "consecutive_late": self.consecutive_late,
                "reason": self.quarantine_reason}


class Pulse:
    """One beat loop; injectable now_fn keeps tests deterministic."""

    def __init__(self, name="pulse", beat_s=1.0, now_fn=None):
        self.name = name
        self.beat_s = float(beat_s)
        self._now = now_fn or time.monotonic
        self.organs = {}
        self.beats = 0

    def add_organ(self, name, fn, every_beats=1, **slo):
        self.organs[name] = Organ(name, fn, every_beats=every_beats, **slo)
        return self.organs[name]

    def beat(self):
        self.beats += 1
        t0 = self._now()
        for org in self.organs.values():
            if self.beats % org.every_beats:
                continue
            if org.state == "quarantined":
                org.revive_in -= 1
                if org.revive_in <= 0:
                    org.state = "alive"
                    org.consecutive_late = 0
                    org.quarantine_reason = None
                continue
            try:
                org.fn()
            except Exception as exc:
                org.last_error = f"{type(exc).__name__}: {exc}"
            org.runs += 1
            org.last_ms = (self._now() - t0) * 1000.0
            late = False
            if org.slo_max_ms is not None and \
                    org.last_ms > org.slo_max_ms:
                late = True
            if late:
                org.late_runs += 1
                org.consecutive_late += 1
                if org.consecutive_late >= org.slo_max_late:
                    org.state = "quarantined"
                    org.quarantine_reason = (
                        f"slo breach: {org.last_ms:.0f}ms > "
                        f"{org.slo_max_ms}ms for "
                        f"{org.consecutive_late} beats")
                    org.revive_in = org.revive_after

    def vitals(self):
        return {"name": self.name, "beat_s": self.beat_s,
                "beats": self.beats,
                "organs": {n: o.snapshot()
                           for n, o in self.organs.items()}}
