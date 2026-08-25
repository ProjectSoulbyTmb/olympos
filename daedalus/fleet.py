"""DAEDALUS subfleet - builder lanes renting ATLAS guests.

A lane is one weaver: it owns an atlas guest, takes build jobs from
the workshop queue, and reports health.

Self-building lanes (an organ repairs what it owns):
- a lane provisions its own guest at birth and re-weaves a corrupted
  one without waiting for the warden;
- consecutive gate failures put a lane into a short self-imposed
  cooldown instead of feeding it more work while hot - the warden's
  hard purge stays the last resort, not the first reaction;
- dispatch prefers lanes that are warm for a job's blueprint and riding
  a success streak, so fluid builds reuse proven worlds instead of
  paying cold-start costs on every flight.
"""

import time

from atlas.kernel import AtlasError

try:                        # package import (server / kernel)
    from . import content
except ImportError:         # script mode (verify_daedalus.py)
    import content


class Lane:
    def __init__(self, name, hypervisor):
        self.name = name
        self.hv = hypervisor
        self.guest = None
        self.job = None            # current job dict or None
        self.ok = 0
        self.failed = 0
        self.fails_row = 0         # consecutive failures
        self.streak = 0            # consecutive successes
        self.last_error = None
        self.last_bp = None        # blueprint this guest is warm for
        self.rebuilds = 0          # self-heal count (observability)
        self.cooldown_until = 0.0
        self.state = "idle"        # idle | weaving | gating | maintenance
        self._ensure_guest()

    # ------------------------------------------------------- guest ---

    def _ensure_guest(self):
        if self.guest is not None and self.guest in self.hv.guests:
            return
        gid = f"lane-{self.name}"
        try:
            snap = self.hv.create(gid)
            self.guest = snap["id"]
        except AtlasError as exc:
            # stale directory or full house: adopt if it is ours alone
            if "exists" in str(exc) and gid in self.hv.guests:
                self.guest = gid
                self.hv.stop(gid)
            else:
                raise

    def heal(self):
        """Self-building lane: purge the sick world, weave a fresh one."""
        if self.guest and self.guest in self.hv.guests:
            try:
                self.hv.stop(self.guest)
            except AtlasError:
                pass
            try:
                self.hv.purge(self.guest)
            except KeyError:
                pass
        self.guest = None
        self._ensure_guest()
        self.rebuilds += 1
        self.state = "idle"

    def available(self, now=None):
        """True when this lane may take work right now."""
        now = _now() if now is None else now
        return (self.job is None
                and self.state != "maintenance"
                and now >= self.cooldown_until)

    # --------------------------------------------------------- jobs ---

    def take(self, job):
        if self.job is not None:
            raise AtlasError(f"lane {self.name} is busy")
        self.job = job
        self.last_bp = job.get("blueprint")
        self.state = "weaving"

    def release(self, ok, error=None, heal=False):
        if ok:
            self.ok += 1
            self.streak += 1
            self.fails_row = 0
        else:
            self.failed += 1
            self.fails_row += 1
            self.streak = 0
            self.last_error = error
            if self.fails_row >= content.LANE_COOLDOWN_AFTER_FAILS:
                self.cooldown_until = _now() + content.LANE_COOLDOWN_S
                self.fails_row = 0     # served its sentence; watch anew
        self.job = None
        self.state = "idle"
        if heal:
            self.heal()
        else:
            self.hv.reap()

    def snapshot(self):
        return {"lane": self.name, "guest": self.guest,
                "state": self.state,
                "job": (self.job or {}).get("id") if self.job else None,
                "ok": self.ok, "failed": self.failed,
                "streak": self.streak, "fails_row": self.fails_row,
                "last_blueprint": self.last_bp,
                "rebuilds": self.rebuilds,
                "cooldown_s": max(0, round(
                    self.cooldown_until - _now(), 1)),
                "last_error": self.last_error}


class SubFleet:
    """Pool of self-building lanes; affinity dispatch + health."""

    def __init__(self, size, hypervisor):
        self.hv = hypervisor
        self.lanes = [Lane(f"L{i+1}", hypervisor)
                      for i in range(max(1, int(size)))]
        self._retiring = set()      # names draining out after a shrink

    def resize(self, size):
        """Live fleet resizing.

        Grow appends lanes immediately (subject to the ATLAS hypervisor
        guest ceiling - fails loud past it). Shrink retires IDLE excess
        lanes on the spot; busy excess lanes are flagged and leave only
        after their current job drains. Returns a report dict.
        """
        from atlas import content as ac
        want = max(1, int(size))
        if want > ac.MAX_GUESTS:
            raise ValueError(
                f"resize refused: {want} lanes exceeds the ATLAS "
                f"hypervisor ceiling ({ac.MAX_GUESTS} guests)")
        report = {"added": [], "retired": [], "pending": []}
        while len(self.lanes) < want:
            lane = Lane(f"L{len(self.lanes) + 1}", self.hv)
            self.lanes.append(lane)
            report["added"].append(lane.name)
        while len(self.lanes) > want:
            # retire from the tail: newest lanes first
            lane = self.lanes[-1]
            if lane.job is not None:
                self._retiring.add(lane.name)
                report["pending"].append(lane.name)
                break               # keep order stable until it drains
            self.lanes.pop()
            self._retiring.discard(lane.name)
            try:
                self.hv.stop(lane.guest)
            except Exception:       # noqa: BLE001 - already gone
                pass
            report["retired"].append(lane.name)
        return report

    def reap_retired(self):
        """Drop shrink-flagged lanes once their job has drained."""
        for lane in list(self.lanes):
            if lane.name in self._retiring and lane.job is None:
                self._retiring.discard(lane.name)
                self.lanes.remove(lane)
                try:
                    self.hv.stop(lane.guest)
                except Exception:   # noqa: BLE001 - already gone
                    pass

    def acquire(self, job=None):
        """Pick an idle lane for this job, or None when all are busy /
        cooling down.

        Preference order: a lane already warm for the job's blueprint,
        then the longest success streak, then fewest lifetime failures.
        """
        idle = [l for l in self.lanes
                if l.available() and l.name not in self._retiring]
        if not idle:
            return None

        def key(l):
            warm = 0 if (job is not None
                         and l.last_bp == job.get("blueprint")) else 1
            return (warm, -l.streak, l.failed, l.name)

        return sorted(idle, key=key)[0]

    def snapshot(self):
        return [l.snapshot() for l in self.lanes]

    def busy_count(self):
        return sum(1 for l in self.lanes if l.job is not None)


class StuckBuild(RuntimeError):
    pass


def _now():
    return time.time()
