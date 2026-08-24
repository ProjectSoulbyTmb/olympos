"""DAEDALUS warden (VULCAN pattern): patrols the workshop for waste,
runaways and stuck lanes, and repairs them automatically.

Findings -> actions, every action audited:
  stuck lane        -> stop guest, requeue job (once; then quarantine)
  runaway attempts  -> blueprint quarantined after repeated failure
  dirty guest       -> purge on reap
"""

import time

from atlas.kernel import AtlasError


class Warden:
    def __init__(self, workshop):
        self.ws = workshop
        self.enabled = True
        self.findings = []
        self.actions = []
        self._quarantined = {}     # blueprint -> revive_at epoch

    def patrol(self):
        if not self.enabled:
            return []
        self.findings = []
        self._stuck_lanes()
        self._failure_storms()
        return list(self.findings)

    def _finding(self, kind, text, **extra):
        f = {"kind": kind, "text": text,
             "at": round(time.time(), 3)}
        f.update(extra)
        self.findings.append(f)
        self.ws.log("warden", finding=kind, text=text)
        return f

    def _act(self, action, **fields):
        self.actions.append({"action": action, "at": time.time(),
                             **fields})
        self.ws.log("warden-act", action=action, **fields)

    # ---- finding: a lane whose job outlived its own ceiling ----

    def _stuck_lanes(self):
        now = time.time()
        for lane in self.ws.fleet.lanes:
            job = lane.job
            if not job:
                continue
            ceiling = job.get("_ceiling_s", 0) * 2 + 30
            if now - float(job.get("_started", now)) > ceiling:
                self._finding("stuck", f"lane {lane.name} stuck on "
                              f"{job['id']}", job=job["id"])
                try:
                    self.hv_stop(lane)
                    self._act("stop_guest", lane=lane.name,
                              job=job["id"])
                except AtlasError as exc:
                    self._act("stop_failed", lane=lane.name,
                              error=str(exc))
                attempts = int(job.get("attempts", 0))
                if attempts >= int(job.get("max_attempts", 1)):
                    self.ws.finalize(job, ok=False,
                                     error="warden: stuck build "
                                           "finalized")
                    lane.release(False, "stuck")
                else:
                    job["attempts"] = attempts + 1
                    self.ws.requeue(job)
                    lane.release(False, "requeued by warden")

    def hv_stop(self, lane):
        if lane.guest:
            lane.hv.stop(lane.guest)

    # ---- finding: a blueprint failing far more than it succeeds ----

    def _failure_storms(self):
        now = time.time()
        stats = {}
        for job in list(self.ws.history)[-50:]:
            bp = job.get("blueprint")
            s = stats.setdefault(bp, {"ok": 0, "bad": 0})
            s["ok" if job.get("ok") else "bad"] += 1
        for bp, s in stats.items():
            total = s["ok"] + s["bad"]
            if total >= 3 and s["bad"] / total >= 0.8:
                until = now + self.ws.quarantine_seconds
                self._quarantined[bp] = max(
                    self._quarantined.get(bp, 0), until)
                self._finding("storm", f"blueprint '{bp}' failing "
                              f"{s['bad']}/{total}; quarantined",
                              blueprint=bp)
                self._act("quarantine_blueprint", blueprint=bp)

    def blueprint_available(self, bp):
        until = self._quarantined.get(bp)
        if until is None:
            return True
        if time.time() >= until:
            del self._quarantined[bp]
            self._act("revive_blueprint", blueprint=bp)
            return True
        return False
