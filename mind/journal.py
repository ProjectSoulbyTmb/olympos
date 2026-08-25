"""MIND journal - append-only JSONL record of everything MIND saw or did.

Hades-flavored discipline in miniature: one JSON object per line,
monotonic per-process sequence numbers allocated under the same lock as
the append (lesson L026 - never derive identity from line position),
and readers replay strictly through the sequence field.

Run: python mind/journal.py   (self-test, exit 0 = ledger sane)
"""

from __future__ import annotations

import datetime
import json
import os
import threading

MAX_LINE_BYTES = 65536


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="milliseconds")


class Journal:
    def __init__(self, path: str):
        self.path = str(path)
        self._lock = threading.Lock()
        self._seq = self._recover_seq()
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def _recover_seq(self) -> int:
        """Seed from max(existing seq, line count) so rotated or
        pre-counter files migrate without collision (L026)."""
        highest, lines = 0, 0
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    for raw in handle:
                        lines += 1
                        try:
                            record = json.loads(raw)
                            highest = max(highest, int(record.get("seq", 0)))
                        except (json.JSONDecodeError, ValueError):
                            continue
            except OSError:
                return 0
        return max(highest, lines)

    def append(self, kind: str, data: "dict | None" = None,
               source: str = "mind") -> dict:
        record = {
            "seq": 0,  # replaced under lock before write
            "ts": _now_iso(),
            "source": source,
            "kind": str(kind),
            "data": data or {},
        }
        with self._lock:
            self._seq += 1
            record["seq"] = self._seq
            line = json.dumps(record, ensure_ascii=False)
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                record["data"] = {"truncated": True}
                line = json.dumps(record, ensure_ascii=False)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return record

    def replay(self) -> list:
        """Read back every well-formed record in sequence order."""
        records = []
        if not os.path.exists(self.path):
            return records
        with open(self.path, "r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        records.sort(key=lambda item: item.get("seq", 0))
        return records


def selftest() -> int:
    import tempfile

    failures = []

    def check(name, fn):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")

    def t_append_replay():
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(os.path.join(tmp, "nested", "journal.jsonl"))
            journal.append("event", {"eventType": "StreamStateChanged"})
            journal.append("action", {"action": "switch_scene"})
            records = journal.replay()
            assert [r["seq"] for r in records] == [1, 2], \
                f"sequence broken: {records}"
            assert records[0]["data"]["eventType"] == "StreamStateChanged"
            # reopening recovers identity instead of colliding (L026)
            again = Journal(journal.path)
            third = again.append("event", {"note": "post-rotation"})
            assert third["seq"] == 3, \
                f"recovered seq wrong: {third['seq']}"

    def t_corrupt_lines_skipped():
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            journal.append("good", {})
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("{not json\n")
            journal.append("good2", {})
            records = journal.replay()
            assert [r["kind"] for r in records] == ["good", "good2"], \
                "corrupt lines must quarantine, not block"

    check("append-replay-recover", t_append_replay)
    check("corrupt-lines-quarantine", t_corrupt_lines_skipped)

    print(f"journal selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
