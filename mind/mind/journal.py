"""MIND journal - append-only JSONL audit trail.

One line per notable act (connection, flow fired, control action),
timestamped UTC. The journal is the record: the HTTP layer stays quiet,
so reading the journal is reading MIND's memory of the show.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone


class Journal:
    def __init__(self, path: str):
        self.path = str(path)
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, kind: str, **fields) -> dict:
        entry = {"ts": datetime.now(timezone.utc).isoformat(),
                 "kind": kind}
        entry.update(fields)
        line = json.dumps(entry, ensure_ascii=True)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return entry

    def entries(self, limit=None) -> list:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    lines = handle.readlines()
            except FileNotFoundError:
                return []
        rows = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows[-int(limit):] if limit else rows


def selftest(tmp_dir: str = None) -> int:
    import tempfile
    tmp_dir = tmp_dir or tempfile.mkdtemp(prefix="mind-journal-")
    path = os.path.join(tmp_dir, "nested", "journal.jsonl")

    failures = []

    def check(name, fn):
        try:
            ok = fn()
        except Exception as exc:
            print(f"FAIL journal.{name}: crashed: {exc}")
            failures.append(name)
            return
        if not ok:
            print(f"FAIL journal.{name}")
            failures.append(name)

    j = Journal(path)

    def t_append_read():
        j.append("flow-fired", flow="f1")
        j.append("control", action="switch_scene")
        rows = j.entries()
        return ([r["kind"] for r in rows] == ["flow-fired", "control"]
                and all("ts" in r for r in rows))

    def t_limit():
        return len(j.entries(limit=1)) == 1

    def t_missing_is_empty():
        return Journal(os.path.join(tmp_dir, "none", "x.jsonl")).entries() == []

    check("append-read", t_append_read)
    check("limit", t_limit)
    check("missing-is-empty", t_missing_is_empty)
    print(f"journal selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
