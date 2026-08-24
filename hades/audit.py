"""HADES audit trail - append-only, hash-chained event log.

Every event commits to the full history before it (prev hash), so
editing or deleting an old entry breaks every chain link after it.
The log lives next to the seal and is itself checked by the gate.
"""


import hashlib
import json
import time

GENESIS = "0" * 64


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _link(seq, ts, event, prev):
    return hashlib.sha256(
        (str(seq) + "\n" + ts + "\n" + _canon(event) + "\n" + prev).encode("utf-8")
    ).hexdigest()


class AuditLog:
    def __init__(self, path):
        self.path = path

    def append(self, event):
        entries = self._read_raw()[0]
        prev = entries[-1]["h"] if entries else GENESIS
        seq = (entries[-1]["seq"] + 1) if entries else 1
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry = {
            "seq": seq,
            "ts": ts,
            "event": event,
            "prev": prev,
            "h": _link(seq, ts, event, prev),
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def verify(self):
        entries, problems = self._read_raw()
        prev = GENESIS
        for e in entries:
            try:
                want = _link(e["seq"], e["ts"], e["event"], prev)
                if want != e.get("h"):
                    problems.append("seq %s: hash mismatch" % e.get("seq"))
                if e.get("prev") != prev:
                    problems.append("seq %s: broken chain link" % e.get("seq"))
            except KeyError:
                problems.append("malformed entry near seq %s" % e.get("seq"))
            prev = e.get("h", prev)
        return (not problems), problems, len(entries)

    def tail(self, n=5):
        return self._read_raw()[0][-n:]

    def _read_raw(self):
        entries = []
        problems = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except ValueError:
                        problems.append("line %d: corrupt JSON" % lineno)
        except OSError:
            pass
        return entries, problems
