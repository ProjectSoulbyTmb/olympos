"""Vault: typed access to knowledge/lessons.json + proposal queue.

Schema (knowledge/lessons.json):
    {"_meta": {"categories": [...], ...},
     "lessons": [{"id": "L001", "title": ..., "category": ...,
                  "source": ..., "lesson": ..., "tags": [...]}]}

Invariants enforced by verify_learning.py:
- ids are monotonic, unique, never reused;
- every lesson carries all five required fields;
- categories come from _meta.categories.

Proposals live in ``knowledge/proposals/<L###>-<slug>.proposal.json``
with provenance attached; they never touch lessons.json directly.
"""

import json
import os
import re
import time

REQUIRED_FIELDS = ("id", "title", "category", "source", "lesson", "tags")
ID_RX = re.compile(r"^L(\d{3,})$")


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Vault:
    def __init__(self, root=None):
        self.root = root or repo_root()
        self.path = os.path.join(self.root, "knowledge", "lessons.json")
        self.proposals_dir = os.path.join(self.root, "knowledge",
                                          "proposals")

    # ---------------------------------------------------------- load
    def load(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def lessons(self):
        return self.load().get("lessons", [])

    def categories(self):
        return self.load().get("_meta", {}).get("categories", [])

    def ids(self):
        out = []
        for lsn in self.lessons():
            m = ID_RX.match(str(lsn.get("id", "")))
            if m:
                out.append(int(m.group(1)))
        return sorted(out)

    def next_id(self):
        ids = self.ids()
        n = (ids[-1] if ids else 0) + 1
        return f"L{n:03d}"

    # ------------------------------------------------------- queries
    def by_tag(self, tag):
        tag = tag.lower()
        return [l for l in self.lessons()
                if tag in [t.lower() for t in l.get("tags", [])]]

    def by_category(self, category):
        return [l for l in self.lessons()
                if l.get("category") == category]

    # ---------------------------------------------------- validation
    @staticmethod
    def validate_entry(entry, valid_categories):
        problems = []
        for field in REQUIRED_FIELDS:
            v = entry.get(field)
            if v is None or (isinstance(v, str) and not v.strip()):
                problems.append(f"missing field: {field}")
        if not isinstance(entry.get("tags"), list) or \
                not entry.get("tags"):
            problems.append("tags must be a non-empty list")
        cat = entry.get("category")
        if valid_categories and cat not in valid_categories:
            problems.append(f"unknown category: {cat!r}")
        if entry.get("id") and not ID_RX.match(entry["id"]):
            problems.append(f"bad id format: {entry['id']}")
        return problems

    # ------------------------------------------------------ proposals
    def propose(self, entry, *, proposed_by, evidence=None,
                rationale=""):
        """Stage a new lesson as a proposal file (never touches
        lessons.json). Returns the proposal path."""
        cats = self.categories()
        draft = dict(entry)
        draft["id"] = draft.get("id") or self.next_id()
        problems = Vault.validate_entry(draft, cats)
        if problems:
            raise ValueError("invalid lesson: " + "; ".join(problems))
        os.makedirs(self.proposals_dir, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", draft["title"].lower())[:40]
        fname = f"{draft['id']}-{slug}.proposal.json"
        path = os.path.join(self.proposals_dir, fname)
        n = 1
        while os.path.exists(path):  # concurrent drafters
            n += 1
            path = os.path.join(
                self.proposals_dir, f"{draft['id']}-{slug}-{n}.proposal.json")
        payload = {
            "v": 1,
            "proposed_by": proposed_by,
            "proposed_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "evidence": evidence or [],
            "rationale": rationale,
            "lesson": draft,
            "status": "proposed",
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return path

    def proposals(self):
        out = []
        if not os.path.isdir(self.proposals_dir):
            return out
        for f in sorted(os.listdir(self.proposals_dir)):
            if f.endswith(".proposal.json"):
                try:
                    with open(os.path.join(self.proposals_dir, f),
                              encoding="utf-8") as fh:
                        out.append(json.load(fh))
                except (OSError, ValueError):
                    continue
        return out


def load_vault(root=None):
    """Convenience: returns the raw lessons list."""
    return Vault(root).lessons()
