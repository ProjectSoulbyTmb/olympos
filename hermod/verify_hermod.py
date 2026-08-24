"""HERMOD verifier - live feed pipeline contract, checked.

Every check runs against a throwaway data dir + post root.
"""

import contextlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from hermod import content                        # noqa: E402
from hermod.kernel import FeedRoom, entry_sha     # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@contextlib.contextmanager
def sandbox():
    outer = tempfile.mkdtemp(prefix="hermod-verify-")
    saved = {f: getattr(content, f) for f in
             ("DATA_DIR", "INBOX_DIR", "STORE_DIR", "DONE_DIR",
              "FAILED_DIR", "AUDIT_PATH")}
    saved_env = os.environ.get("RATATOSK_ROOT")
    data = os.path.join(outer, "data")
    for f, v in (("DATA_DIR", data),
                 ("INBOX_DIR", os.path.join(data, "incoming")),
                 ("STORE_DIR", os.path.join(data, "store")),
                 ("DONE_DIR", os.path.join(data, "processed")),
                 ("FAILED_DIR", os.path.join(data, "failed")),
                 ("AUDIT_PATH", os.path.join(data, "audit.jsonl"))):
        setattr(content, f, v)
        os.makedirs(v if f != "DATA_DIR" else data, exist_ok=True)
    os.environ["RATATOSK_ROOT"] = os.path.join(outer, "post")
    try:
        yield FeedRoom()
    finally:
        for f, v in saved.items():
            setattr(content, f, v)
        if saved_env is None:
            os.environ.pop("RATATOSK_ROOT", None)
        else:
            os.environ["RATATOSK_ROOT"] = saved_env
        shutil.rmtree(outer, ignore_errors=True)


def drop(bundle, fname="feed.json"):
    path = os.path.join(content.INBOX_DIR, fname)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh)
    return path


@check
def bundle_ingest_publishes_and_archives():
    with sandbox() as room:
        drop({"source": "upstream",
              "entries": [{"id": "a", "title": "A"},
                          {"id": "b", "title": "B"}]})
        rep = room.ingest()
        assert rep["added"] == 2 and rep["failed"] == 0, rep
        latest = room.latest("upstream")
        assert {e["id"] for e in latest} == {"a", "b"}, latest
        # shouted across the tree
        import ratatosk
        shouts = [r for r in ratatosk.Post().tail(
            content.TOPIC, n=10) if r.get("from") == "hermod"]
        assert shouts and shouts[-1]["payload"]["added"] == 2, shouts
        # original consumed into processed/
        done = os.listdir(content.DONE_DIR)
        assert len(done) == 1 and done[0].endswith("feed.json"), done


@check
def duplicate_bundles_dedupe():
    with sandbox() as room:
        bundle = {"source": "dup",
                  "entries": [{"id": "x"}, {"id": "y"}]}
        drop(bundle)
        r1 = room.ingest()
        assert r1["added"] == 2, r1
        drop(dict(bundle))
        r2 = room.ingest()
        assert r2["added"] == 0 and r2["skipped"] == 2, r2
        assert len(room.latest("dup")) == 2


@check
def corrupt_bundles_park_not_block():
    with sandbox() as room:
        with open(os.path.join(content.INBOX_DIR, "bad.json"),
                  "w", encoding="utf-8") as fh:
            fh.write("{nope")
        drop({"source": "good", "entries": [{"id": "ok"}]})
        rep = room.ingest()
        assert rep["added"] == 1 and rep["failed"] == 1, rep
        failed = os.listdir(content.FAILED_DIR)
        assert any(f.startswith("corrupt-") for f in failed), failed
        assert any(f.startswith("why-") for f in failed), failed
        assert len(room.latest("good")) == 1


@check
def stores_prune_to_bounds():
    old = content.STORE_KEEP_ENTRIES
    content.STORE_KEEP_ENTRIES = 3
    try:
        with sandbox() as room:
            for i in range(6):
                drop({"source": "prune",
                      "entries": [{"id": str(i), "n": i}]},
                     fname=f"f{i}.json")
                room.ingest()
            path = os.path.join(content.STORE_DIR, "prune.jsonl")
            lines = [l for l in open(path, encoding="utf-8")
                     if l.strip()]
            assert len(lines) <= 3, len(lines)
            ids = [json.loads(l)["id"] for l in lines]
            assert ids == ["3", "4", "5"], ids     # newest kept
    finally:
        content.STORE_KEEP_ENTRIES = old


@check
def status_reports_sources_and_backlog():
    with sandbox() as room:
        st = room.status()
        assert st["hermod"] and st["inbox_pending"] == 0, st
        drop({"source": "s1", "entries": [{"id": "1"}]})
        assert room.status()["inbox_pending"] == 1
        room.ingest()
        assert sorted(room.status()["sources"]) == ["s1"]


def main():
    print("=" * 64)
    print("HERMOD FEED GATE - live update pipeline")
    print("=" * 64)
    failures = []
    for fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:              # noqa: BLE001 - gate
            failures.append(fn.__name__)
            print(f"[FAIL] {fn.__name__}: "
                  f"{type(exc).__name__}: {exc}")
    total = len(CHECKS)
    print("-" * 64)
    print(f"{total - len(failures)}/{total} checks green"
          + ("" if not failures else " - FAILURES PRESENT"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
