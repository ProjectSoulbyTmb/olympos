import datetime
import threading
import time

from . import jobobject
from .logging_setup import get_logger, log_path


def _next_daily_seconds(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    now = datetime.datetime.now()
    tgt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if tgt <= now:
        tgt += datetime.timedelta(days=1)
    return max(1.0, (tgt - now).total_seconds())


class OneShot:
    def __init__(self, spec, job_handle):
        self.spec = spec
        self.job_handle = job_handle
        self.name_ = spec["name"]
        self.log = get_logger(spec["name"])
        self.lock = threading.Lock()
        self.proc = None
        self.runs = 0
        self.last_run = None
        self.last_exit = None
        self.last_duration = None
        self.started_monotonic = None
        if "daily" in spec:
            self.next_run = time.time() + _next_daily_seconds(spec["daily"])
        else:
            self.next_run = time.time()

    def snapshot(self):
        with self.lock:
            return {
                "type": "oneshot",
                "schedule": self.spec.get("daily") or f"every {self.spec['interval']}s",
                "busy": self.busy(),
                "runs": self.runs,
                "last_run": self.last_run,
                "last_exit": self.last_exit,
                "last_duration": self.last_duration,
                "next_run": self.next_run,
            }

    def busy(self):
        p = self.proc
        return bool(p) and jobobject.is_alive(p[0])

    def fire(self):
        if self.busy():
            return
        self.started_monotonic = time.monotonic()
        try:
            hp, pid, assigned = jobobject.spawn(
                self.job_handle, self.spec["args"], self.spec["cwd"],
                log_path(self.name_),
            )
        except OSError as e:
            self.log.error("spawn failed: %s", e)
            with self.lock:
                self.last_run = time.time()
                self.last_exit = -1
            if "daily" in self.spec:
                self.next_run = time.time() + _next_daily_seconds(self.spec["daily"])
            else:
                self.next_run = time.time() + self.spec["interval"]
            return
        with self.lock:
            self.proc = (hp, pid)
            self.runs += 1
            self.last_run = time.time()
        self.log.info("fired pid=%d", pid)
        step = (
            _next_daily_seconds(self.spec["daily"])
            if "daily" in self.spec
            else self.spec["interval"]
        )
        self.next_run = time.time() + step

    def reap(self):
        with self.lock:
            p = self.proc
            if not p or jobobject.is_alive(p[0]):
                if p and self.spec.get("timeout"):
                    if time.monotonic() - self.started_monotonic > self.spec["timeout"]:
                        self.log.error("timeout after %ss; killing pid=%d",
                                       self.spec["timeout"], p[1])
                        jobobject.terminate(p[0])
                        code = jobobject.exit_code(p[0])
                        jobobject.close_handle(p[0])
                        self._finish(code)
                return
            code = jobobject.exit_code(p[0])
            jobobject.close_handle(p[0])
            self._finish(code)

    def _finish(self, code):
        self.last_exit = code
        self.last_duration = time.monotonic() - self.started_monotonic
        self.proc = None
        lvl = "info" if code == 0 else "warning"
        getattr(self.log, lvl)("finished exit=%s in %.1fs", code, self.last_duration)


class Scheduler(threading.Thread):
    def __init__(self, specs, job_handle):
        super().__init__(daemon=True, name="scheduler")
        self.job_handle = job_handle
        self.oneshots = {s["name"]: OneShot(s, job_handle) for s in specs}
        self.stop_event = threading.Event()

    def snapshot(self):
        return {n: j.snapshot() for n, j in self.oneshots.items()}

    def request_stop_all(self, timeout=15):
        self.stop_event.set()
        deadline = time.monotonic() + timeout
        for j in self.oneshots.values():
            with j.lock:
                if j.proc:
                    remaining = int((deadline - time.monotonic()) * 1000)
                    jobobject.terminate(j.proc[0], max(1000, remaining))
                    jobobject.close_handle(j.proc[0])
                    j.proc = None

    def run(self):
        while not self.stop_event.is_set():
            for j in self.oneshots.values():
                j.reap()
                if self.stop_event.is_set():
                    break
                if time.time() >= j.next_run:
                    if j.busy():
                        j.log.warning("previous run still active; skipping cycle")
                        if "daily" in j.spec:
                            j.next_run = time.time() + 60
                        continue
                    j.fire()
            self.stop_event.wait(1)
