import ctypes
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from olympus import config, control, jobobject, logging_setup  # noqa: E402
from olympus import muster, scheduler as sched_mod, status  # noqa: E402
from olympus import supervisor as sup_mod  # noqa: E402

MUTEX_NAME = "OlympusOrchestratorSingleton"
ERROR_ALREADY_EXISTS = 183
EMERGENCY_DISABLE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "DISABLED_POPUP_STORM",
)


def acquire_single_instance():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW(None, False, MUTEX_NAME)
    return k32.GetLastError() != ERROR_ALREADY_EXISTS


class App:
    def __init__(self):
        self.log = logging_setup.setup()
        self.main_job = jobobject.new_job()
        self.supervisors = {
            s["name"]: sup_mod.Supervisor(s, self.main_job)
            for s in config.SINGLETON_JOBS
        }
        self.scheduler = sched_mod.Scheduler(config.ONESHOT_JOBS, self.main_job)
        self.shutdown_event = threading.Event()

    def start(self):
        for sup in self.supervisors.values():
            sup.start()
        self.scheduler.start()
        self.status_writer = status.StatusWriter(self.collect)
        self.status_writer.start()
        self.control_server = control.ControlServer(self.handle_command)
        self.control_server.start()
        self.log.info(
            "olympus orchestrator v%s up: %d singletons, %d oneshots, ctl %s:%d",
            config.VERSION,
            len(self.supervisors),
            len(self.scheduler.oneshots),
            config.CONTROL_HOST,
            config.CONTROL_PORT,
        )

    def collect(self):
        return {
            "singletons": {n: s.snapshot() for n, s in self.supervisors.items()},
            "oneshots": self.scheduler.snapshot(),
        }

    def handle_command(self, cmd, arg):
        if cmd == "status":
            return {"ok": True, "jobs": self.collect()}
        if cmd == "muster":
            text, ready = muster.run_muster(self.supervisors, self.scheduler)
            return {"ok": True, "ready": ready, "report": text}
        if cmd in ("start", "stop", "restart"):
            return self._job_control(cmd, arg)
        if cmd == "reload":
            return {"ok": False, "error": "restart orchestrator to apply config changes"}
        if cmd == "shutdown":
            self.log.warning("shutdown requested via control channel")
            self.request_shutdown()
            return {"ok": True, "note": "shutting down"}
        return {"ok": False, "error": f"unknown command: {cmd}"}

    def _job_control(self, cmd, name):
        if name in self.supervisors:
            sup = self.supervisors[name]
            if cmd == "stop":
                ok = sup.stop_sync()
                return {"ok": ok, "job": name, "state": sup.snapshot()["state"]}
            if cmd == "start":
                sup.request_start()
                time.sleep(1)
                return {"ok": True, "job": name, "state": sup.snapshot()["state"]}
            if cmd == "restart":
                sup.stop_sync()
                sup.request_start()
                time.sleep(1)
                return {"ok": True, "job": name, "state": sup.snapshot()["state"]}
        if name in self.scheduler.oneshots:
            j = self.scheduler.oneshots[name]
            j.next_run = time.time()
            return {"ok": True, "job": name, "next_run": "now"}
        return {"ok": False, "error": f"no such job: {name}"}

    def request_shutdown(self):
        self.shutdown_event.set()

    def shutdown(self):
        self.log.info("graceful shutdown: terminating fleet")
        try:
            self.control_server.request_stop()
        except Exception:
            pass
        self.status_writer.stop_event.set()
        self.scheduler.request_stop_all()
        names = list(self.supervisors)
        for n in reversed(names):
            try:
                self.supervisors[n].stop_sync(10)
            except Exception as e:
                self.log.error("stopping %s failed: %s", n, e)
        jobobject.close_job(self.main_job)
        self.log.info("job object closed; all children dead")

    def wait_forever(self):
        while not self.shutdown_event.wait(1):
            pass


def main():
    # Fail closed before creating the job object or spawning any worker. This
    # marker is the recovery circuit breaker for task/login process storms.
    if os.path.exists(EMERGENCY_DISABLE_FILE):
        return
    if not acquire_single_instance():
        sys.exit(0)
    app = App()
    app.start()
    try:
        app.wait_forever()
    finally:
        app.shutdown()


if __name__ == "__main__":
    main()
