"""DAEDALUS blueprint: muse-curriculum - the OS knowledge product DB.

Batch V8 mind tier. The curriculum pack for VOLTAGE's own conventions,
shaped EXACTLY to the knowledge organ's law (verified against the live
organ at the sovereign root, 7/7):

  Entry contract - id MUSE-### (prefix honored, monotonic), title,
  category, summary, details, sources (https URLs), tags. Seven keys,
  all mandatory, all truthy.
  Validator as gate - the same checks the organ runs: schema, prefix,
  uniqueness, https sources. A deliberately corrupted copy MUST be
  caught BY NAME; a gutted check must turn this blueprint's own gate
  red (independence).
  Loader refuses to serve an unlawful corpus - broken curricula never
  reach learners.

The CURRICULUM object here IS the shipped muse.json content: one
source of truth, no drift between blueprint and product."""

import sys

REPO = "https://github.com/ProjectSoulbyTmb/voltage"
SPEC = REPO + "/blob/main/docs/contracts/voltage-command-spec-v1.md"
ADR3 = REPO + "/blob/main/docs/adr/0005-voltage-creative-control-os.md"

CURRICULUM = {
    "$schema": "olympos/knowledge-db-v1",
    "description": ("MUSE - VOLTAGE's own convention curriculum: "
                    "the laws a creative-control OS runs on."),
    "prefix": "muse",
    "updated": "2026-08-25",
    "upstream": "ADR-0005 + voltage-command-spec-v1",
    "entries": [
        {"id": "MUSE-001", "title": "command grammar law",
         "category": "command-plane",
         "summary": ("One verb per organ surface; grammar derives "
                     "from the rights map; /catalog renders it."),
         "details": ("Every command parses through one grammar whose "
                     "domains and verbs derive from apollo_rights_map; "
                     "the catalog endpoint emits that law so UIs and "
                     "docs never hand-copy tables that can rot."),
         "sources": [SPEC], "tags": ["apollo", "grammar"]},
        {"id": "MUSE-002", "title": "envelope everywhere",
         "category": "bus-contract",
         "summary": ("Every response carries error through one choke "
                     "point; refusals are lawful outputs."),
         "details": ("Single choke point in each server assembles "
                     "envelopes; a stripped choke is an injected "
                     "breaker with a named red."),
         "sources": [ADR3], "tags": ["bus", "contract"]},
        {"id": "MUSE-003", "title": "port isolation 441xx",
         "category": "isolation",
         "summary": ("VOLTAGE owns 44100-44199; seeded realms offset "
                     "439NN to 441NN; squatters fail loud at boot."),
         "details": ("Boot-time sweeps claim the whole block; "
                     "collisions fail loud instead of degrading."),
         "sources": [ADR3], "tags": ["isolation", "ports"]},
        {"id": "MUSE-004", "title": "studio adapter protocol",
         "category": "studios",
         "summary": ("apollo_ext_<domain>.py overrides builtin doubles; "
                     "ladder, witness and seal apply unchanged."),
         "details": ("Drop-in adapters load once at dispatcher init; "
                     "broken files are skipped, never fatal; extension "
                     "mutations witness identically to builtins."),
         "sources": [SPEC], "tags": ["studios", "extension"]},
        {"id": "MUSE-005", "title": "digest determinism",
         "category": "studios",
         "summary": ("Same job spec plus seed yields identical artifact "
                     "sha256; digests come before encoders."),
         "details": ("B7 is enforced upstream of any backend: the "
                     "digest law lives in the host seam, so swapping "
                     "ffmpeg or engines cannot break replay."),
         "sources": [SPEC], "tags": ["studios", "determinism"]},
        {"id": "MUSE-006", "title": "seal chain",
         "category": "provenance",
         "summary": ("Session transcripts and artifacts seal under HADES; "
                     "one flipped byte breaks verification."),
         "details": ("Chains link each entry to its predecessor so "
                     "deletion or reordering fails AT THE GAP even "
                     "with forged length and tip metadata."),
         "sources": [ADR3], "tags": ["provenance"]},
        {"id": "MUSE-007", "title": "lesson pipeline",
         "category": "learning",
         "summary": ("Proposals cite evidence or die; promotion needs an "
                     "L2 session plus operator sign-off file."),
         "details": ("Two named refusals guard the valve: evidence "
                     "required at propose time; sign-off file missing "
                     "at promote time. The auto_promote breaker proves "
                     "the gate dies if either check is gutted."),
         "sources": [SPEC], "tags": ["learning"]},
        {"id": "MUSE-008", "title": "thin entertainment",
         "category": "entertainment",
         "summary": ("Playlists compose existing viewers; no new player "
                     "engine exists or will."),
         "details": ("Seeded composition with shuffle-token-in-digest "
                     "witnesses determinism; guest clamps strip "
                     "interactive launch."),
         "sources": [ADR3], "tags": ["entertainment"]},
        {"id": "MUSE-009", "title": "acceptable use hard line",
         "category": "policy",
         "summary": ("No identity-clone tooling; nothing targeting real, "
                     "identifiable people; local-first always."),
         "details": ("Carried verbatim from the KINEMA and RILEY "
                     "charters into the OS curriculum so every learner "
                     "inherits the boundary."),
         "sources": [REPO], "tags": ["policy"]},
        {"id": "MUSE-010", "title": "one-seat enterprise bar",
         "category": "enterprise",
         "summary": ("Audit chains, rights ladder, provenance seals, SLA "
                     "pulse and packaged installers - B1 through B10."),
         "details": ("Each criterion has an executable proof or an "
                     "explicitly commissioning-bound gate; nothing "
                     "claims health without one."),
         "sources": [ADR3], "tags": ["enterprise"]},
    ],
}

LOADER = '''"""Muse loader - convention validation before anything learns."""

import json

REQUIRED_KEYS = ("id", "title", "category", "summary", "details",
                 "sources", "tags")


def validate(data):
    """-> list[str] problems. Empty means the corpus is lawful."""
    p = []
    if not isinstance(data, dict):
        return ["curriculum must be an object"]
    prefix = str(data.get("prefix") or "")
    if not prefix:
        p.append("prefix required")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return p + ["entries must be a non-empty list"]
    seen = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            p.append("entry %d must be an object" % i)
            continue
        for k in REQUIRED_KEYS:
            if not e.get(k):
                p.append("entry %d missing %s" % (i, k))
        eid = str(e.get("id") or "")
        if prefix and not eid.upper().startswith(prefix.upper()):
            p.append("entry %d id %r violates prefix %r"
                     % (i, eid, prefix))
        if eid in seen:
            p.append("duplicate id %r" % eid)
        seen.add(eid)
        srcs = e.get("sources")
        if not isinstance(srcs, list) or not srcs:
            p.append("entry %d sources must be a non-empty list" % i)
        else:
            for s in srcs:
                if not str(s).startswith("https://"):
                    p.append("entry %d non-https sources: %r"
                             % (i, s))
                    break
    return p


def load(path):
    """Parse + validate; refuse to serve an unlawful corpus."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    problems = validate(data)
    if problems:
        raise ValueError("curriculum rejected: " + "; ".join(problems))
    return data
'''

GATE = '''"""Self-test gate for muse-curriculum (exit 0 = green)."""

import copy
import json
import os
import sys
import tempfile

from muse_loader import load, validate
from muse_data import CURRICULUM


def main():
    # the shipped corpus is lawful, and equals its module snapshot
    problems = validate(CURRICULUM)
    assert problems == [], problems
    assert len(CURRICULUM["entries"]) == 10
    assert all(e["id"].startswith("MUSE-")
               for e in CURRICULUM["entries"])
    assert all(str(e["sources"][0]).startswith("https://")
               for e in CURRICULUM["entries"])

    base = tempfile.mkdtemp(prefix="muse-")
    path = os.path.join(base, "muse.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(CURRICULUM, fh)
    loaded = load(path)
    assert loaded == CURRICULUM

    # a corrupted copy MUST be caught BY NAME (organ parity)
    bad = copy.deepcopy(CURRICULUM)
    bad["entries"][2]["id"] = "X-003"
    bad_problems = validate(bad)
    assert any("violates prefix" in q for q in bad_problems), \\
        bad_problems

    bad2 = copy.deepcopy(CURRICULUM)
    bad2["entries"][5]["id"] = "MUSE-001"
    assert any("duplicate id" in q for q in validate(bad2))

    bad3 = copy.deepcopy(CURRICULUM)
    bad3["entries"][0]["sources"] = ["http://insecure.example"]
    assert any("non-https" in q for q in validate(bad3)), \\
        "https law did not bite"

    # the loader refuses to serve corruption
    badpath = os.path.join(base, "bad.json")
    with open(badpath, "w", encoding="utf-8") as fh:
        json.dump(bad, fh)
    try:
        load(badpath)
        raise AssertionError("loader served a corrupt curriculum")
    except ValueError as exc:
        assert "violates prefix" in str(exc), exc

    print("muse-curriculum gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {
        "muse_loader.py": LOADER,
        "muse_data.py": "CURRICULUM = " + repr(CURRICULUM) + "\n",
        "verify_muse.py": GATE,
    }


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # prefix rule gutted -> the corrupted X-003 copy passes validation;
    # the named-catch assertions go red (independent breaker)
    "prefix_drift": ("muse_loader.py",
                     'if prefix and not eid.upper().startswith('
                     'prefix.upper()):\n'
                     '            p.append("entry %d id %r violates '
                     'prefix %r"\n'
                     '                     % (i, eid, prefix))',
                     'pass'),
}

BLUEPRINT = {
    "description": "VOLTAGE muse-curriculum: organ-law conforming "
                   "knowledge DB (MUSE-### ids, 7 mandatory keys, "
                   "https sources) + refusing loader",
    "files": FILES,
    "gate": [sys.executable, "verify_muse.py"],
    "faults": dict(FAULTS),
}
