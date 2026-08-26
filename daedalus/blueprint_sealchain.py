"""DAEDALUS blueprint: session-seal - HADES-ready linked seal chains.

Batch V9 enterprise hardening. Generalizes B8 from transcripts to any
artifact set: each entry links to its predecessor, so the chain proves
COMPLETE ORDER, not merely membership:

  link_i = sha256(prev_link | name | payload_sha256), genesis =
  sha256("genesis|seed|session"). Removing or reordering a middle
  entry breaks verification AT THAT INDEX even when an attacker also
  fixes the stored length and tip - linkage is the law.
  verify names the first divergent index instead of a bare false.
  Artifacts ride beside transcript entries with equal standing.

Commissioning hands sealed chains to HADES for fingerprint + HMAC
anchoring; this blueprint owns the chain mathematics itself."""

import sys

CHAIN = '''"""Seal chains - linked digests that name their first break."""

import hashlib
import json


def h(b):
    return hashlib.sha256(b).hexdigest()


def _genesis(session_id, seed):
    return h(("genesis|%s|%s" % (seed, session_id))
             .encode("utf-8"))


def _link(prev, name, psha):
    return h((prev + "|" + name + "|" + psha).encode("utf-8"))


def _chain_from_digests(genesis, digests):
    """digests: [(name, payload_sha256)] -> linked nodes."""
    prev = genesis
    out = []
    for name, psha in digests:
        prev = _link(prev, name, psha)
        out.append({"name": name, "payload_sha256": psha,
                    "link": prev})
    return out


def build(session_id, transcript_entries, artifacts, seed="voltage"):
    items = [("transcript:%04d" % i,
              json.dumps(e, sort_keys=True))
             for i, e in enumerate(transcript_entries)]
    items += [("artifact:%s" % str(a.get("name")),
               str(a.get("sha256")))
              for a in (artifacts or [])]
    genesis = _genesis(session_id, seed)
    digests = [(name, h(str(payload).encode("utf-8")))
               for name, payload in items]
    chain = _chain_from_digests(genesis, digests)
    return {"session": session_id, "genesis": genesis,
            "seed": seed,
            "length": len(chain),
            "tip": chain[-1]["link"] if chain else genesis,
            "chain": chain}


def verify(sealed):
    """Recompute the whole chain; name the first divergence."""
    if not isinstance(sealed, dict) or "chain" not in sealed:
        return {"ok": False, "error": "malformed seal"}
    genesis = _genesis(sealed.get("session"), sealed.get("seed",
                                                        "voltage"))
    if sealed.get("genesis") != genesis:
        return {"ok": False, "error": "genesis mismatch"}
    if sealed.get("length") != len(sealed["chain"]):
        return {"ok": False, "error": "length mismatch"}
    recomputed = _chain_from_digests(
        genesis, [(n["name"], n["payload_sha256"])
                  for n in sealed["chain"]])
    for i, (got, exp) in enumerate(zip(recomputed,
                                       sealed["chain"])):
        if got["link"] != exp["link"]:
            return {"ok": False, "at_index": i,
                    "error": "chain diverges at index %d" % i}
    tip = sealed["chain"][-1]["link"] if sealed["chain"] \\
        else genesis
    if sealed.get("tip") != tip:
        return {"ok": False, "error": "tip mismatch"}
    return {"ok": True, "tip": tip}


def register(executors):
    """APOLLO drop-in adapter: ops seal packages a session."""
    def _seal(session, cmd, ctx):
        built = build(session["id"],
                      ctx.get("transcript_entries") or [],
                      ctx.get("artifacts") or [],
                      seed=ctx.get("seed", "voltage"))
        return {"ok": True, "sealed": built}
    executors[("ops", "seal")] = _seal
'''

GATE = '''"""Self-test gate for session-seal (exit 0 = green)."""

import copy
import sys

from seal_chain import build, verify

ENTRIES = [{"line": "voltage demo note alpha", "ok": True},
           {"line": "voltage image generate sunset", "ok": True},
           {"line": "voltage session seal", "ok": True}]
ARTIFACTS = [{"name": "reel.mp4", "sha256": "a" * 64},
             {"name": "poster.png", "sha256": "b" * 64}]


def main():
    sealed = build("s-0007", ENTRIES, ARTIFACTS, seed="friday")
    assert sealed["length"] == 5, sealed["length"]
    assert verify(sealed)["ok"] is True

    # byte-flip inside a payload digest -> named index
    tampered = copy.deepcopy(sealed)
    tampered["chain"][3]["payload_sha256"] = "f" * 64
    v = verify(tampered)
    assert not v["ok"] and v.get("at_index") == 3, v

    # THE LINKAGE LAW: delete a middle entry AND forge length+tip-
    # consistent metadata; verification must still die AT THE GAP
    attacked = copy.deepcopy(sealed)
    del attacked["chain"][1]
    attacked["length"] = len(attacked["chain"])
    v = verify(attacked)
    assert not v["ok"] and v.get("at_index") == 1, v

    # reordering two entries breaks at the first swapped slot
    reordered = copy.deepcopy(sealed)
    reordered["chain"][0], reordered["chain"][1] = \\
        reordered["chain"][1], reordered["chain"][0]
    v = verify(reordered)
    assert not v["ok"] and v.get("at_index") == 0, v

    # different seed -> different genesis -> everything diverges
    other = build("s-0007", ENTRIES, ARTIFACTS, seed="saturday")
    assert other["genesis"] != sealed["genesis"]
    assert verify(other)["ok"] is True

    # empty session seals to genesis-tip honestly
    empty = build("s-0000", [], [])
    assert empty["tip"] == empty["genesis"]
    assert verify(empty)["ok"] is True

    print("session-seal gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"seal_chain.py": CHAIN, "verify_sealchain.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # predecessor dropped from the link input -> membership-only
    # hashing; the delete-middle attack then verifies clean and the
    # linkage assertion goes red (independent breaker)
    "weaken_link": ("seal_chain.py",
                    'return h((prev + "|" + name + "|" + psha)'
                    '.encode("utf-8"))',
                    'return h((name + "|" + psha)'
                    '.encode("utf-8"))'),
}

BLUEPRINT = {
    "description": "VOLTAGE session-seal: linked seal chains that "
                   "prove complete order and name their first break",
    "files": FILES,
    "gate": [sys.executable, "verify_sealchain.py"],
    "faults": dict(FAULTS),
}
