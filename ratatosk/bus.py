"""RATATOSK bus - mailboxes, topics, heartbeats over plain files.

Layout under the post root (default `<repo>/data/post/`):

    registry.json                  organ name -> meta
    seq/<organ>.seq                per-sender monotonic counters
    locks/<resource>.lock          O_CREAT|O_EXCL spinlocks, stale takeover
     <organ>/inbox/<seq>-<from>-<kind>-<token>.json   unread letters
     <organ>/seen/...               read letters (purged by cap)
     <organ>/heartbeat.json         last liveness stamp + note
     topics/<topic>.jsonl           broadcast journal (live segment)
     topics/<topic>.jsonl.N         rotated archives, N=1 newest archive
     topics/<topic>.seq             persistent seq counter (never resets)
     cursors/<consumer>.<topic>     last consumed topic seq

Priority lanes: send(priority="high") leads the filename with "!."
(e.g. "!.000042-...json"); "!" sorts below digits, so inbox listings -
and therefore read()/peek() - deliver high-priority mail first, with
sender-sequence order preserved inside each lane.

Request/reply: send(corr=<id>) stamps the envelope; request() waits
for a "<kind>.reply" letter with the same corr in the caller's own
inbox; respond() answers a letter carrying both forward.

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

# SAFEGUARD: a letter is a signal, not a shipping service. Oversized
# payloads are the classic way one buggy organ degrades every reader.
MAX_LETTER_BYTES = 8 * 1024 * 1024      # 8 MiB serialized envelope cap
FLOOD_UNREAD = 1000                     # unread above this == flooded

ROTATE_BYTES = 5 * 1024 * 1024      # topic live-segment size cap
KEEP_SEGMENTS = 3                   # rotated archives kept per topic


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

    def __init__(self, root=None, rotate_bytes=ROTATE_BYTES,
                 keep_segments=KEEP_SEGMENTS):
        self.root = root or default_root()
        self.rotate_bytes = max(int(rotate_bytes), 1)
        self.keep_segments = max(int(keep_segments), 1)

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

    def send(self, to, kind, payload, frm="cli", corr=None,
             priority="normal"):
        """Deliver one letter to an organ's inbox. Returns the id.

        corr embeds a correlation id (request/reply pairing); priority
        is "normal" or "high" - high mail gets a "!." filename prefix
        so lexicographic listing delivers it first."""
        if priority not in ("normal", "high"):
            raise ValueError("priority must be 'normal' or 'high'")
        letter_probe = json.dumps({"payload": payload}, default=str)
        if len(letter_probe.encode("utf-8")) > MAX_LETTER_BYTES:
            raise ValueError(
                f"payload exceeds MAX_LETTER_BYTES ({MAX_LETTER_BYTES}); "
                "write it to a file and send the path instead")
        inbox, _ = self._ensure_organ(to)
        frm = _safe(frm)
        seq = self._next_seq(frm)
        letter = {"v": VERSION,
                  "id": f"{frm}-{seq:012d}",
                  "from": frm, "to": _safe(to), "kind": _safe(kind),
                  "ts": _now_iso(), "epoch": round(time.time(), 3),
                  "payload": payload}
        if corr is not None:
            letter["corr"] = str(corr)
        head = "!." if priority == "high" else ""
        fname = (f"{head}{seq:012d}-{frm}-{_safe(kind)}-"
                 f"{uuid.uuid4().hex[:8]}.json")
        atomic_write_json(os.path.join(inbox, fname), letter)
        self._bump_metrics(frm, "sent")
        return letter["id"]

    def request(self, to, kind, payload, frm, timeout_s=10.0,
                poll_s=0.05):
        """Send a request and wait for its reply.

        Stamps the outgoing letter with a fresh corr id, then polls our
        own inbox (frm is treated as an organ) for a letter whose kind
        is "<kind>.reply" carrying that corr. Returns the reply letter
        dict, or None on timeout. Raises TypeError on malformed args;
        everything else degrades to None."""
        if not isinstance(kind, str) or not kind:
            raise TypeError("kind must be a non-empty str")
        if isinstance(timeout_s, bool) or \
                not isinstance(timeout_s, (int, float)) or timeout_s < 0:
            raise TypeError("timeout_s must be a non-negative number")
        if isinstance(poll_s, bool) or \
                not isinstance(poll_s, (int, float)) or poll_s <= 0:
            raise TypeError("poll_s must be a positive number")
        try:
            corr = uuid.uuid4().hex
            self.send(to, kind, payload, frm=frm, corr=corr)
            self._ensure_organ(frm)      # our inbox must exist to poll
            want = _safe(kind) + ".reply"
            deadline = time.monotonic() + float(timeout_s)
            while time.monotonic() < deadline:
                hit = self._take_letter(
                    frm,
                    lambda l, c=corr, k=want: l.get("corr") == c
                    and l.get("kind") == k)
                if hit is not None:
                    return hit
                time.sleep(poll_s)
            return None
        except TypeError:
            raise
        except Exception:                # noqa: BLE001 - never kill host
            return None

    def respond(self, letter, payload, frm="cli"):
        """Answer a request letter: sends "<kind>.reply" back to the
        original sender with the same corr. Never raises."""
        try:
            if not isinstance(letter, dict):
                return None
            to = letter.get("from")
            kind = letter.get("kind")
            if not to or not kind:
                return None
            out = self.send(to, str(_safe(kind)) + ".reply", payload,
                            frm=frm, corr=letter.get("corr"))
            self._bump_metrics(frm, "replied")
            return out
        except Exception:                # noqa: BLE001
            return None

    # -- mailbox metrics (best-effort, never fatal) --

    DEFAULT_METRICS = {"sent": 0, "received": 0, "replied": 0,
                       "quarantined": 0}

    def _load_metrics(self, name):
        try:
            m = _read_json(self._dir(_safe(name), "metrics.json"))
        except (OSError, ValueError):
            m = {}
        out = dict(self.DEFAULT_METRICS)
        if isinstance(m, dict):
            for k in out:
                v = m.get(k)
                if isinstance(v, int) and not isinstance(v, bool):
                    out[k] = v
        return out

    def _bump_metrics(self, name, field, n=1):
        """Read-modify-write one counter under a best-effort lock;
        any failure is swallowed - metrics must never break mail."""
        if field not in self.DEFAULT_METRICS:
            return
        try:
            with _lock(self._dir("locks",
                                 f"metrics-{_safe(name)}.lock")) as ok:
                if not ok:
                    return
                m = self._load_metrics(name)
                m[field] += n
                atomic_write_json(
                    self._dir(_safe(name), "metrics.json"), m)
        except Exception:                # noqa: BLE001
            pass

    def _inbox_letters(self, name):
        """Yield (fname, letter-or-None) for one inbox in delivery
        order; unreadable files come through as None."""
        inbox = self._dir(_safe(name), "inbox")
        try:
            names = sorted(f for f in os.listdir(inbox)
                           if f.endswith(".json"))
        except OSError:
            return
        for fname in names:
            try:
                letter = _read_json(os.path.join(inbox, fname))
                if not isinstance(letter, dict):
                    letter = None
            except (OSError, ValueError):
                letter = None
            yield fname, letter

    def _take_letter(self, name, pred):
        """Consume the first inbox letter matching pred (moved to
        seen/, other mail untouched); None when nothing matches."""
        inbox = self._dir(_safe(name), "inbox")
        seen = self._dir(_safe(name), "seen")
        for fname, letter in self._inbox_letters(name):
            if letter is None or "payload" not in letter:
                continue
            try:
                if not pred(letter):
                    continue
            except Exception:            # noqa: BLE001 - bad pred, skip
                continue
            try:
                os.replace(os.path.join(inbox, fname),
                           os.path.join(seen, fname))
            except OSError:
                pass
            return letter
        return None

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
        for fname, letter in self._inbox_letters(name):
            if len(letters) >= limit:
                break
            src = os.path.join(inbox, fname)
            if letter is None or "payload" not in letter:
                if mark:
                    try:
                        os.replace(src, os.path.join(
                            seen, "corrupt-" + fname))
                    except OSError:
                        pass
                    self._bump_metrics(name, "quarantined")
                continue
            letters.append(letter)
            if mark:
                try:
                    os.replace(src, os.path.join(seen, fname))
                except OSError:
                    pass
                self._bump_metrics(name, "received")
        return letters

    # -- broadcast topics --

    def broadcast(self, topic, kind, payload, frm="cli"):
        """Append to topics/<topic>.jsonl under a mandatory lock;
        returns the unique, never-resetting seq.

        Seqs come from a persistent topics/<topic>.seq counter (atomic
        write, same strong lock as the append), NOT from line counts -
        so consumer cursors survive size-based rotation into
        .1/.2/.3 archive segments. Raises only if the lock is
        unwinnable - callers like publish() swallow that."""
        tpath = self._dir("topics", _safe(topic) + ".jsonl")
        os.makedirs(os.path.dirname(tpath), exist_ok=True)
        with _strong_lock(tpath + ".lock"):
            seq = self._next_topic_seq(_safe(topic))
            rec = {"v": VERSION, "topic": _safe(topic), "seq": seq,
                   "from": _safe(frm), "kind": _safe(kind),
                   "ts": _now_iso(), "epoch": round(time.time(), 3),
                   "payload": payload}
            line = json.dumps(rec, separators=(",", ":"),
                              default=str) + "\n"
            self._maybe_rotate(tpath, len(line.encode("utf-8")))
            with open(tpath, "a", encoding="utf-8") as fh:
                fh.write(line)
        return seq

    # Rotation internals - all run under the topic's strong lock.

    def _next_topic_seq(self, t):
        """Allocate seq = counter+1; lazily seed the counter from the
        existing segments on first touch (legacy single-file topics:
        their line-count == highest seq ever used)."""
        p = self._dir("topics", t + ".seq")
        cur = self._read_seq_file(p)
        if cur is None:
            cur = self._infer_topic_seq(t)
            self._write_seq_file(p, cur)
        nxt = cur + 1
        self._write_seq_file(p, nxt)
        return nxt

    @staticmethod
    def _read_seq_file(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return int(fh.read().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _write_seq_file(p, n):
        # L006: temp file + os.replace, never in-place
        tmp = p + f".{uuid.uuid4().hex[:6]}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(str(int(n)))
            os.replace(tmp, p)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _infer_topic_seq(self, t):
        """Highest seq plausibly consumed by existing data: max of the
        largest explicit record seq and the total line count across
        segments (covers pre-counter files whose seqs were line
        numbers, and counter-file loss)."""
        max_seq, lines = 0, 0
        for path in self._segment_paths(t):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    for ln in fh:
                        if not ln.strip():
                            continue
                        lines += 1
                        try:
                            s = int(json.loads(ln).get("seq"))
                        except (ValueError, AttributeError, TypeError):
                            continue
                        max_seq = max(max_seq, s)
            except OSError:
                continue
        return max(max_seq, lines)

    def _maybe_rotate(self, tpath, incoming_bytes):
        """Roll base -> .1 -> .2 -> ... when appending would push the
        live segment past the cap; oldest archive falls off. os.replace
        overwrites destinations, so the chain needs no unlinks."""
        try:
            if os.path.getsize(tpath) + incoming_bytes <= self.rotate_bytes:
                return
        except OSError:
            return                      # no live segment yet
        for i in range(self.keep_segments, 1, -1):
            try:
                os.replace(tpath + f".{i - 1}", tpath + f".{i}")
            except OSError:
                pass
        try:
            os.replace(tpath, tpath + ".1")
        except OSError:
            pass

    def _segment_paths(self, topic):
        """Topic segment files oldest-archive-first, live base last."""
        base = self._dir("topics", _safe(topic) + ".jsonl")
        paths = []
        for i in range(self.keep_segments, 0, -1):
            p = base + f".{i}"
            if os.path.exists(p):
                paths.append(p)
        paths.append(base)
        return paths

    @staticmethod
    def _seq_sort_key(rec):
        # records without a parseable int seq sort last (stable)
        s = rec.get("seq")
        if isinstance(s, int) and not isinstance(s, bool):
            return (0, s)
        return (1, 0)

    def _topic_records(self, topic):
        """All parseable records across segments, ascending by explicit
        seq (legacy/unparseable lines last)."""
        recs = []
        for path in self._segment_paths(topic):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    for ln in fh:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            rec = json.loads(ln)
                        except ValueError:
                            continue
                        if isinstance(rec, dict):
                            recs.append(rec)
            except OSError:
                continue
        recs.sort(key=self._seq_sort_key)
        return recs

    def line_count(self, topic):
        """Total non-empty lines across all segments of a topic."""
        n = 0
        for path in self._segment_paths(topic):
            try:
                with open(path, "rb") as fh:
                    n += sum(chunk.count(b"\n") for chunk in
                             iter(lambda: fh.read(1 << 16), b""))
            except OSError:
                continue
        return n

    def tail(self, topic, n=20):
        """Newest n records across all segments, ordered by seq."""
        return self._topic_records(topic)[-int(n):]

    def since(self, topic, consumer, limit=1000):
        """Cursor-based consume that survives rotation: cursors hold
        explicit record seqs (never line numbers); only records with a
        parseable seq participate. Advances to the max seq delivered."""
        cur_path = self._dir("cursors",
                             f"{_safe(consumer)}.{_safe(topic)}")
        try:
            with open(cur_path, "r", encoding="utf-8") as fh:
                start = int(fh.read().strip() or "0")
        except (OSError, ValueError):
            start = 0
        out = []
        max_seen = start
        for rec in self._topic_records(topic):
            if len(out) >= int(limit):
                break
            s = rec.get("seq")
            if not isinstance(s, int) or isinstance(s, bool) or s <= start:
                continue
            out.append(rec)
            max_seen = max(max_seen, s)
        if max_seen > start:
            tmp = cur_path + f".{uuid.uuid4().hex[:6]}.tmp"
            try:
                os.makedirs(os.path.dirname(cur_path), exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(str(max_seen))
                os.replace(tmp, cur_path)
            except OSError:
                pass
        return out

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
            unread = self.unread(name)
            last = None
            try:
                files = sorted(os.listdir(self._dir(name, "inbox")))
                if files:
                    last = files[0]
            except OSError:
                pass
            organs[name] = {"unread": unread,
                            "heartbeat_age_s": hb_age,
                            "stale": hb_age is None or hb_age > 600,
                            "flooded": unread > FLOOD_UNREAD,
                            "next_letter": last,
                            "metrics": self._load_metrics(name)}
        topics = {}
        for t in self.topics():
            size = 0
            segments = 0
            for path in self._segment_paths(t):
                try:
                    size += os.path.getsize(path)
                    segments += 1
                except OSError:
                    pass
            topics[t] = {"lines": self.line_count(t),
                         "bytes": size,
                         "segments": segments}
        return {"root": self.root, "v": VERSION,
                "organs": organs, "topics": topics}


# ------------------------------------------------- wiring convenience

def fit_payload(payload, max_bytes=MAX_LETTER_BYTES):
    """Shrink a payload under the letter cap for never-raise senders.

    Oversized payloads are replaced by a reference note; nothing is
    dropped silently because publish() callers cannot handle raises."""
    try:
        probe = json.dumps({"payload": payload}, default=str)
        if len(probe.encode("utf-8")) <= max_bytes:
            return payload
        blob = json.dumps(payload, default=str)
        keep = max(0, max_bytes - 512)       # room for the marker text
        return {"_truncated": True,
                "_reason": f"payload > {max_bytes} bytes",
                "preview": blob[:keep]}
    except Exception:                        # noqa: BLE001 - never raise
        return {"_truncated": True, "_reason": "unserializable payload"}


def safe_send(to, kind, payload, frm="cli", root=None, **kw):
    """send() that truncates oversize payloads instead of raising -
    for organ wiring where a crash costs more than a trimmed letter."""
    try:
        return Post(root).send(to, kind, fit_payload(payload), frm=frm,
                               **kw)
    except Exception:                        # noqa: BLE001
        return None


def deadman(name, max_age_s=600.0, root=None):
    """True when an organ's heartbeat is missing or too old - the
    liveness question watchdogs ask. Never raises."""
    try:
        age = Post(root).heartbeat_age(name)
        return age is None or age > float(max_age_s)
    except Exception:                        # noqa: BLE001
        return True

def publish(topic, payload, frm="cli", kind="event", root=None):
    """Broadcast that never raises - safe inside watchdogs/gates.
    Oversize payloads are truncated to a reference note, not dropped."""
    try:
        return Post(root).broadcast(topic, kind,
                                    fit_payload(payload), frm=frm)
    except Exception:                        # noqa: BLE001 - bus must not kill hosts
        return None


def beat(name, note=None, root=None):
    """Heartbeat that never raises."""
    try:
        return Post(root).beat(name, note=note)
    except Exception:                        # noqa: BLE001
        return None
