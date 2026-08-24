"""DAEDALUS workshop - the full build pipeline over its subfleet.

Flow: spec -> schema gate -> lane dispatch -> weave (templates +
injected faults) -> gate run inside the ATLAS guest -> fix pass on
failure (faults restored to canonical) -> retry up to ceiling ->
seal artifact copy or quarantine. Every step audited; rules engine
may add retries/headroom per VULCAN-style policy.
"""

import hashlib
import hmac
import json
import sys
import os
import shutil
import threading
import time
import uuid
from collections import deque

from atlas.kernel import AtlasError
from daedalus import blueprints, content, rules as rig
from daedalus.fleet import SubFleet
from daedalus.warden import Warden

try:
    import ratatosk
except ImportError:                 # pragma: no cover
    ratatosk = None


class BuildError(Exception):
    pass


def _now():
    return time.time()


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _slug(s):
    return "".join(c if (c.isalnum() or c in "-_") else "_"
                   for c in str(s))[:40] or "job"


class Workshop:
    def __init__(self, hypervisor=None, lanes=None):
        from atlas.kernel import Hypervisor
        self.hv = hypervisor or Hypervisor()
        self.fleet = SubFleet(lanes or content.MAX_CONCURRENT_BUILDS,
                              self.hv)
        self.warden = Warden(self)
        self.queue = deque()
        self._wake = threading.Event()   # fluid: submit nudges the pump
        self.history = deque(maxlen=content.EVENTS_MAX)
        self.jobs = {}             # id -> job dict (live)
        self.quarantine_seconds = 120.0
        self.audit = _Chain(content.AUDIT_PATH)
        self._lock = threading.Lock()

    # ------------------------------------------------------------- audit --

    def log(self, kind, **fields):
        return self.audit.append({"t": round(_now(), 3), "ts": _iso(),
                                  "kind": kind, **fields})

    # ------------------------------------------------------------ intake --

    def submit(self, spec):
        issues = rig.validate_spec(spec, blueprints.blueprint_names())
        if issues:
            hard = [i for i in issues if i.startswith("error")]
            if hard:
                raise BuildError("spec refused: " + "; ".join(hard[:3]))
        bp = spec["blueprint"]
        if not self.warden.blueprint_available(bp):
            raise BuildError(f"blueprint '{bp}' is quarantined by "
                             "the warden; try again later")
        jid = f"{_slug(spec.get('name') or bp)}-{uuid.uuid4().hex[:6]}"
        attempts_cap = min(
            int(spec.get("attempts", content.BUILD_ATTEMPTS)),
            content.BUILD_ATTEMPTS)
        job = {"id": jid, "blueprint": bp,
               "faults": list(spec.get("faults", [])),
               "params": dict(spec.get("params", {})),
               "attempts": 0,
               "max_attempts": max(1, attempts_cap),
               "_ceiling_s": content.EXEC_TIMEOUT_S,
               "_started": _now(), "state": "queued"}
        with self._lock:
            if sum(1 for j in self.jobs.values()
                   if j["state"] != "done") >= \
                    content.MAX_CONCURRENT_BUILDS * 2:
                raise BuildError("workshop backlog full")
            self.jobs[jid] = job
        self.queue.append(job)
        self._wake.set()                 # fluid: wake the pump now
        self.log("submit", job=jid, blueprint=bp)
        return dict(job)

    # ------------------------------------------------------------ weaving --

    @staticmethod
    def weave(bp_name, dest_dir, faults=(), params=None):
        """Materialize blueprint files; inject named faults; substitute
        {{PARAM}} placeholders (blueprint defaults first, spec params
        override). Returns the file list. Faults make the gate fail ON
        PURPOSE until the repair pass restores canonical text."""
        bp = blueprints.BLUEPRINTS[bp_name]
        merged = dict(bp.get("params", {}))
        for k, v in (params or {}).items():
            merged[str(k)] = v
        woven = []
        for fname, text in bp["files"].items():
            for fault_name in faults:
                fault = bp["faults"].get(fault_name)
                if fault and fault[0] == fname:
                    text = text.replace(fault[1], fault[2])
            for key, val in merged.items():
                text = text.replace("{{" + key + "}}", str(val))
            path = os.path.join(dest_dir, fname)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            woven.append(fname)
        return woven

    # ------------------------------------------------------------ build --

    def build_next(self):
        """One dispatch+run cycle; returns the finished result or None
        when the queue is empty / fleet busy."""
        if not self.queue:
            return None
        lane = self.fleet.acquire()
        if lane is None:
            return None
        job = self.queue.popleft()
        if job["id"] not in self.jobs:
            return None
        lane.take(job)
        try:
            result = self._attempt_on_lane(lane, job)
        except AtlasError as exc:
            self.finalize(job, ok=False, error=f"atlas: {exc}")
            lane.release(False, str(exc), heal=True)
            return {"id": job["id"], "ok": False, "error": str(exc)}
        return result

    def _attempt_on_lane(self, lane, job):
        bp = job["blueprint"]
        g = self.hv.get(lane.guest)
        ws_root = os.path.join(g.workspace, "build")
        shutil.rmtree(ws_root, ignore_errors=True)
        os.makedirs(ws_root, exist_ok=True)
        job["_guest_ws"] = ws_root

        faults = list(job.get("faults", []))
        self.weave(bp, ws_root, faults=faults,
                   params=job.get("params"))
        lane.state = "gating"
        gate = [sys.executable] + \
            list(blueprints.BLUEPRINTS[bp]["gate"])[1:]
        r = self.hv.exec(lane.guest, gate,
                         timeout_s=content.GATE_TIMEOUT_S,
                         cwd=os.path.join("build"))
        job["attempts"] += 1

        culprits, repair_mode = None, None
        if not r["ok"] and faults:
            # REPAIR PASS: instead of blindly restoring everything,
            # isolate the culprit - restore one suspect at a time and
            # re-gate. A single restoration that turns the gate green
            # is the culprit, with evidence; innocent suspects stay
            # active in the sealed artifact. Falls back to restoring
            # all faults when no single one explains the failure
            # (multi-fault interaction).
            self.log("repair-start", job=job["id"],
                     attempt=job["attempts"], suspects=list(faults))
            culprit = None
            regates = 0
            for f in list(faults):
                if regates >= content.REPAIR_REGATES_MAX:
                    break
                trial = [x for x in faults if x != f]
                self.weave(bp, ws_root, faults=trial,
                           params=job.get("params"))
                r = self.hv.exec(lane.guest, gate,
                                 timeout_s=content.GATE_TIMEOUT_S,
                                 cwd="build")
                job["attempts"] += 1
                regates += 1
                if r["ok"]:
                    culprit = f
                    break
            if culprit is not None:
                repair_mode = "isolated"
                culprits = [culprit]
                remaining = [x for x in faults if x != culprit]
                self.log("repair-isolated", job=job["id"],
                         culprit=culprit, innocent=remaining)
                self._bump_repair_stats(bp, culprit, fixed=True)
            else:
                repair_mode = "restore-all"
                culprits = list(faults)
                self.weave(bp, ws_root, faults=(),
                           params=job.get("params"))
                r = self.hv.exec(lane.guest, gate,
                                 timeout_s=content.GATE_TIMEOUT_S,
                                 cwd="build")
                job["attempts"] += 1
                for f in faults:
                    self._bump_repair_stats(bp, f, fixed=False)

        ok = bool(r["ok"])
        if ok:
            sha = self._seal(bp, ws_root)
            result = dict(r, id=job["id"], blueprint=bp, ok=True,
                          attempts=job["attempts"],
                          fixed=bool(culprits) or repair_mode == "restore-all",
                          **({"culprit": culprits[0]}
                             if repair_mode == "isolated" else {}),
                          artifact_sha256=sha)
            self.finalize(job, ok=True, result=result)
        elif job["attempts"] < int(job["max_attempts"]) \
                and not culprits:
            job["next_epoch"] = _now() + 1
            self.requeue(job)
            lane.release(False, r.get("stderr", "")[-200:])
            return {"id": job["id"], "ok": False,
                    "retrying": True, "stderr": r["stderr"][-200:]}
        else:
            result = dict(r, id=job["id"], blueprint=bp, ok=False,
                          attempts=job["attempts"])
            self.finalize(job, ok=False, result=result)
        lane.release(ok, None if ok else "gate failed")
        return result

    def requeue(self, job):
        job["state"] = "queued"
        job["_started"] = _now()
        self.queue.appendleft(job)

    # ------------------------------------------------------- fluidity --

    def drain_parallel(self, max_jobs=None):
        """Weave up to max_jobs at once - one thread per lane.

        This is what the fleet is FOR: sequential drains leave N-1
        lanes idle. Each thread owns its lane exclusively; shared
        mutations (history chain, jobs dict) stay inside their locks.
        """
        cap = max(1, int(max_jobs or content.MAX_CONCURRENT_BUILDS))
        done = []
        threads = []
        while len(threads) < cap and self.queue:
            lane = self.fleet.acquire()
            if lane is None:
                break                    # every lane busy / cooling
            job = self.queue.popleft()
            if job["id"] not in self.jobs:
                continue
            lane.take(job)
            t = threading.Thread(target=self._run_on_lane,
                                 args=(lane, job, done),
                                 name=f"weave-{lane.name}",
                                 daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        return {"drained": len(done), "results": done}

    def _run_on_lane(self, lane, job, done):
        try:
            done.append(self._attempt_on_lane(lane, job))
        except AtlasError as exc:
            # structural guest sickness: finalize, then let the lane
            # rebuild its own world instead of dying with it
            self.finalize(job, ok=False, error=f"atlas: {exc}")
            lane.release(False, str(exc), heal=True)
            done.append({"id": job["id"], "ok": False,
                         "error": str(exc)})

    def pump_start(self):
        """Fluid mode: a background weaver keeps lanes saturated so
        builds flow without anyone calling build_next by hand."""
        pump = getattr(self, "_pump", None)
        if pump is not None and pump.is_alive():
            return False
        self._pump_stop = threading.Event()

        def _loop():
            while not self._pump_stop.wait(content.PUMP_IDLE_WAIT_S):
                worked = False
                while True:
                    r = self.build_next()
                    if r is None:
                        break
                    worked = True
                if worked:
                    self._wake.set()     # immediately look for more

        self._pump = threading.Thread(target=_loop,
                                      name="daedalus-pump",
                                      daemon=True)
        self._pump.start()
        self.log("pump", state="start")
        return True

    def pump_stop(self):
        ev = getattr(self, "_pump_stop", None)
        if ev is None:
            return False
        ev.set()
        pump = getattr(self, "_pump", None)
        if pump is not None:
            pump.join(timeout=2)
        self._pump = None
        self.log("pump", state="stop")
        return True

    def pump_running(self):
        pump = getattr(self, "_pump", None)
        return bool(pump is not None and pump.is_alive())

    def finalize(self, job, ok, error=None, result=None):
        job["state"] = "done"
        rec = {"id": job["id"], "blueprint": job["blueprint"],
               "ok": ok, "attempts": job.get("attempts"),
               "ts": _iso(), **({"error": error} if error else {}),
               **({"result": result} if result else {})}
        self.history.append(rec)
        self.log("build-done", job=job["id"], ok=ok)
        if ratatosk is not None:
            try:
                ratatosk.publish(content.ORGAN,
                                 {"ok": ok, "id": job["id"],
                                  "blueprint": job["blueprint"]},
                                 frm=content.ORGAN,
                                 kind="build" if ok else "build-failed")
            except Exception:
                pass
        return rec

    def _seal(self, bp_name, src_dir):
        """Copy the woven tree into artifacts/ and hash it."""
        out = os.path.join(content.ARTIFACTS_DIR,
                           f"{bp_name}-{uuid.uuid4().hex[:8]}")
        shutil.copytree(src_dir, out)
        sha = hashlib.sha256()
        for root, _d, files in os.walk(out):
            for f in sorted(files):
                with open(os.path.join(root, f), "rb") as fh:
                    sha.update(fh.read())
        return sha.hexdigest()

    # --------------------------------------------------------- reporting --

    def status(self):
        chain_ok, entries, bad = self.audit.verify()
        return {"daedalus": True, "version": content.VERSION,
                "queued": len(self.queue),
                "lanes_busy": self.fleet.busy_count(),
                "lanes": len(self.fleet.lanes),
                "history_ok": sum(1 for h in self.history if h["ok"]),
                "history_bad": sum(1 for h in self.history
                                   if not h["ok"]),
                "repair_stats": self._load_repair_stats(),
                "audit": {"entries": entries, "ok": chain_ok,
                          "first_bad": bad},
                "warden": {"enabled": self.warden.enabled,
                           "findings": len(self.warden.findings)}}

    @staticmethod
    def _load_repair_stats():
        try:
            with open(content.REPAIR_STATS_PATH,
                      encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _bump_repair_stats(self, bp_name, fault, fixed):
        """Atomic per-fault repair telemetry: which injected faults the
        workshop has seen, and how often isolation repaired them.
        Best-effort - telemetry must never fail a build."""
        try:
            os.makedirs(content.DATA_DIR, exist_ok=True)
            path = content.REPAIR_STATS_PATH
            try:
                doc = json.load(open(path, encoding="utf-8"))
            except (OSError, ValueError):
                doc = {}
            slot = (doc.setdefault(bp_name, {})
                        .setdefault(fault, {"seen": 0, "repaired": 0}))
            slot["seen"] += 1
            if fixed:
                slot["repaired"] += 1
            tmp = path + f".{uuid.uuid4().hex[:6]}.tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(doc, fh, indent=1, sort_keys=True)
            os.replace(tmp, path)
        except OSError:
            pass


class _Chain:
    """Hash-chained audit trail (rule 16) - same contract as zeus."""

    def __init__(self, path):
        self.path = path
        self.head = self._tail(path)
        self._lock = threading.Lock()

    @staticmethod
    def _canonical(entry):
        body = {k: v for k, v in entry.items() if k != "sha"}
        return json.dumps(body, sort_keys=True, separators=(",", ":"),
                          default=str)

    @staticmethod
    def _tail(path):
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 4096))
                tail = fh.read().decode("utf-8", errors="replace")
            last = [ln for ln in tail.splitlines() if ln.strip()][-1]
            return json.loads(last).get("sha", "genesis")
        except (OSError, ValueError, IndexError):
            return "genesis"

    def append(self, entry):
        with self._lock:
            entry["prev"] = self.head
            digest = hashlib.sha256(self._canonical(entry)
                                    .encode("utf-8")).hexdigest()
            entry["sha"] = digest
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                if (os.path.getsize(self.path)
                        if os.path.exists(self.path) else 0) \
                        > content.AUDIT_MAX_BYTES:
                    os.replace(self.path, self.path + ".1")
                    entry["prev"] = "genesis"
                    digest = hashlib.sha256(self._canonical(entry)
                                            .encode("utf-8")
                                            ).hexdigest()
                    entry["sha"] = digest
                with open(self.path, "a", encoding="utf-8",
                          newline="\n") as fh:
                    fh.write(json.dumps(entry, sort_keys=True,
                                        separators=(",", ":"),
                                        default=str) + "\n")
                self.head = digest
            except OSError:
                pass
            return digest

    def verify(self):
        ok, count, first_bad = True, 0, None
        prev = "genesis"
        try:
            with open(self.path, encoding="utf-8") as fh:
                for seq, ln in enumerate(
                        (l for l in fh if l.strip()), 1):
                    count = seq
                    try:
                        entry = json.loads(ln)
                        recomputed = hashlib.sha256(
                            self._canonical(entry)
                            .encode("utf-8")).hexdigest()
                        good = (entry.get("prev") == prev
                                and hmac.compare_digest(
                                    entry.get("sha", ""), recomputed))
                    except ValueError:
                        ok = False
                        first_bad = first_bad or seq
                        continue
                    if not good:
                        ok = False
                        first_bad = first_bad or seq
                    prev = entry.get("sha", prev)
        except OSError:
            return True, 0, None
        return ok, count, first_bad

