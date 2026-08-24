"""FORSETI - push-lane arbitration for Olympos.

Named for the judge of the gods: exactly one writer may hold the lane.

Built on the same filesystem-lock discipline as ratatosk (O_CREAT|
O_EXCL spinlocks with stale takeover), but self-contained so it can
guard ANY serialised operation - today the canonical use is the git
push lane that two parallel sessions once raced to destruction:

    python -m forseti run -- python doctor.py --ci
    python -m forseti status

Lock files carry holder metadata (pid, ts, note) and live under
``<root>/data/post/locks/`` next to ratatosk's own locks.
"""

import json
import os
import time


def default_root():
    env = os.environ.get("RATATOSK_ROOT")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "data", "post")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class LaneLock:
    """Exclusive, crash-tolerant, stale-reclaiming named lock."""

    def __init__(self, name="push-main", root=None, stale_s=60.0,
                 note=""):
        self.name = str(name)
        self.root = root or default_root()
        self.stale_s = float(stale_s)
        self.note = str(note)
        self.path = os.path.join(self.root, "data", "post", "locks",
                                 f"{self.name}.lock")
        self._held_pid = None

    # -- helpers ----------------------------------------------------
    def _holder(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _is_stale(self):
        try:
            age = time.time() - os.path.getmtime(self.path)
            return age > self.stale_s
        except OSError:
            return True

    # -- api --------------------------------------------------------
    def acquire(self, timeout=10.0, sleep_s=0.05):
        """Block up to ``timeout`` seconds. True on acquisition."""
        deadline = time.monotonic() + max(0.0, timeout)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        while True:
            existed = os.path.exists(self.path)
            if existed and self._is_stale():
                try:
                    os.unlink(self.path)  # reclaim stale lane
                    existed = False
                except OSError:
                    pass
            if not existed:
                try:
                    fd = os.open(self.path,
                                 os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, json.dumps({
                        "pid": os.getpid(), "ts": _now(),
                        "note": self.note,
                    }, separators=(",", ":")).encode())
                    os.close(fd)
                    self._held_pid = os.getpid()
                    return True
                except FileExistsError:
                    pass
                except OSError:
                    pass  # Windows delete-pending race: retry
            if time.monotonic() >= deadline:
                return False
            time.sleep(sleep_s)

    def release(self):
        holder = self._holder()
        if holder and holder.get("pid") != os.getpid():
            return False  # never release someone else's lane
        try:
            os.unlink(self.path)
            self._held_pid = None
            return True
        except OSError:
            return False

    def held_by_other(self):
        h = self._holder()
        if not h:
            return None
        if h.get("pid") == os.getpid():
            return None
        age = None
        try:
            age = round(time.time() - os.path.getmtime(self.path), 1)
        except OSError:
            pass
        return {"pid": h.get("pid"), "ts": h.get("ts"),
                "note": h.get("note", ""), "age_s": age}

    def __enter__(self):
        if not self.acquire():
            other = self.held_by_other()
            raise RuntimeError(f"lane '{self.name}' busy: {other}")
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def status(name="push-main", root=None):
    """Report lane occupancy as a plain dict."""
    lock = LaneLock(name=name, root=root)
    holder = lock._holder()
    if not holder or lock._is_stale():
        return {"name": name, "free": True}
    return {"name": name, "free": False, **holder}
