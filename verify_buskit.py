"""Verify suite for BUSKIT (envelope contract, catalogue, ledger lint).

Run:  python verify_buskit.py
Exit: 0 all green, 1 any failure. Standard library only.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from buskit import envelope as env_mod
from buskit import lint as lint_mod
from buskit.envelope import KINDS, PROFILES, TOPICS, dump, iter_lint, loads, make, stamp_seq, validate

RESULTS = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name, detail))
        print(f"  PASS  {name:<46} {detail}")
    except Exception as exc:  # noqa: BLE001 - suite reports everything
        RESULTS.append((False, name, f"{type(exc).__name__}: {exc}"))
        print(f"  FAIL  {name:<46} {type(exc).__name__}: {exc}")


def t_mailbox_roundtrip():
    env = make("incident", "vulcan", {"zone": "atrium"}, to="sentinel",
               rights="operator", error=None)
    assert validate(env) == []
    back, problems = loads(dump(env))
    assert back == env and problems == []
    return "to=sentinel ok"


def t_broadcast_roundtrip():
    env = make("build.describe", "venus", {"intent": "make a widget"},
               topic="build.request", rights="player")
    assert validate(env) == []
    back, _ = loads(dump(env))
    assert back == env
    return "topic=build.request ok"


def test_error_field_always_present():
    env = make("vital", "zeus", {"cpu": 1}, topic="vitals")
    assert "error" in env and env["error"] is None
    broken = dict(env)
    del broken["error"]
    assert any("error" in p for p in validate(broken))
    broken2 = dict(env, error=42)
    assert any("null or a string" in p for p in validate(broken2))
    return "error present, null-or-str enforced"


def t_exactly_one_target():
    base = dict(v=1, id="x", ts="2026-08-24T00:00:00", frm="zeus",
                kind="incident", rights="watcher", payload={}, error=None)
    both = dict(base, to="gaia", topic="incidents")
    assert any("exactly one" in p for p in validate(both))
    neither = dict(base)
    assert any("exactly one" in p for p in validate(neither))
    return "to/topic exclusivity enforced"


def t_unknowns_rejected():
    good = make("incident", "a", {}, to="b")
    bad_topic = dict(good, topic="nope", to=None)
    assert any("unknown topic" in p for p in validate(bad_topic))
    bad_kind = dict(make("incident", "a", {}, to="b"), kind="wat")
    assert any("unknown mailbox kind" in p for p in validate(bad_kind))
    bad_rights = dict(make("incident", "a", {}, to="b"), rights="root")
    assert any("unknown rights profile" in p for p in validate(bad_rights))
    return "topic/kind/profile gates hold"


def t_catalogue_integrity():
    assert KINDS and TOPICS
    for topic, kinds in TOPICS.items():
        assert kinds, f"{topic} has no kinds"
    assert {"incidents", "grants", "build.request"} <= set(TOPICS)
    assert len(KINDS) == len(set(KINDS)), "duplicate kinds across topics"
    return f"{len(TOPICS)} topics, {len(KINDS)} kinds"


def t_stamp_seq():
    env = make("incident", "vulcan", {}, to="sentinel")
    token = env["id"]
    stamped = stamp_seq(env, 7)
    assert stamped["id"].startswith("7-vulcan-") and token in stamped["id"]
    return f"id={stamped['id']}"


def t_strict_loads_raises():
    good = dump(make("incident", "a", {}, to="b"))
    bad = json.dumps(dict(json.loads(good), v=99))
    try:
        loads(bad, strict=True)
        raise AssertionError("strict should have raised")
    except ValueError:
        pass
    _, problems = loads(bad, strict=False)
    assert problems
    return "strict raises, lenient reports"


def _write_ledger(tmpdir):
    good = dump(make("grant.grant", "thoth",
                     {"who": "agent-7", "level": "L1"},
                     topic="grants", rights="admin"))
    badkind = dump(make("incident", "zeus", {}, to="sentinel"))
    badkind = json.dumps(dict(json.loads(badkind), kind="???"))
    path = os.path.join(tmpdir, "incidents.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(good + "\n")
        fh.write("\n")            # blank lines are skipped
        fh.write("{not json\n")   # unparseable
        fh.write(badkind + "\n")  # contract violation
    return path


def t_ledger_lint_finds_all_classes():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_ledger(tmp)
        found = list(iter_lint(path))
        nos = [no for no, _ in found]
        assert nos == [3, 4], f"expected lines 3,4 got {nos}"
        assert any("unparseable" in p for p in found[0][1])
        assert any("unknown mailbox kind" in p for p in found[1][1])
        rc = lint_mod.main([path, "--quiet"])
        assert rc == 1
        rc_clean_dir = os.path.join(tmp, "clean.jsonl")
        with open(rc_clean_dir, "w", encoding="utf-8") as fh:
            fh.write(dump(make("policy.reload", "thoth", {},
                               topic="policy.update", rights="admin")) + "\n")
        assert lint_mod.main([rc_clean_dir, "--quiet"]) == 0
    return "corrupt+violation+clean paths verified"


def t_missing_file_exit_two():
    rc = lint_mod.main(["Z:/definitely/not/here.jsonl", "--quiet"])
    assert rc == 2
    return "exit 2 on unreadable ledger"


def t_llm_attestation():
    import tempfile
    from buskit.llmlog import LLMJournal, digest, validate

    def fake_brain(prompt):
        return "echo:" + prompt

    with tempfile.TemporaryDirectory() as tmp:
        j = LLMJournal(os.path.join(tmp, "brain.jsonl"), actor="ptah")
        resp = j.attested(fake_brain, model="scripted-1",
                          prompt="design a widget")
        assert resp == "echo:design a widget"
        entries = j.entries()
        assert len(entries) == 1
        e = entries[0]
        assert validate(e) == []
        assert e["prompt_digest"] == digest("design a widget")
        assert e["response_chars"] == len(resp)

        def boom(_p):
            raise RuntimeError("offline")

        try:
            j.attested(boom, model="scripted-1", prompt="x")
            raise AssertionError("should re-raise")
        except RuntimeError:
            pass
        bad = j.entries()[-1]
        assert bad["ok"] is False and bad["error"]
        assert validate(bad) == []
    return "call + failure journaled with digests"


def main():
    print("verify_buskit")
    check("envelope mailbox round-trip", t_mailbox_roundtrip)
    check("envelope broadcast round-trip", t_broadcast_roundtrip)
    check("error field contract", test_error_field_always_present)
    check("to/topic exclusivity", t_exactly_one_target)
    check("unknown topic/kind/profile rejected", t_unknowns_rejected)
    check("catalogue integrity", t_catalogue_integrity)
    check("stamp_seq composes bus id", t_stamp_seq)
    check("loads strict/lenient", t_strict_loads_raises)
    check("ledger lint classes", t_ledger_lint_finds_all_classes)
    check("lint exit code on missing file", t_missing_file_exit_two)
    check("llm attestation journal", t_llm_attestation)
    failed = [r for r in RESULTS if not r[0]]
    print(f"buskit: {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
