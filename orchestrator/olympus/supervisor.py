import os
import random
import threading
import time

from . import jobobject
from .logging_setup import get_logger, log_path


class Supervisor(threading.Thread):
    def __init__(self, spec, job_handle):
        super().__init__(daemon=True, name=f"sup-{spec['name']}")
        self.spec = spec
        self.job_handle = job_handle
        self.log = get_logger(spec["name"])
        self.name_ = spec["name"]
        self.stop_event = threading.Event()
        self.resume_event = threading.Event()
        self.lock = threading.Lock()
        self.desired = "run"
        self.state = "STARTING"
        self.pid = None
        self.started_at = None
        self.restarts = 0
        self.consecutive_crashes = 0
        self.last_exit = None
        self.assigned_job = True
        self.pidfile = log_path(f"{spec['name']}.pid")
        self.external_conflict = None

    def _check_external_conflict(self):
        try:
            with open(self.pidfile) as f:
                old = int(f.read().strip())
        except (FileNotFoundError, ValueError):
            self.external_conflict = False
            return
        if old != os.getpid() and jobobject.pid_alive(old):
            if self.external_conflict is not True:
                self.log.warning(
                    "external instance alive pid=%d; deferring", old
                )
            self.external_conflict = True
            return
        if self.external_conflict is True:
            self.log.info("external instance gone; taking over")
        self.external_conflict = False

    def _set(self, state):
        with self.lock:
            self.state = state

    def snapshot(self):
        with self.lock:
            return {
                "type": "singleton",
                "state": self.state,
                "pid": self.pid,
                "started": self.started_at,
                "last_exit": self.last_exit,
                "restarts": self.restarts,
                "consecutive_crashes": self.consecutive_crashes,
                "job_assigned": self.assigned_job,
            }

    def request_stop(self):
        with self.lock:
            self.desired = "stopped"
        self.stop_event.set()

    def request_start(self):
        with self.lock:
            self.desired = "run"
            self.consecutive_crashes = 0
        self.stop_event.clear()
        self.resume_event.set()

    def run(self):
        base = self.spec.get("cooldown", 5)
        while True:
            if self.desired == "stopped":
                self._set("STOPPED")
                with open(self.pidfile, "w") as f:
                    f.write(str(os.getpid()))
                self.resume_event.wait()
                self.resume_event.clear()
                self._set("STARTING")
                continue
            self._check_external_conflict()
            if self.external_conflict:
                self._set("CONFLICT")
                self.stop_event.wait(60)
                continue
            try:
                hp, pid, assigned = jobobject.spawn(
                    self.job_handle, self.spec["args"], self.spec["cwd"],
                    log_path(self.name_),
                )
                with self.lock:
                    self.assigned_job = assigned
            except OSError as e:
                self.log.error("spawn failed: %s", e)
                self._set("FAILED")
                self.consecutive_crashes += 1
                self.stop_event.wait(300)
                continue
            with self.lock:
                self.pid = pid
                self.started_at = time.time()
                self.state = "RUNNING"
            self.log.info(
                "started pid=%d job_assigned=%s", pid, bool(assigned)
            )
            exited_naturally = True
            stable_since = time.monotonic()
            while not self.stop_event.is_set():
                if not jobobject.is_alive(hp):
                    break
                if (
                    self.consecutive_crashes
                    and time.monotonic() - stable_since > 600
                ):
                    with self.lock:
                        self.consecutive_crashes = 0
                    self.log.info("stable 600s; crash counter reset")
                time.sleep(1)
            if self.stop_event.is_set():
                jobobject.terminate(hp)
                jobobject.close_handle(hp)
                with self.lock:
                    self.pid = None
                self.log.info("stopped by request")
                continue
            code = jobobject.exit_code(hp)
            jobobject.close_handle(hp)
            with self.lock:
                self.pid = None
                self.last_exit = code
                self.restarts += 1
                self.consecutive_crashes += 1
                cc = self.consecutive_crashes
            if cc >= 5:
                self._set("FAILED")
                delay = 3600
                self.log.error(
                    "exit code %s; circuit breaker OPEN, retry in %ss", code, delay
                )
            else:
                self._set("BACKOFF")
                delay = min(300, base * (2 ** (cc - 1))) + random.uniform(0, 5)
                self.log.warning(
                    "exit code %s (%d consecutive); restart in %.0fs",
                    code, cc, delay,
                )
            self.stop_event.wait(delay)

    def stop_sync(self, timeout=15):
        self.request_stop()
        for _ in range(timeout * 10):
            if self.snapshot()["state"] == "STOPPED":
                return True
            time.sleep(0.1)
        return False
