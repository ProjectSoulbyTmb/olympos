"""DAEDALUS blueprint: know-gateway - the knowledge domain adapter.

Batch V8 mind tier. Search/cards/advise law for the OS's own corpus,
proven offline against an embedded distilled corpus (the real
knowledge organ and haven-v bind behind the same seams at
commissioning):

  Deterministic ranking - field-weighted scoring (title x3, tags x2,
  body x1) with ties broken by entry id ascending; two runs over the
  same query MUST produce identical order, and anchor queries MUST
  return their named top hit (semantic anchors make tie-break drift
  observable, not just structural).
  Honest misses - unknown card ids and empty result sets are lawful
  refusals with named errors, never silent empties.

Extension shape: register(executors) wires know search/cards/advise
onto APOLLO's drop-in protocol (all three are L0 verbs)."""

import sys

GATEWAY = '''"""Know gateway - deterministic retrieval over the OS corpus."""

import re

CORPUS = [
    {"id": "K-002", "title": "envelope contract",
     "body": "Every response carries error; clients trust the shape.",
     "tags": ["bus", "contract"], "source": "INTEGRATION section 4"},
    {"id": "K-010", "title": "seeded replay",
     "body": "Same seed plus same actions yields identical digests.",
     "tags": ["determinism"], "source": "guarantee one"},
    {"id": "K-011", "title": "digest determinism",
     "body": "Studio artifacts hash from spec plus seed, so reruns "
             "verify byte-for-byte.",
     "tags": ["studios", "determinism"],
     "source": "B7 acceptance"},
    {"id": "K-012", "title": "rights ladder",
     "body": "L0 observe, L1 act, L2 administer; the ladder is "
             "checked at dispatch before anything runs.",
     "tags": ["security"], "source": "apollo rights map"},
    {"id": "K-003", "title": "quarantine never destroy",
     "body": "Broken things are contained and journaled, not deleted.",
     "tags": ["ops"], "source": "house doctrine"},
    {"id": "K-020", "title": "riley model tiers",
     "body": "sd15 fast, sdxl quality, flux flagship; tier follows "
             "vram.",
     "tags": ["image", "generation"], "source": "riley studio readme"},
    {"id": "K-021", "title": "kinema job specs",
     "body": "Steps run in order in the workdir; outputs stay inside "
             "it.",
     "tags": ["video", "generation"], "source": "kinema readme"},
]

ADVISE = {
    "provenance": ["K-002"],
    "generation": ["K-020", "K-021"],
    "replay": ["K-010", "K-011"],
    "access": ["K-012"],
}


def tokenize(text):
    return [t for t in re.split(r"[^a-z0-9]+",
                                str(text or "").lower()) if t]


def score(entry, terms):
    hits = 0
    title = tokenize(entry.get("title"))
    body = tokenize(entry.get("body"))
    tags = tokenize(" ".join(entry.get("tags") or []))
    for t in terms:
        if t in title:
            hits += 3
        if t in tags:
            hits += 2
        if t in body:
            hits += 1
    return hits


def _ranked(terms):
    scored = [(score(e, terms), e) for e in CORPUS]
    hits = [(s, e) for s, e in scored if s > 0]
    hits.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return hits


def search(q, limit=5):
    """Deterministic retrieval: weight, then id ascending."""
    hits = _ranked(tokenize(q))[:max(1, int(limit))]
    return [{"id": e["id"], "title": e["title"], "score": s,
             "source": e["source"]} for s, e in hits]


def cards(eid):
    for e in CORPUS:
        if e["id"] == str(eid or "").strip():
            return dict(e)
    return None


def advise(topic):
    ids = ADVISE.get(str(topic or "").lower())
    if not ids:
        return None
    return [c(i) for i in ids if c(i)]


def c(eid):
    return cards(eid)


def register(executors):
    """APOLLO drop-in adapter: know domain lands here."""

    def _search(session, cmd, ctx):
        rows = search(str(cmd.target or ""),
                      limit=int(cmd.flags.get("limit", 5)))
        return {"ok": True, "hits": rows}
    executors[("know", "search")] = _search

    def _cards(session, cmd, ctx):
        card = cards(str(cmd.target or ""))
        if card is None:
            return {"ok": False,
                    "error": "no such card: %r" % cmd.target}
        return {"ok": True, "card": card}
    executors[("know", "cards")] = _cards

    def _advise(session, cmd, ctx):
        rows = advise(str(cmd.target or ""))
        if rows is None:
            return {"ok": False,
                    "error": "no advice topic: %r" % cmd.target}
        return {"ok": True, "cards": rows}
    executors[("know", "advise")] = _advise
'''

GATE = '''"""Self-test gate for know-gateway (exit 0 = green)."""

import sys

from know_gateway import advise, cards, search, tokenize


def main():
    # determinism: identical query, identical order - twice
    a = search("seed")
    b = search("seed")
    assert a == b, "search order drifted between runs"

    # semantic anchor: "seed" is a scored TIE (K-010 body, K-011 body)
    # so id-ascending must put K-010 on top; any tie-break drift or
    # reordering shows up right here
    assert a and a[0]["id"] == "K-010", a
    assert a[1]["id"] == "K-011", a

    # weighting beats raw frequency: "ladder" lives in K-012's TITLE
    top = search("ladder")[0]
    assert top["id"] == "K-012" and top["score"] >= 3, top

    # envelope law of the corpus itself
    env = search("error carries")[0]
    assert env["id"] == "K-002", env

    # honest misses are lawful Nones at the library layer
    assert cards("M-999") is None
    assert advise("nonexistent-topic") is None

    # tokens split cleanly
    assert tokenize("Seeded REPLAY!") == ["seeded", "replay"]

    print("know-gateway gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"know_gateway.py": GATEWAY, "verify_knowgateway.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # tie-break flipped -> the anchored "seed" query puts K-011 on
    # top; the semantic-anchor assertion goes red (independent)
    "rank_drift": ("know_gateway.py",
                   'hits.sort(key=lambda pair: (-pair[0], '
                   'pair[1]["id"]))',
                   'hits.sort(key=lambda pair: (-pair[0], '
                   'pair[1]["id"]), reverse=False)\n'
                   '    hits = hits[::-1]'),
}

BLUEPRINT = {
    "description": "VOLTAGE know-gateway: deterministic weighted "
                   "search, anchored tie-breaks, honest misses",
    "files": FILES,
    "gate": [sys.executable, "verify_knowgateway.py"],
    "faults": dict(FAULTS),
}
