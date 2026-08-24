"""HERMOD kernel - live update feeds without shipped fetchers.

Operators (or any local producer) drop feed bundles into
data/feeds/incoming/ - JSON files shaped {"source": "...",
"entries": [{"id", "title", "ts", ...}]}. Ingest normalizes them,
dedupes on content hash, appends to per-source JSONL stores, prunes
to bounds, and shouts each batch across the Ratatosk tree. Nothing
phones home; the contract is snapshot-directories (rule 12).
"""

import hashlib
import json
import os
import shutil
import threading
import time

from hermod import content


class FeedError(Exception):
    pass


def _now():
    return time.time()


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def entry_sha(source, entry):
    basis = json.dumps({"s": source, "e": entry},
                       sort_keys=True, separators=(",", ":"),
                       default=str)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def store_path(source):
    safe = "".join(c if (c.isalnum() or c in "-_") else "_"
                   for c in str(source))[:40] or "src"
    return os.path.join(content.STORE_DIR, safe + ".jsonl")


class FeedRoom:
    """Ingest + query. Thread-safe; every batch is atomic."""

    def __init__(self):
        self._lock = threading.Lock()
        self._head = {}            # source -> set of entry shas (lazy)
        for d in (content.INBOX_DIR, content.STORE_DIR,
                  content.DONE_DIR, content.FAILED_DIR):
            os.makedirs(d, exist_ok=True)

    # ------------------------------------------------------------ ingest --

    def ingest(self):
        """Consume every bundle in the inbox. Returns a report."""
        with self._lock:
            added, skipped, failed = 0, 0, []
            names = sorted(f for f in os.listdir(content.INBOX_DIR)
                           if f.endswith(".json"))
            for fname in names:
                src = os.path.join(content.INBOX_DIR, fname)
                try:
                    n = self._consume(src, fname)
                    added += n
                    skipped += self._last_skipped
                except (ValueError, OSError) as exc:
                    failed.append(fname)
                    self._park(src, fname, str(exc))
            return {"bundles": len(names), "added": added,
                    "skipped": skipped, "failed": len(failed),
                    "failed_files": failed}

    def _consume(self, src, fname):
        with open(src, "r", encoding="utf-8") as fh:
            bundle = json.load(fh)
        if not isinstance(bundle, dict):
            raise ValueError("bundle must be an object")
        source = str(bundle.get("source") or fname[:-5])
        entries = bundle.get("entries")
        if entries is None:
            entries = [bundle]
        if not isinstance(entries, list) or \
                len(entries) > content.MAX_ENTRIES_PER_BUNDLE:
            raise ValueError("bad entries array")
        seen = self._seen(source)
        fresh = []
        for e in entries:
            if not isinstance(e, dict):
                raise ValueError("entries must be objects")
            sha = entry_sha(source, e)
            if sha in seen:
                self._last_skipped += 1
                continue
            seen.add(sha)
            rec = dict(e)
            rec["_source"] = source
            rec["_sha"] = sha
            rec["_ingested"] = round(_now(), 3)
            fresh.append(rec)
        if fresh:
            self._append(source, fresh)
            self._shout(source, len(fresh), [r["_sha"] for r in fresh])
        shutil.move(src, self._archived_name(content.DONE_DIR, fname))
        self._prune(source)
        self._last_skipped = len(entries) - len(fresh) \
            if entries else 0
        return len(fresh)

    _last_skipped = 0

    def _archived_name(self, side, fname):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return os.path.join(side, f"{stamp}-{fname}")

    def _park(self, src, fname, why):
        try:
            shutil.move(src, self._archived_name(
                content.FAILED_DIR, "corrupt-" + fname))
            with open(os.path.join(
                    content.FAILED_DIR,
                    "why-" + fname + ".txt"), "w",
                    encoding="utf-8") as fh:
                fh.write(why)
        except OSError:
            pass

    def _seen(self, source):
        if source not in self._head:
            shas = set()
            try:
                with open(store_path(source), encoding="utf-8") as fh:
                    for ln in fh:
                        if ln.strip():
                            shas.add(json.loads(ln).get("_sha"))
            except OSError:
                pass
            self._head[source] = shas
        return self._head[source]

    def _append(self, source, records):
        path = store_path(source)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            for r in records:
                fh.write(json.dumps(r, sort_keys=True,
                                    separators=(",", ":"),
                                    default=str) + "\n")

    def _prune(self, source):
        path = store_path(source)
        try:
            lines = open(path, encoding="utf-8").readlines()
        except OSError:
            return
        cap = content.STORE_KEEP_ENTRIES
        if len(lines) <= cap:
            return
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(lines[-cap:])
        os.replace(tmp, path)

    @staticmethod
    def _shout(source, count, shas):
        try:
            import ratatosk
            ratatosk.publish(content.TOPIC,
                             {"source": source, "added": count,
                              "shas": shas[:20]},
                             frm=content.ORGAN, kind="feed")
        except Exception:
            pass

    # ------------------------------------------------------------- query --

    def latest(self, source=None, n=20):
        sources = ([source] if source
                   else self.sources())
        out = []
        for s in sources:
            try:
                with open(store_path(s), encoding="utf-8") as fh:
                    rows = [json.loads(l) for l in fh if l.strip()]
            except OSError:
                continue
            for r in rows[-int(n):]:
                out.append(r)
        out.sort(key=lambda r: r.get("_ingested", 0), reverse=True)
        return out[:int(n)]

    def sources(self):
        try:
            return sorted(f[:-6] for f in
                          os.listdir(content.STORE_DIR)
                          if f.endswith(".jsonl"))
        except OSError:
            return []

    def status(self):
        return {"hermod": True, "version": content.VERSION,
                "sources": self.sources(),
                "inbox_pending": len([f for f in
                                      os.listdir(content.INBOX_DIR)
                                      if f.endswith(".json")])}
