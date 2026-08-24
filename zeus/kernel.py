"""ZEUS kernel - the protection core.

One patrol tick walks every subsystem through a circuit breaker:
the sentinel watches processes, the oracle eyes filesystem churn and
the aegis re-verifies file integrity on its slower cadence. Findings
are escalated per policy, enforcement always goes through the bolt,
and every event lands in an append-only JSONL audit trail that
rotates before it can grow unbounded. A subsystem that fails
repeatedly trips its breaker and is auto-revived later - ZEUS must
never let one sick probe take the whole kernel down.
"""

import contextlib
import json
import os
import time
from collections import deque

import content
import aegis as aegis_mod
import bolt as bolt_mod
import oracle as oracle_mod
import sentinel as sentinel_mod

try:                                # the post office is optional glue
    import ratatosk
except ImportError:                 # pragma: no cover
    ratatosk = None

try:                                # NORN pulse: SLO-paced patrols
    from norn.pulse import Pulse
except ImportError:                 # pragma: no cover
    Pulse = None


class Breaker:
    """Circuit breaker around one subsystem patrol."""

    def __init__(self, name):
        self.name = name
        self.fails = 0
        self.tripped = False
        self.cool_ticks_left = 0

    def run(self, fn, kernel, *args):
        if self.tripped:
            self.cool_ticks_left -= 1
            if self.cool_ticks_left <= 0:
                self._revive(kernel)
            return None
        try:
            result = fn(*args)
        except Exception as exc:                 # noqa: BLE001 - breaker job
            self.fails += 1
            if self.fails >= content.SUBSYSTEM_FAIL_LIMIT:
                self._trip(kernel, repr(exc))
            return None
        self.fails = 0
        return result

    def _trip(self, kernel, detail):
        self.tripped = True
        self.cool_ticks_left = content.SUBSYSTEM_REVIVE_TICKS
        kernel.log_event("breaker", "warn",
                         f"{self.name} tripped after "
                         f"{self.fails} failures ({detail})")

    def _revive(self, kernel):
        self.tripped = False
        self.fails = 0
        kernel.log_event("breaker", "info",
                         f"{self.name} revived for retry")

    def snapshot(self):
        return {"tripped": self.tripped, "fails": self.fails,
                "cool_ticks_left": max(0, self.cool_ticks_left)}


_PATH_FIELDS = ("WORKSPACE", "DATA_DIR", "QUARANTINE_DIR",
                "AUDIT_PATH", "BASELINE_PATH")


@contextlib.contextmanager
def sandbox(workspace, data_dir=None):
    """Point ZEUS at a scratch root; restores content paths on exit.
    The Ratatosk post root is redirected into the sandbox too, so
    verify runs never write the live network."""
    saved = {f: getattr(content, f) for f in _PATH_FIELDS}
    saved_post_env = os.environ.get("RATATOSK_ROOT")
    data = data_dir or os.path.join(workspace, "zeus-sandbox")
    try:
        content.WORKSPACE = workspace
        content.DATA_DIR = data
        content.QUARANTINE_DIR = os.path.join(data, "quarantine")
        content.AUDIT_PATH = os.path.join(data, "audit.jsonl")
        content.BASELINE_PATH = os.path.join(data, "baseline.json")
        os.environ["RATATOSK_ROOT"] = os.path.join(data, "post")
        os.makedirs(data, exist_ok=True)
        yield Kernel()
    finally:
        for f, val in saved.items():
            setattr(content, f, val)
        if saved_post_env is None:
            os.environ.pop("RATATOSK_ROOT", None)
        else:
            os.environ["RATATOSK_ROOT"] = saved_post_env


class Kernel:
    def __init__(self):
        self.aegis = aegis_mod.Aegis()
        self.oracle = oracle_mod.Oracle()
        self.quarantine = bolt_mod.Quarantine()
        self.sentinel = sentinel_mod.Sentinel()
        self.breakers = {name: Breaker(name)
                         for name in ("sentinel", "oracle", "integrity")}
        self.events = deque(maxlen=content.EVENTS_MAX)
        self.repairs = deque(maxlen=content.REPAIRS_MAX)
        self.tick_count = 0
        self.started_at = time.time()
        self.last_report = {}
        os.makedirs(content.DATA_DIR, exist_ok=True)
        # NORN pulse: the patrol cycle is an organ with a latency SLO;
        # breach streaks quarantine it briefly instead of letting a
        # wedged probe spin. Vitals ride the status verb.
        self.pulse = None
        if Pulse is not None:
            self.pulse = Pulse(name="zeus",
                               beat_s=content.PATROL_SECONDS_REAL)
            self.pulse.add_organ(
                "patrol", self._patrol_body,
                slo_max_ms=content.PATROL_SECONDS_REAL * 750.0,
                slo_max_late=4, revive_after=2)

    # ---------- audit ----------

    def log_event(self, kind, severity, text, **extra):
        entry = {"t": round(time.time(), 3),
                 "tick": self.tick_count,
                 "kind": kind, "severity": severity, "text": text}
        entry.update(extra)
        self.events.append(entry)
        self._audit(entry)
        return entry

    def record_repair(self, category, text, **extra):
        n = (self.repairs[-1]["n"] + 1) if self.repairs else 1
        rec = {"n": n, "category": category, "text": text}
        rec.update(extra)
        self.repairs.append(rec)
        self.log_event("repair", "info", f"[{category}] {text}",
                       repair=n)
        return rec

    def _audit(self, entry):
        line = json.dumps(entry, separators=(",", ":"),
                          default=str) + "\n"
        try:
            size = os.path.getsize(content.AUDIT_PATH) \
                if os.path.exists(content.AUDIT_PATH) else 0
            if size > content.AUDIT_MAX_BYTES:
                os.replace(content.AUDIT_PATH,
                           content.AUDIT_PATH + ".1")
            with open(content.AUDIT_PATH, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass                    # auditing must never kill patrols
        if ratatosk is not None and \
                entry.get("severity") in ("warn", "critical"):
            try:                    # shout across the tree, never throw
                ratatosk.publish("zeus-events", entry, frm="zeus",
                                 kind=str(entry.get("kind", "event")))
            except Exception:
                pass

    def _heartbeat(self):
        if ratatosk is None:
            return
        try:
            ratatosk.beat("zeus",
                          note=f"tick {self.tick_count}, "
                               f"{len(self.last_report.get('findings', []))}"
                               f" findings")
        except Exception:
            pass

    # ---------- patrol ----------

    def tick(self):
        """One full protection cycle (pulse-paced); returns the report."""
        if self.pulse is None:
            return self._patrol_body()
        self.pulse.beat()
        return self.last_report

    def _patrol_body(self):
        self.tick_count += 1
        report = {"tick": self.tick_count, "at": time.time(),
                  "findings": []}

        s_finds, snap = (self.breakers["sentinel"].run(
            self.sentinel.patrol, self) or ([], {}))
        report["processes"] = len(snap)

        o_finds = self.breakers["oracle"].run(
            self.oracle.patrol, self) or []

        i_findings = []
        if self.aegis.has_baseline() and (
                self.tick_count == 1
                or self.tick_count % content.INTEGRITY_EVERY_TICKS == 0):
            verify = self.breakers["integrity"].run(
                self.aegis.verify, self) or None
            if verify and not verify["clean"]:
                i_findings.append({
                    "type": "tamper", "severity": "critical",
                    "modified": verify["modified"]["count"],
                    "added": verify["added"]["count"],
                    "missing": verify["missing"]["count"],
                    "paths": (verify["modified"]["paths"][:10]
                              + verify["added"]["paths"][:10]
                              + verify["missing"]["paths"][:10]),
                    "text": f"integrity drift: "
                            f"{verify['modified']['count']} modified, "
                            f"{verify['added']['count']} added, "
                            f"{verify['missing']['count']} missing",
                })

        findings = list(s_finds) + list(o_finds) + i_findings
        for f in findings:
            payload = {k: v for k, v in f.items()
                       if k not in ("type", "severity", "text", "entry")}
            self.log_event(f["type"], f["severity"], f["text"], **payload)
        report["findings"] = [
            {k: v for k, v in f.items() if k != "entry"}
            for f in findings]

        self._enforce(findings, snap)
        report["repairs_total"] = len(self.repairs)
        self.last_report = report
        self._heartbeat()
        return report

    def _enforce(self, findings, snap):
        for f in findings:
            if f.get("type") == "proc_death" \
                    and f.get("on_death") == "restart":
                res = self.sentinel.try_restart(f)
                if res:
                    verb = "restarted" if res["restarted"] \
                        else f"restart failed: {res.get('error')}"
                    self.record_repair("restart",
                                       f"{f['watch']}: {verb}")
            elif f.get("type") == "runaway" \
                    and f.get("action") == "bolt":
                try:
                    rec = bolt_mod.discharge(f["pid"], snap)
                    self.record_repair(
                        "bolt", f"{f.get('name') or f['pid']} bolted: "
                        f"{rec['detail']}", pid=f["pid"])
                except bolt_mod.BoltDenied as exc:
                    self.record_repair(
                        "bolt-refused", f"pid {f['pid']}: {exc}",
                        pid=f["pid"])
            elif f.get("type") == "churn_burst" and f.get("synthetic"):
                self.record_repair(
                    "churn", f"burst contained in {f['dir']} - "
                    f"watching; raise policy to quarantine to act")

    # ---------- reporting ----------

    def status(self):
        rep = {
            "zeus": True,
            "version": content.VERSION,
            "uptime_s": round(time.time() - self.started_at, 1),
            "ticks": self.tick_count,
            "baseline_files": len(self.aegis.baseline),
            "quarantined": len(self.quarantine.entries),
            "pinned_pids": sorted(self.sentinel.pinned),
            "watches": [w["name"] for w in self.sentinel.manifest],
            "breakers": {k: v.snapshot()
                         for k, v in self.breakers.items()},
            "last_findings": len(self.last_report.get("findings", [])),
        }
        if self.pulse is not None:
            rep["pulse"] = self.pulse.vitals()
        return rep

    def diagnose(self):
        rep = self.status()
        rep["events_recent"] = list(self.events)[-20:]
        rep["repairs"] = list(self.repairs)[-20:]
        rep["audit_path"] = content.AUDIT_PATH
        rep["audit_bytes"] = (os.path.getsize(content.AUDIT_PATH)
                              if os.path.exists(content.AUDIT_PATH)
                              else 0)
        return rep
