"""RATATOSK bus - mailboxes, topics, heartbeats over plain files.

Layout under the post root (default `<repo>/data/post/`):

    registry.json                  organ name -> meta
    seq/<organ>.seq                per-sender monotonic counters
    locks/<resource>.lock          O_CREAT|O_EXCL spinlocks, stale takeover
    <organ>/inbox/<seq>-<from>-<kind>-<token>.json   unread letters
    <organ>/seen/...               read letters (purged by cap)
    <organ>/heartbeat.json         last liveness stamp + note
    topics/<topic>.jsonl           broadcast journal, line number = seq
    cursors/<consumer>.<topic>     last consumed topic seq

Safety model:
- delivery is `os.replace` of a temp file in the destination dir, so a
  reader never observes a partial letter;
- per-sender sequence numbers give FIFO order and unique ids even with
  concurrent senders (allocation happens under an exclusive lock);
- corrupt letters are quarantined into seen/corrupt-* instead of
  blocking the queue;
- everything degrades silently when the filesystem says no.
"""

import contextlib
import json
import os
import tempfile
import time
import uuid

VERSION = 1

LOCK_STALE_S = 10.0
LOCK_RETRIES = 150
LOCK_SLEEP_S = 0.02


# ---------------------------------------------------------------- helpers

def _safe(name):
    """Filesystem-safe organ/topic slug."""
    return "".join(c if (c.isalnum() or c in "-_.") else "_"
                   for c in str(name))[:64] or "anon"


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def default_root():
    """Post root: $RATATOSK_ROOT or <repo>/data/post."""
    env = os.environ.get("RATATOSK_ROOT")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "data", "post")


def atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, separators=(",", ":"), default=str)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextlib.contextmanager
def _lock(path, stale_s=LOCK_STALE_S, retries=LOCK_RETRIES,
          sleep_s=LOCK_SLEEP_S):
    """Best-effort exclusive lockfile: stale locks are taken over; on
    exhaustion we yield False so callers can degrade instead of
    deadlock."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    acquired = False
    fd = None
    for _ in range(retries):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            acquired = True
            break
        except (FileExistsError, PermissionError):
            # PermissionError is the normal contended case on Windows:
            # while one holder is between close() and unlink(), the
            # entry is delete-pending and CREATE fails with EACCES
            # instead of EEXIST - so treat both as "retry".
            try:
                if time.time() - os.path.getmtime(path) > stale_s:
                    os.unlink(path)
                    continue
            except OSError:
                pass
            time.sleep(sleep_s)
        except OSError:
            break
    try:
        yield acquired
    finally:
        if acquired:
            for op in (lambda: os.close(fd), lambda: os.unlink(path)):
                try:
                    op()
                except OSError:
                    pass


@contextlib.contextmanager
def _strong_lock(path, timeout_s=30.0, stale_s=LOCK_STALE_S):
    """Mandatory exclusive lockfile for operations where an unlocked
    write would corrupt shared state (topic sequence density). Blocks
    up to timeout_s with backoff, takes over stale locks, and raises
    RuntimeError on exhaustion - callers decide to fail loudly."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.monotonic() + float(timeout_s)
    acquired = False
    fd = None
    delay = 0.004
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            acquired = True
            break
        except (FileExistsError, PermissionError):
            # see _lock: EACCES is a transient delete-pending race on
            # Windows, not a fatal condition
            if time.monotonic() >= deadline:
                raise RuntimeError(f"post lock busy: {path}")
            try:
                if time.time() - os.path.getmtime(path) > stale_s:
                    os.unlink(path)
                    continue
            except OSError:
                pass
            time.sleep(delay)
            delay = min(delay * 1.5, 0.05)
        except OSError as exc:
            raise RuntimeError(f"post lock unusable: {path}") from exc
    try:
        yield
    finally:
        if acquired:
            for op in (lambda: os.close(fd), lambda: os.unlink(path)):
                try:
                    op()
                except OSError:
                    pass


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- the Post

class Post:
    """One filesystem post office shared by every organ in the repo."""

    def __init__(self, root=None):
        self.root = root or default_root()

    # -- paths --

    def _dir(self, *parts):
        p = os.path.join(self.root, *map(str, parts))
        return p

    def _ensure_organ(self, name):
        inbox = self._dir(_safe(name), "inbox")
        seen = self._dir(_safe(name), "seen")
        os.makedirs(inbox, exist_ok=True)
        os.makedirs(seen, exist_ok=True)
        return inbox, seen

    # -- registry --

    def register(self, name, **meta):
        self._ensure_organ(name)
        reg_path = self._dir("registry.json")
        with _lock(self._dir("locks", "registry.lock")):
            try:
                reg = _read_json(reg_path)
            except (OSError, ValueError):
                reg = {}
            entry = reg.get(name) or {}
            entry.setdefault("registered", _now_iso())
            if meta:
                entry.update(meta)
            reg[name] = entry
            atomic_write_json(reg_path, reg)

    def organs(self):
        names = set()
        try:
            for n in os.listdir(self.root):
                if os.path.isdir(self._dir(n, "inbox")):
                    names.add(n)
        except OSError:
            pass
        try:
            names.update(_read_json(self._dir("registry.json")))
        except (OSError, ValueError):
            pass
        return sorted(names)

    # -- direct mail --

    def send(self, to, kind, payload, frm="cli"):
        """Deliver one letter to an organ's inbox. Returns the id."""
        inbox, _ = self._ensure_organ(to)
        frm = _safe(frm)
        seq = self._next_seq(frm)
        letter = {"v": VERSION,
                  "id": f"{frm}-{seq:012d}",
                  "from": frm, "to": _safe(to), "kind": _safe(kind),
                  "ts": _now_iso(), "epoch": round(time.time(), 3),
                  "payload": payload}
        fname = f"{seq:012d}-{frm}-{_safe(kind)}-{uuid.uuid4().hex[:8]}.json"
        atomic_write_json(os.path.join(inbox, fname), letter)
        return letter["id"]

    def _next_seq(self, frm):
        seq_dir = self._dir("seq")
        os.makedirs(seq_dir, exist_ok=True)
        p = os.path.join(seq_dir, f"{frm}.seq")
        try:
            with _strong_lock(p + ".lock", timeout_s=10.0):
                return self._bump_seq(p)
        except RuntimeError:
            return self._bump_seq(p)     # degraded: tokens keep ids unique

    @staticmethod
    def _bump_seq(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                n = int(fh.read().strip() or "0") + 1
        except (OSError, ValueError):
            n = 1
        tmp = p + f".{uuid.uuid4().hex[:6]}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(str(n))
        os.replace(tmp, p)
        return n

    def unread(self, name):
        try:
            return len([f for f in os.listdir(self._dir(_safe(name),
                                                        "inbox"))
                        if f.endswith(".json")])
        except OSError:
            return 0

    def peek(self, name, limit=200):
        """Read letters without marking them seen."""
        return self._drain(name, limit=limit, mark=False)

    def read(self, name, limit=200, mark=True):
        """Drain the inbox in FIFO order; mark moves letters to seen/."""
        return self._drain(name, limit=limit, mark=mark)

    def _drain(self, name, limit, mark):
        inbox = self._dir(_safe(name), "inbox")
        seen = self._dir(_safe(name), "seen")
        letters = []
        try:
            names = sorted(f for f in os.listdir(inbox)
                           if f.endswith(".json"))
        except OSError:
            return letters
        for fname in names:
            if len(letters) >= limit:
                break
            src = os.path.join(inbox, fname)
            try:
                letter = _read_json(src)
                if not isinstance(letter, dict) or "payload" not in letter:
                    raise ValueError("bad envelope")
            except (OSError, ValueError):
                if mark:
                    try:
                        os.replace(src, os.path.join(
                            seen, "corrupt-" + fname))
                    except OSError:
                        pass
                continue
            letters.append(letter)
            if mark:
                try:
                    os.replace(src, os.path.join(seen, fname))
                except OSError:
                    pass
        return letters

    # -- broadcast topics --

    def broadcast(self, topic, kind, payload, frm="cli"):
        """Append to topics/<topic>.jsonl under a mandatory lock;
        returns the dense, unique seq. Raises only if the lock is
        unwinnable - callers like publish() swallow that."""
        tpath = self._dir("topics", _safe(topic) + ".jsonl")
        os.makedirs(os.path.dirname(tpath), exist_ok=True)
        with _strong_lock(tpath + ".lock"):
            seq = _count_lines(tpath) + 1
            rec = {"v": VERSION, "topic": _safe(topic), "seq": seq,
                   "from": _safe(frm), "kind": _safe(kind),
                   "ts": _now_iso(), "epoch": round(time.time(), 3),
                   "payload": payload}
            with open(tpath, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, separators=(",", ":"),
                                    default=str) + "\n")
        return seq

    def tail(self, topic, n=20):
        lines = self._topic_lines(topic)
        out = []
        for line in lines[-int(n):]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def since(self, topic, consumer, limit=1000):
        """Cursor-based consume: only records newer than this
        consumer's cursor; advances the cursor."""
        cur_path = self._dir("cursors",
                             f"{_safe(consumer)}.{_safe(topic)}")
        try:
            with open(cur_path, "r", encoding="utf-8") as fh:
                start = int(fh.read().strip() or "0")
        except (OSError, ValueError):
            start = 0
        lines = self._topic_lines(topic)
        out = []
        for i, line in enumerate(lines, 1):
            if len(out) >= int(limit):
                break
            if i <= start:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        if out:
            last_seq = out[-1].get("seq", start)
            tmp = cur_path + f".{uuid.uuid4().hex[:6]}.tmp"
            try:
                os.makedirs(os.path.dirname(cur_path), exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(str(max(start, int(last_seq))))
                os.replace(tmp, cur_path)
            except OSError:
                pass
        return out

    def _topic_lines(self, topic):
        try:
            with open(self._dir("topics", _safe(topic) + ".jsonl"),
                      "r", encoding="utf-8") as fh:
                return [ln for ln in fh.read().splitlines() if ln.strip()]
        except OSError:
            return []

    def topics(self):
        try:
            return sorted(f[:-6] for f in
                          os.listdir(self._dir("topics"))
                          if f.endswith(".jsonl"))
        except OSError:
            return []

    # -- heartbeats --

    def beat(self, name, note=None):
        hb = {"organ": _safe(name), "epoch": round(time.time(), 3),
              "ts": _now_iso()}
        if note is not None:
            hb["note"] = str(note)[:200]
        atomic_write_json(self._dir(_safe(name), "heartbeat.json"), hb)
        return hb

    def heartbeat_age(self, name, now=None):
        try:
            hb = _read_json(self._dir(_safe(name), "heartbeat.json"))
            return round((now or time.time()) - float(hb["epoch"]), 1)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    # -- hygiene & reporting --

    def purge(self, keep_seen=200):
        """Cap each organ's seen folder at keep_seen letters."""
        removed = 0
        for organ in self.organs():
            seen = self._dir(organ, "seen")
            try:
                olds = sorted(f for f in os.listdir(seen)
                              if f.endswith(".json"))
            except OSError:
                continue
            for fname in olds[:-keep_seen] if keep_seen else olds:
                try:
                    os.unlink(os.path.join(seen, fname))
                    removed += 1
                except OSError:
                    pass
        return removed

    def status(self, now=None):
        now = now or time.time()
        organs = {}
        for name in self.organs():
            hb_age = self.heartbeat_age(name, now=now)
            last = None
            try:
                files = sorted(os.listdir(self._dir(name, "inbox")))
                if files:
                    last = files[0]
            except OSError:
                pass
            organs[name] = {"unread": self.unread(name),
                            "heartbeat_age_s": hb_age,
                            "stale": hb_age is None or hb_age > 600,
                            "next_letter": last}
        topics = {}
        for t in self.topics():
            p = self._dir("topics", t + ".jsonl")
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
            topics[t] = {"lines": len(self._topic_lines(t)),
                         "bytes": size}
        return {"root": self.root, "v": VERSION,
                "organs": organs, "topics": topics}


def _count_lines(path):
    try:
        with open(path, "rb") as fh:
            return sum(chunk.count(b"\n")
                       for chunk in iter(lambda: fh.read(1 << 16), b""))
    except OSError:
        return 0


# ------------------------------------------------- wiring convenience

def publish(topic, payload, frm="cli", kind="event", root=None):
    """Broadcast that never raises - safe inside watchdogs/gates."""
    try:
        return Post(root).broadcast(topic, kind, payload, frm=frm)
    except Exception:                        # noqa: BLE001 - bus must not kill hosts
        return None


def beat(name, note=None, root=None):
    """Heartbeat that never raises."""
    try:
        return Post(root).beat(name, note=note)
    except Exception:                        # noqa: BLE001
        return None
