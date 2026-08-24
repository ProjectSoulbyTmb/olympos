"""Verify suite for the LEARNING engine and knowledge-vault integrity.

Checks the append-only vault's invariants, de-duplication behaviour,
proposal round-trips in an isolated sandbox, and that every evidence
reader survives the real workspace (quiet streams are fine).

Run:  python verify_learning.py
Exit: 0 green, 1 any failure.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from learning.dedupe import jaccard, tokens  # noqa: E402
from learning.evidence import stream_summary  # noqa: E402
from learning.vault import Vault  # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name))
        print(f"  PASS  {name:<44} {detail}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((False, name))
        print(f"  FAIL  {name:<44} {type(exc).__name__}: {exc}")


def t_real_vault_invariants():
    v = Vault()
    data = v.load()
    lessons = data.get("lessons", [])
    assert lessons, "vault is empty"
    cats = data.get("_meta", {}).get("categories", [])
    ids = []
    for lsn in lessons:
        problems = Vault.validate_entry(lsn, cats)
        assert not problems, f"{lsn.get('id')}: {problems}"
        m = __import__("re").match(r"^L(\d+)$", lsn["id"])
        ids.append(int(m.group(1)))
    assert len(set(ids)) == len(ids), "duplicate lesson ids"
    assert ids == sorted(ids), "ids not monotonic"
    return f"{len(lessons)} lessons, next L{len(str(ids[-1]+1))}"


def t_dedupe_separates():
    a = tokens("Retry failed gates once after remediation")
    b = tokens("Retry failing gates a single time post repair")
    c = tokens("Vulkan renderer shadows flicker on metal roofs")
    ja, jb = jaccard(a, b), jaccard(a, c)
    assert ja >= 0.2, f"near-duplicates score too low: {ja:.2f}"
    assert jb <= 0.1, f"unrelated topics score too high: {jb:.2f}"
    assert ja > jb * 2
    return f"near={ja:.2f} far={jb:.2f}"


def t_proposal_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "knowledge"))
        seed = {"_meta": {"categories": ["testing", "process"]},
                "lessons": []}
        with open(os.path.join(tmp, "knowledge", "lessons.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(seed, fh)
        v = Vault(root=tmp)
        path = v.propose(
            {"title": "Always re-verify before claiming health",
             "category": "testing",
             "source": "smoke test",
             "lesson": "Claims require gates.",
             "tags": ["testing", "gates"]},
            proposed_by="metis", evidence=["verify_x:12"])
        assert os.path.exists(path)
        props = v.proposals()
        assert len(props) == 1 and props[0]["status"] == "proposed"
        bad = dict(props[0]["lesson"], category="not-a-cat")
        problems = Vault.validate_entry(bad, ["testing"])
        assert problems
    return "propose -> queue -> validate"


def t_evidence_streams_survive():
    s = stream_summary()
    assert isinstance(s, dict)
    for key in ("incidents", "zeus_audit", "health_report",
                "cycle_logs", "proposals"):
        assert key in s, f"missing stream: {key}"
    return ", ".join(f"{k}={v}" for k, v in s.items())


def main():
    print("verify_learning")
    check("real vault invariants", t_real_vault_invariants)
    check("de-duplication separates near/far", t_dedupe_separates)
    check("proposal lifecycle (sandboxed)", t_proposal_lifecycle)
    check("evidence readers survive quiet organs",
          t_evidence_streams_survive)
    failed = [n for ok, n in RESULTS if not ok]
    print(f"learning: {len(RESULTS) - len(failed)}/{len(RESULTS)} "
          "checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
