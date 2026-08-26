"""KRONOS kernel - sample, decide, hold, release, recover.

The governor watches physical RAM load. Sustained strain stops the
deferrable patrol tasks (content.MANAGED_TASKS); sustained calm starts
them again. Every transition is journaled to data/state.json - written
*before* the first stop, so a crash mid-hold still recovers on the
next boot - and logged to data/events.jsonl.
"""

import ctypes
import json
import os
import subprocess
import time

from . import content as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PS = "powershell.exe"

# Every child spawns windowless: a background governor must never
# flash consoles over the operator's shoulder (house convention).
SILENT = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def data_paths(root=None):
    """Journal + event-log locations under an organ data dir."""
    base = os.path.join(root or ROOT, "kronos", "data")
    return {"dir": base,
            "state": os.path.join(base, "state.json"),
            "events": os.path.join(base, "events.jsonl")}


# ------------------------------------------------------------ sampler

class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def ram_sample():
    """Physical RAM snapshot: load percentage + byte counts."""
    st = _MemoryStatusEx()
    st.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        raise OSError("GlobalMemoryStatusEx failed")
    return {"load_pct": int(st.dwMemoryLoad),
            "avail_bytes": int(st.ullAvailPhys),
            "total_bytes": int(st.ullTotalPhys)}


# ---------------------------------------------------------- controller

class TaskController:
    """Stops and starts scheduled tasks; dry-run touches nothing.

    Code law: any task whose name carries a forbidden marker (ZEUS)
    is refused at this layer, no matter what the manifest says - the
    governor may run elevated, so the veto travels with it.
    """

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.actions = []                     # [(verb, task)]
        self.refused = []                     # [(verb, task)]

    def _vet(self, verb, task):
        low = (task or "").lower()
        if any(m in low for m in C.FORBIDDEN_MARKERS):
            self.refused.append((verb, task))
            return False
        return True

    def stop(self, task):
        if not self._vet("stop", task):
            return False
        self.actions.append(("stop", task))
        if self.dry_run:
            return True
        return self._ps("Stop-ScheduledTask -TaskName '%s' "
                        "-ErrorAction SilentlyContinue" % task)

    def start(self, task):
        if not self._vet("start", task):
            return False
        self.actions.append(("start", task))
        if self.dry_run:
            return True
        return self._ps("Start-ScheduledTask -TaskName '%s' "
                        "-ErrorAction SilentlyContinue" % task)

    def query(self, task):
        """Task state string ('Running', 'Ready', ...) or None."""
        if self.dry_run:
            return "dry-run"
        proc = subprocess.run(
            [PS, "-NoProfile", "-NonInteractive", "-Command",
             "(Get-ScheduledTask -TaskName '%s' "
             "-ErrorAction SilentlyContinue).State" % task],
            capture_output=True, text=True, timeout=60, **SILENT)
        out = (proc.stdout or "").strip()
        return out or None

    @staticmethod
    def _ps(script):
        try:
            proc = subprocess.run(
                [PS, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=60,
                **SILENT)
        except subprocess.TimeoutExpired:
            return False
        return proc.returncode == 0


# ------------------------------------------------------------- journal

def _read_journal(paths):
    try:
        with open(paths["state"], encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class Governor:
    """The breathing regulator: watch RAM, hold patrols under strain,
    release them back when the machine has room again."""

    def __init__(self, controller=None, sampler=ram_sample, root=None):
        self.ctrl = controller or TaskController()
        self.sampler = sampler
        self.paths = data_paths(root)
        self.holding = False
        self.held = []
        self.over_streak = 0
        self.under_streak = 0

    # -- journaling ---------------------------------------------------

    def _write_journal(self, planned=None):
        os.makedirs(self.paths["dir"], exist_ok=True)
        row = {"holding": self.holding,
               "held": list(self.held),
               "planned": list(planned or []),
               "pid": os.getpid(),
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        tmp = self.paths["state"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(row, fh)
        os.replace(tmp, self.paths["state"])

    def _log(self, kind, **kw):
        os.makedirs(self.paths["dir"], exist_ok=True)
        row = dict(kind=kind,
                   ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
        row.update(kw)
        with open(self.paths["events"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    # -- lifecycle ----------------------------------------------------

    def recover(self):
        """Adopt a hold left behind by a crashed predecessor - but
        trust reality over paper: a claimed-held task found Running
        was never stopped (crash before the stop landed), so it is
        dropped from the hold rather than double-booked."""
        self._log("boot", pid=os.getpid())
        j = _read_journal(self.paths)
        if j and j.get("holding"):
            claimed = list(j.get("held") or [])
            if getattr(self.ctrl, "dry_run", False):
                verified = claimed          # nothing real to verify
                dropped = []
            else:
                verified, dropped = [], []
                for task in claimed:
                    state = self.ctrl.query(task)
                    if state in ("Ready", "Stopped"):
                        verified.append(task)
                    else:
                        dropped.append(task)
            self.holding = True
            self.held = verified
            self._log("adopt", held=list(verified),
                      dropped=dropped)
        return list(self.held)

    # -- decision core --------------------------------------------------

    def step(self, load_pct):
        """Feed one sample; act when a streak earns it."""
        if load_pct >= C.HOLD_PCT:
            self.over_streak += 1
            self.under_streak = 0
        elif load_pct < C.RELEASE_PCT:
            self.under_streak += 1
            self.over_streak = 0
        else:                       # deadband: neither strained nor calm
            self.over_streak = 0
            self.under_streak = 0

        if not self.holding and self.over_streak >= C.HOLD_SAMPLES:
            return self.do_hold(load_pct)
        if self.holding and self.under_streak >= C.RELEASE_SAMPLES:
            return self.do_release(load_pct)
        return {"action": "holding" if self.holding else "watch",
                "load": load_pct,
                "held": list(self.held)}

    def do_hold(self, load_pct=None):
        planned = list(C.MANAGED_TASKS)
        self.holding, self.held = True, []
        # journal intent BEFORE touching anything: a crash between the
        # write and the stops still leaves a recoverable trail.
        self._write_journal(planned=planned)
        stopped = []
        for task in planned:
            if self.ctrl.stop(task):
                stopped.append(task)
                self.held = list(stopped)
                self._write_journal(planned=planned)
        self._log("hold", load=load_pct,
                  held=list(stopped),
                  refused=[t for t in planned if t not in stopped])
        self.over_streak = 0
        return {"action": "hold",
                "load": load_pct,
                "held": list(stopped)}

    def do_release(self, load_pct=None):
        j = _read_journal(self.paths) or {}
        targets = self.held or list(j.get("held") or [])
        started, missed = [], []
        for task in targets:
            if self.ctrl.start(task):
                started.append(task)
            else:
                missed.append(task)
        self.holding, self.held = False, []
        self._write_journal()
        self._log("release", load=load_pct,
                  resumed=started, missed=missed)
        self.under_streak = 0
        return {"action": "release",
                "load": load_pct,
                "resumed": started,
                "missed": missed}

    # -- loops and reporting --------------------------------------------

    def run(self, interval=None, max_cycles=0):
        interval = float(interval or C.SAMPLE_S)
        self.recover()
        cycles = 0
        while True:
            try:
                s = self.sampler()
            except Exception as exc:          # noqa: BLE001 - keep breathing
                self._log("sample-error", error=str(exc))
                s = None
            if s is not None:
                row = self.step(s["load_pct"])
                if row["action"] in ("hold", "release"):
                    try:
                        print(json.dumps(row), flush=True)
                    except OSError:
                        pass          # scheduler gave us no stdout
            cycles += 1
            if max_cycles and cycles >= max_cycles:
                return cycles
            time.sleep(interval)

    def status(self):
        try:
            s = self.sampler()
        except Exception as exc:              # noqa: BLE001 - report, don't die
            s = {"error": str(exc)}
        j = _read_journal(self.paths) or {}
        return {"sample": s,
                "holding": self.holding,
                "held": list(self.held),
                "over_streak": self.over_streak,
                "under_streak": self.under_streak,
                "journal": j,
                "tasks": {t: self.ctrl.query(t)
                          for t in C.MANAGED_TASKS}}
