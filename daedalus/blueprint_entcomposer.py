"""DAEDALUS blueprint: ent-composer - the entertainment composer.

Batch V7 studio tier. Deterministic composition over produced and
imported media - consumption-only, no new player engine (house
non-goal). Proven laws:

  Seeded determinism - the same library + seed yields a manifest
  whose digest is identical across runs; a shuffle token derived
  from the seeded RNG is folded INTO the digest so any unseeded
  randomness breaks the gate rather than hiding.
  Bucket order - sealed reels lead, then videos/images interleaved
  round-robin, at most one game last, trimmed to the limit.
  Guest clamp - an L0 profile strips interactive launch; viewing
  remains.

Extension shape: register(executors) wires entertain play/queue/reel
onto APOLLO's drop-in protocol."""

import sys

COMPOSER = '''"""Entertainment composer - seeded playlists over sealed artifacts."""

import hashlib
import json
import random

BUCKET_ORDER = ("reel", "video", "image", "game")


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _bucket(e):
    k = str(e.get("kind") or "").lower()
    return k if k in BUCKET_ORDER else "image"


def compose(library, seed, mode="evening", limit=12):
    """Build one evening. Deterministic in (library order-insensitive
    sort, seed); the RNG token inside the digest proves it."""
    rng = random.Random(seed)
    entries = sorted((dict(e) for e in library),
                     key=lambda e: (str(e.get("path")),
                                    float(e.get("mtime") or 0)))
    buckets = {k: [] for k in BUCKET_ORDER}
    for e in entries:
        b = _bucket(e)
        if b == "reel" and not e.get("sealed"):
            continue          # unsealed reels never headline
        buckets[b].append(e)
    reels = buckets["reel"][::-1]      # newest first (stable sort)
    rng.shuffle(reels)                 # seeded: reproducible
    vids, imgs = buckets["video"], buckets["image"]
    inter = []
    while vids or imgs:
        if vids:
            inter.append(vids.pop(0))
        if imgs:
            inter.append(imgs.pop(0))
    games = buckets["game"][:1]
    order = ([e["path"] for e in reels] +
             [e["path"] for e in inter] +
             [e["path"] for e in games])[:max(1, int(limit))]
    token = rng.random()               # digest-visible RNG witness
    body = {"mode": mode, "order": order, "seed": str(seed),
            "shuffle_token": repr(token)}
    return {"mode": mode, "order": order, "seed": str(seed),
            "interactive_launch": True,
            "digest": hashlib.sha256(
                _canonical(body).encode("utf-8")).hexdigest()}


def clamp_guest(manifest_out, level):
    """L0 sessions get viewing only - no interactive launches."""
    out = dict(manifest_out)
    if level == "L0":
        out["interactive_launch"] = False
    return out


def register(executors):
    """APOLLO drop-in adapter: entertain domain lands here."""

    def _compose(session, cmd, ctx):
        lib = ctx.get("library") or []
        seed = cmd.flags.get("seed", session["id"])
        mode = str(cmd.target or "evening")
        out = compose(lib, seed, mode=mode,
                      limit=int(cmd.flags.get("limit", 12)))
        return {"ok": True, "playlist": clamp_guest(out,
                                                    session["level"])}
    executors[("entertain", "play")] = _compose
    executors[("entertain", "queue")] = _compose

    def _reel(session, cmd, ctx):
        lib = [e for e in (ctx.get("library") or [])
               if e.get("kind") == "reel" and e.get("sealed")]
        if not lib:
            return {"ok": False,
                    "error": "no sealed reels available"}
        out = compose(lib, cmd.flags.get("seed", session["id"]),
                      mode="reels", limit=int(
                          cmd.flags.get("limit", 6)))
        return {"ok": True, "playlist": clamp_guest(out,
                                                    session["level"])}
    executors[("entertain", "reel")] = _reel
'''

GATE = '''"""Self-test gate for ent-composer (exit 0 = green)."""

import sys

from entertainer_composer import clamp_guest, compose

LIBRARY = (
    [{"path": "reels/r%d.mp4" % i, "kind": "reel",
      "mtime": 100 + i, "sealed": True} for i in range(5)] +
    [{"path": "clips/v%d.mp4" % i, "kind": "video",
      "mtime": 200 + i} for i in range(6)] +
    [{"path": "stills/i%d.png" % i, "kind": "image",
      "mtime": 300 + i} for i in range(8)] +
    [{"path": "builds/orb.exe", "kind": "game", "mtime": 400}] +
    [{"path": "reels/draft.mp4", "kind": "reel",
      "mtime": 999, "sealed": False}]
)


def main():
    a = compose(LIBRARY, "friday", mode="evening", limit=99)
    b = compose(LIBRARY, "friday", mode="evening", limit=99)
    assert a["digest"] == b["digest"], "same seed digested apart"
    assert a["order"] == b["order"], "same seed ordered apart"

    c = compose(LIBRARY, "saturday", mode="evening", limit=99)
    assert c["digest"] != a["digest"], "seeds collapsed"
    assert c["order"] != a["order"], "shuffle did not move"

    # bucket law: sealed reels first, exactly one game last
    reel_paths = {e["path"] for e in LIBRARY
                  if e.get("kind") == "reel" and e.get("sealed")}
    head = [p for p in a["order"] if p in reel_paths]
    tail = a["order"][-1]
    assert head and a["order"][:len(head)] == head, \\
        "sealed reels do not lead: %r" % a["order"]
    assert tail == "builds/orb.exe", "game not last: %r" % a["order"]
    assert "reels/draft.mp4" not in a["order"], \\
        "unsealed reel headlined"

    # limit honored
    d = compose(LIBRARY, "friday", limit=3)
    assert len(d["order"]) == 3, d["order"]

    # guest clamp strips launch but keeps the playlist
    g = clamp_guest(a, "L0")
    assert g["interactive_launch"] is False
    assert g["order"] == a["order"] and g["digest"] == a["digest"]
    assert clamp_guest(a, "L1")["interactive_launch"] is True

    print("ent-composer gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"entertainer_composer.py": COMPOSER,
            "verify_entcomposer.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # RNG stripped of its seed -> shuffle tokens diverge between the
    # two same-seed runs -> digest equality assert goes red
    "shuffle_drift": ("entertainer_composer.py",
                      "rng = random.Random(seed)",
                      "rng = random.Random()"),
}

BLUEPRINT = {
    "description": "VOLTAGE ent-composer (entertainment): seeded "
                   "deterministic playlists, guest clamp, no player "
                   "engine (thin composition only)",
    "files": FILES,
    "gate": [sys.executable, "verify_entcomposer.py"],
    "faults": dict(FAULTS),
}
