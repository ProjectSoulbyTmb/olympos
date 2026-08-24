"""ZEUS aegis - the file-integrity shield.

Builds a SHA-256 baseline over the protected roots declared in
content.PROTECTED_ROOTS and re-scans on demand: anything modified,
added or removed shows up as a tamper finding. The bolt can then move
suspect arrivals into quarantine. Scans prune junk directories and
cap file sizes so a fat build tree cannot stall a patrol.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import hashlib
import json
import time

import content


class Aegis:
    def __init__(self, workspace=None, baseline_path=None, roots=None):
        self.workspace = workspace or content.WORKSPACE
        self.baseline_path = baseline_path or content.BASELINE_PATH
        self.roots = list(roots if roots is not None
                          else content.PROTECTED_ROOTS)
        self.baseline = {}
        self.built_at = None

    # ---------- scanning ----------

    def _iter_files(self):
        ws = self.workspace
        for root in self.roots:
            base = os.path.join(ws, root)
            if os.path.isfile(base):
                yield base, os.path.normpath(root)
                continue
            if not os.path.isdir(base):
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in sorted(dirnames)
                               if d.lower() not in content.EXCLUDE_DIRS]
                for fn in sorted(filenames):
                    path = os.path.join(dirpath, fn)
                    rel = os.path.relpath(path, ws)
                    yield path, os.path.normpath(rel)

    @staticmethod
    def _hash_file(path):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()

    def _acceptable(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        if st.st_size > content.MAX_BASELINE_BYTES:
            return None
        if os.path.splitext(path)[1].lower() in content.EXCLUDE_SUFFIXES:
            return None
        return st

    def scan(self):
        """Full hash sweep: {relpath: record}."""
        table = {}
        for path, rel in self._iter_files():
            st = self._acceptable(path)
            if st is None:
                continue
            table[rel] = {
                "sha256": self._hash_file(path),
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            }
        return table

    # ---------- baseline ----------

    def build(self):
        self.baseline = self.scan()
        self.built_at = time.time()
        self.save()
        return {"files": len(self.baseline),
                "built_at": self.built_at}

    def save(self):
        os.makedirs(os.path.dirname(self.baseline_path), exist_ok=True)
        payload = {"version": content.VERSION,
                   "workspace": self.workspace,
                   "built_at": self.built_at,
                   "files": self.baseline}
        tmp = self.baseline_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp, self.baseline_path)

    def load(self):
        try:
            with open(self.baseline_path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            return False
        if payload.get("workspace") != self.workspace:
            return False
        self.baseline = payload.get("files", {})
        self.built_at = payload.get("built_at")
        return True

    def has_baseline(self):
        return bool(self.baseline)

    # ---------- verification ----------

    def verify(self, limit=100):
        """Compare disk against baseline; returns a findings dict.

        Findings kinds: modified, added, missing. Each carries at most
        `limit` examples plus a true count.
        """
        if not self.baseline:
            raise ValueError("no baseline - run build first")
        current = self.scan()
        mods, adds, miss = [], [], []
        for rel, rec in current.items():
            old = self.baseline.get(rel)
            if old is None:
                adds.append(rel)
            elif old["sha256"] != rec["sha256"]:
                mods.append(rel)
        for rel in self.baseline:
            if rel not in current:
                miss.append(rel)
        return {
            "checked": len(current),
            "modified": {"count": len(mods), "paths": mods[:limit]},
            "added": {"count": len(adds), "paths": adds[:limit]},
            "missing": {"count": len(miss), "paths": miss[:limit]},
            "clean": not (mods or adds or miss),
        }
