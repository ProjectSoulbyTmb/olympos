"""DAEDALUS subfleet - builder lanes renting ATLAS guests.

A lane is one weaver: it owns an atlas guest, takes build jobs from
the workshop queue, and reports health. Dispatch is least-recently-
used across healthy lanes; a lane that fails repeatedly is pulled for
maintenance (its guest purged and rebuilt) by the warden.
"""

import time

from atlas.kernel import AtlasError


class Lane:
    def __init__(self, name, hypervisor):
        self.name = name
        self.hv = hypervisor
        self.guest = None
        self.job = None            # current job dict or None
        self.ok = 0
        self.failed = 0
        self.last_error = None
        self.state = "idle"        # idle | weaving | gating | maintenance
        self._ensure_guest()

    def _ensure_guest(self):
        if self.guest is not None and self.guest in self.hv.guests:
            return
        try:
            snap = self.hv.create(f"lane-{self.name}")
            self.guest = snap["id"]
        except AtlasError as exc:
            # stale directory or full house: adopt if it is ours alone
            gid = f"lane-{self.name}"
            if "exists" in str(exc) and gid in self.hv.guests:
                self.guest = gid
                self.hv.stop(gid)
            else:
                raise

    def take(self, job):
        if self.job is not None:
            raise AtlasError(f"lane {self.name} is busy")
        self.job = job
        self.state = "weaving"

    def release(self, ok, error=None):
        if ok:
            self.ok += 1
        else:
            self.failed += 1
            self.last_error = error
        self.job = None
        self.state = "idle"
        self.hv.reap()

    def snapshot(self):
        return {"lane": self.name, "guest": self.guest,
                "state": self.state,
                "job": (self.job or {}).get("id") if self.job else None,
                "ok": self.ok, "failed": self.failed,
                "last_error": self.last_error}


class SubFleet:
    """Fixed pool of lanes; dispatch + health reporting."""

    def __init__(self, size, hypervisor):
        self.lanes = [Lane(f"L{i+1}", hypervisor)
                      for i in range(max(1, int(size)))]

    def acquire(self):
        """Least-failed idle lane, or None when the fleet is busy."""
        idle = [l for l in self.lanes if l.job is None
                and l.state != "maintenance"]
        if not idle:
            return None
        return sorted(idle, key=lambda l: (l.failed, l.ok))[0]

    def snapshot(self):
        return [l.snapshot() for l in self.lanes]

    def busy_count(self):
        return sum(1 for l in self.lanes if l.job is not None)


class StuckBuild(RuntimeError):
    pass
