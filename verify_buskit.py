"""Verify suite for BUSKIT (envelope contract, catalogue, ledger lint).

Run:  python verify_buskit.py
Exit: 0 all green, 1 any failure. Standard library only.
"""

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from buskit.llmlog import LLMJournal
from buskit.slotgen import RemoteBrain, ScriptedBrain, SlotCaller
from buskit.slotgen import SlotError, SlotSpec

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
    import os as _os
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
        # failure path is also evidence
        def boom(_p): raise RuntimeError("offline")
        try:
            j.attested(boom, model="scripted-1", prompt="x")
            raise AssertionError("should re-raise")
        except RuntimeError:
            pass
        bad = j.entries()[-1]
        assert bad["ok"] is False and bad["error"]
        assert validate(bad) == []
    return "call + failure journaled with digests"


def t_llmlog_validate_rejects():
    from buskit.llmlog import VERSION, validate

    good = {"v": VERSION, "model": "m", "prompt_digest": "d",
            "ok": True, "response_digest": "r", "response_chars": 5}
    assert validate(good) == []
    assert any("bad version" in p for p in validate(dict(good, v=99)))
    assert any("missing model" in p for p in validate(dict(good, model="")))
    assert any("missing prompt_digest" in p
               for p in validate(dict(good, prompt_digest=None)))
    assert any("failed call without error" in p
               for p in validate(dict(good, ok=False)))
    assert any("digest without length" in p
               for p in validate(dict(good, response_chars=None)))
    return "all five contract violations detected"


# ---------------------------------------------------- slotgen (forge)
def _slot_stub_brain(script):
    """Socket-free brain stub: pops replies/exceptions in order."""
    class _Stub:
        provider = "openai"

        def label(self):
            return "stub:script"

        def serve(self, spec):
            item = script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
    return _Stub()


def _slot_spec(**kw):
    base = dict(kind="function_body", name="buskit_slot",
                task="suite fixture", seed="b1")
    base.update(kw)
    return SlotSpec(**base)


def t_slotgen_scripted_render():
    b = ScriptedBrain()
    r1 = b.serve(_slot_spec())
    r2 = b.serve(_slot_spec())
    assert r1 == r2 and "buskit_slot" in r1
    cfg = json.loads(b.serve(_slot_spec(kind="config_gen",
                                        fields={"z": 1, "a": 2})))
    assert cfg["fields"] == {"a": 2, "z": 1}      # sorted, stable
    try:
        _slot_spec(kind="app_scale")              # not a slot kind
        raise AssertionError("bad kind accepted")
    except SlotError as exc:
        assert exc.kind == "bad_request"
    return "deterministic render, kinds gated"


def t_slotgen_fallback_dead_endpoint():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                       # closed port -> instant refuse
    with tempfile.TemporaryDirectory() as tmp:
        c = SlotCaller(os.path.join(tmp, "j.jsonl"),
                       [RemoteBrain(f"http://127.0.0.1:{port}/v1", "m",
                                    timeout_s=1),
                        ScriptedBrain()],
                       backoff_base_s=0.01)
        r = c.generate(_slot_spec(name="offline"))
        assert r.fell_back and r.brain == "scripted"
        kinds = {ref["kind"] for ref in r.refusals}
        assert kinds == {"network"}, kinds
        from buskit.llmlog import validate as llmlog_validate
        assert all(llmlog_validate(e) == []
                   for e in c.journal.entries())
    return "dead endpoint -> named network refusals -> scripted"


def t_slotgen_retry_jitter_reproducible():
    from buskit.slotgen import TransientError
    with tempfile.TemporaryDirectory() as tmp_a, \
            tempfile.TemporaryDirectory() as tmp_b:
        runs = []
        for tmp in (tmp_a, tmp_b):
            c = SlotCaller(os.path.join(tmp, "j.jsonl"),
                           [_slot_stub_brain([
                               TransientError("server", "boom"),
                               TransientError("server", "bam"),
                               "ok-text"]),
                            ScriptedBrain()],
                           backoff_base_s=0.02, max_attempts=3)
            res = c.generate(_slot_spec(seed="jit"))
            assert res.text == "ok-text" and res.attempts == 3
            assert len(c.last_delays) == 2
            runs.append(list(c.last_delays))
        assert runs[0] == runs[1], "seeded jitter diverged"
    return f"retries+jitter reproducible {runs[0]}"


def t_slotgen_breaker_lifecycle():
    br = RemoteBrain("http://127.0.0.1:9/v1", "m", trip_after=2,
                     cool_down_s=0.15)
    assert br.state == "closed"
    br._record(False)
    assert br.state == "closed"
    br._record(False)
    assert br.state == "open"                    # tripped
    try:
        br.serve(_slot_spec())                   # short-circuit refusal
        raise AssertionError("open breaker served")
    except SlotError as exc:
        assert exc.kind == "breaker_open"
    time.sleep(0.17)
    assert br.state == "half_open"
    br._record(True)
    assert br.state == "closed" and br.failures == 0
    return "closed->open->half_open->closed, visible throughout"


def t_slotgen_transport_and_caps():
    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):                       # noqa: N802
            self.rfile.read(int(self.headers.get("content-length", 0)))
            code, payload = self.server.script.pop(0)
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    srv.script = [
        (200, completion_remote("remote-wins")),
        (500, {}), (500, {}), (200, completion_remote("after-retry")),
        (401, {}),
        (200, completion_remote("x" * 6000)),
        (200, {}),
    ]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            jp = os.path.join(tmp, "j.jsonl")

            def fresh():
                return SlotCaller(
                    jp, [RemoteBrain(url, "m", timeout_s=5),
                         ScriptedBrain()],
                    backoff_base_s=0.01)

            r1 = fresh().generate(_slot_spec(name="t1"))
            assert r1.brain.startswith("remote:")
            r2 = fresh().generate(_slot_spec(name="t2"))
            assert r2.brain.startswith("remote:") and                 r2.attempts == 3
            r3 = fresh().generate(_slot_spec(name="t3"))   # 401 fatal
            assert r3.fell_back and any(
                ref["kind"] == "auth" for ref in r3.refusals)
            r4 = fresh().generate(_slot_spec(name="t4",
                                             max_chars=1000))
            assert r4.fell_back and any(
                ref["kind"] == "slot_too_large"
                for ref in r4.refusals) and len(r4.text) < 1000
            r5 = fresh().generate(_slot_spec(name="t5"))   # malformed
            assert r5.fell_back and any(
                ref["kind"] == "bad_response"
                for ref in r5.refusals)
            from buskit.llmlog import validate as llmlog_validate
            assert all(llmlog_validate(e) == []
                       for e in LLMJournal(jp).entries())
        return ("transport classes: ok/retry/auth-fatal/oversize/"
                "malformed all journaled")
    finally:
        srv.shutdown()
        srv.server_close()


def completion_remote(text):
    return {"choices": [{"message": {"content": text}}], "usage": {}}


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
    check("llmlog validate contract", t_llmlog_validate_rejects)
    check("slotgen scripted render", t_slotgen_scripted_render)
    check("slotgen dead-endpoint fallback", t_slotgen_fallback_dead_endpoint)
    check("slotgen retry/jitter reproducible",
          t_slotgen_retry_jitter_reproducible)
    check("slotgen breaker lifecycle", t_slotgen_breaker_lifecycle)
    check("slotgen transport classes + caps",
          t_slotgen_transport_and_caps)
    failed = [r for r in RESULTS if not r[0]]
    print(f"buskit: {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
