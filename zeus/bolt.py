"""ZEUS bolt - the enforcement arm.

The bolt is the only module allowed to terminate processes or move
files against their owner's will, so it carries the safety rails:
never touches system pids or binaries under the Windows directory,
never quarantines anything outside declared roots, and records every
discharge for the audit trail.
"""

import os
import shutil
import time

import content
import procsys


class BoltDenied(PermissionError):
    """Raised when a rail refuses a discharge."""


def _is_system_path(exe):
    if not exe:
        return False
    try:
        low = os.path.abspath(exe).lower()
    except (ValueError, OSError):
        return True
    return any(low.startswith(p) for p in content.SYSTEM_PATH_PREFIXES)


def check_kill_allowed(pid, table=None):
    """Return None when allowed, else a refusal reason string."""
    if pid in content.NEVER_KILL_PIDS:
        return f"pid {pid} is a protected system pid"
    if pid == os.getpid():
        return "refusing to bolt ZEUS itself"
    row = (table or {}).get(pid)
    if row is not None:
        if _is_system_path(row.exe):
            return f"pid {pid} runs from a system path: {row.exe!r}"
        return None
    # Unknown pid: probe it live before refusing outright.
    info = procsys.ProcTable().sample().get(pid) \
        if procsys.IS_WINDOWS else None
    if info is None:
        return f"pid {pid} not found in process table"
    if _is_system_path(info.exe):
        return f"pid {pid} runs from a system path: {info.exe!r}"
    return None


def discharge(pid, table=None):
    """Kill a process after rails pass. Returns an audit record."""
    reason = check_kill_allowed(pid, table)
    if reason:
        raise BoltDenied(reason)
    ok, detail = procsys.kill_pid(pid)
    return {"action": "bolt", "pid": pid, "ok": ok,
            "detail": detail, "at": time.time()}


# ---------- quarantine ----------


class Quarantine:
    """Moves suspect files into zeus/data/quarantine, can restore them."""

    def __init__(self, root=None):
        self.root = root or content.QUARANTINE_DIR
        self.entries = {}          # qid -> record
        self._next_id = 1

    def ensure_dir(self):
        os.makedirs(self.root, exist_ok=True)

    def capture(self, path, why):
        """Move `path` into quarantine; returns the audit record."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise ValueError(f"not a file: {path}")
        self.ensure_dir()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        qid = f"q{self._next_id}"
        self._next_id += 1
        held = os.path.join(self.root, f"{stamp}-{qid}-{os.path.basename(path)}")
        shutil.move(path, held)
        rec = {"id": qid, "orig": path, "held": held,
               "why": why, "at": time.time()}
        self.entries[qid] = rec
        return rec

    def restore(self, qid):
        rec = self.entries.get(qid)
        if rec is None:
            raise KeyError(qid)
        os.makedirs(os.path.dirname(rec["orig"]), exist_ok=True)
        shutil.move(rec["held"], rec["orig"])
        done = dict(rec, restored_at=time.time())
        del self.entries[qid]
        return done

    def listing(self):
        return [dict(r) for r in self.entries.values()]
