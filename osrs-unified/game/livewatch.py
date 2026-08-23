"""Live-stream change detection for OsrsLab updater snapshots.

Watches knowledge/live/*.json mtimes and surfaces changed files with
their parsed payloads. Consumers:

  - server/rsps_server.py polls it and serves `{"cmd": "live"}`
  - anything else that wants push-style reactions to updater runs

Pure stdlib, offline-safe, never raises on missing/corrupt files.
"""
import json
import os

WATCHED = ("ge_prices.json", "game_updates.json")

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "knowledge", "live")


class LiveStream:
    def __init__(self, live_dir=None):
        self.dir = live_dir or DEFAULT_DIR
        self._seen = {}

    def _read(self, path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def poll(self):
        """-> [{"file", "mtime", "data"}] for watched files whose
        mtime changed since the previous call (first call reports all
        files that exist)."""
        out = []
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for fname in WATCHED:
            if fname not in names:
                continue
            path = os.path.join(self.dir, fname)
            try:
                m = os.path.getmtime(path)
            except OSError:
                continue
            if self._seen.get(fname) == m:
                continue
            data = self._read(path)
            if data is None:
                continue
            self._seen[fname] = m
            out.append({"file": fname, "mtime": m, "data": data})
        return out

    def latest(self, fname):
        """-> parsed snapshot or None (no mtime bookkeeping)."""
        if fname not in WATCHED:
            return None
        return self._read(os.path.join(self.dir, fname))
