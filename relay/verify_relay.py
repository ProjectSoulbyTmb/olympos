"""Verify suite for RELAY - the daedalus<->venus<->riley bridges.

Proves the seams, not the organs (those have their own suites):

  R1 forward ............ daedalus topic records reach `updates` AND
                          the venus mailbox exactly-once; a restarted
                          relay replays nothing (persistent cursors)
  R2 intents ............ build intents execute once through the
                          runner, file to done/, outcome lands on
                          `updates`; malformed intents quarantine to
                          failed/ without killing the loop
  R3 stream ............. tick() publishes a fleet.tick carrying the
                          doctor verdict summary and beats the organ
  R4 contract ........... every produced record is buskit-catalogue
                          legal (kind allowed on its topic)
  R5 cli ................ python -m relay status exits green against
                          a scratch post office
  R6 work stream ........ nymph-hunter verdicts queue seeded render
                          orders at the studio exactly-once; restart
                          replays nothing; foreign builds never dial
  R7 spool .............. a dark studio parks orders in pending/
                          silently; once the studio answers, retries
                          land, file to sent/ and publish fleet.render
  R8 refusal + seeds .... permanent refusals file to rejected/ without
                          retry storms; seeds derive deterministically
                          from the workshop job id

Run:  python relay/verify_relay.py      Exit: 0 green / 1 red.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)
sys.path.insert(0, WORKSPACE)

from ratatosk.bus import Post                 # noqa: E402
from buskit.envelope import TOPICS            # noqa: E402

from relay import content, riley_stream       # noqa: E402
from relay.bridge import Relay                # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name))
        print(f"  PASS  {name:<44} {detail}")
    except Exception as exc:                  # noqa: BLE001 - evidence
        RESULTS.append((False, name))
        print(f"  FAIL  {name:<44} {type(exc).__name__}: {exc}")


class ScratchFleet:
    """A relay wired to a throwaway post office + intent lanes + a
    dark studio (no order ever dials the real RILEY here)."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="relay-verify-")
        self.post = Post(root=os.path.join(self.tmp, "post"))
        self.intent_dir = os.path.join(self.tmp, "to-fleet")
        self.mind_dir = os.path.join(self.tmp, "from-mind")
        riley_root = os.path.join(self.tmp, "riley-spool")
        self._saved = (content.INTENT_DIR, content.INTENT_DONE,
                       content.INTENT_FAILED, content.WORKSPACE,
                       content.MIND_INTENT_DIR, content.MIND_DONE,
                       content.MIND_FAILED, content.MIND_DEDUPE_LEDGER,
                       content.RILEY_URL, content.RILEY_PENDING_DIR,
                       content.RILEY_SENT_DIR, content.RILEY_REJECTED_DIR,
                       content.RILEY_CURSOR)
        content.INTENT_DIR = self.intent_dir
        content.INTENT_DONE = os.path.join(self.intent_dir, "done")
        content.INTENT_FAILED = os.path.join(self.intent_dir, "failed")
        content.WORKSPACE = self.tmp
        content.MIND_INTENT_DIR = self.mind_dir
        content.MIND_DONE = os.path.join(self.mind_dir, "done")
        content.MIND_FAILED = os.path.join(self.mind_dir, "failed")
        # hermetic dedupe ledger: mind tests must never read or write
        # the real relay/data/mind_seen.json (a polluted ledger turns
        # fresh intents into "duplicate ignored" and skips the runner)
        content.MIND_DEDUPE_LEDGER = os.path.join(self.tmp,
                                                  "mind_seen.json")
        # port 9 (discard): refused instantly - a dark studio default
        content.RILEY_URL = "http://127.0.0.1:9"
        content.RILEY_PENDING_DIR = os.path.join(riley_root, "pending")
        content.RILEY_SENT_DIR = os.path.join(riley_root, "sent")
        content.RILEY_REJECTED_DIR = os.path.join(riley_root, "rejected")
        content.RILEY_CURSOR = os.path.join(riley_root, "jobs.cursor")

    def restore(self):
        (content.INTENT_DIR, content.INTENT_DONE,
         content.INTENT_FAILED, content.WORKSPACE,
         content.MIND_INTENT_DIR, content.MIND_DONE,
         content.MIND_FAILED, content.MIND_DEDUPE_LEDGER,
         content.RILEY_URL, content.RILEY_PENDING_DIR,
         content.RILEY_SENT_DIR, content.RILEY_REJECTED_DIR,
         content.RILEY_CURSOR) = self._saved

    def write_intent(self, body):
        os.makedirs(self.intent_dir, exist_ok=True)
        name = f"{body.get('id', 'i')}.intent.json"
        with open(os.path.join(self.intent_dir, name), "w",
                  encoding="utf-8") as fh:
            json.dump(body, fh)
        return name

    def write_mind_intent(self, body):
        os.makedirs(self.mind_dir, exist_ok=True)
        name = f"mind-{body.get('id', 'i')}.intent.json"
        with open(os.path.join(self.mind_dir, name), "w",
                  encoding="utf-8") as fh:
            json.dump(body, fh)
        return name

    def close(self):
        self.restore()
        shutil.rmtree(self.tmp, ignore_errors=True)


class StubRiley:
    """A loopback stand-in for the studio's job API on an ephemeral
    port. Records every POST; `code` scripts the verdict."""

    def __init__(self, code=200, jobs=None):
        self.code = code
        self.hits = []
        self.jobs = jobs or []                  # GET /api/jobs payload
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):                   # noqa: N802
                part = urlsplit(self.path)
                body = json.dumps({
                    "ok": True, "error": None,
                    "data": {"items": outer.jobs}},
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):                  # noqa: N802
                part = urlsplit(self.path)
                outer.hits.append({
                    "path": part.path,
                    "qs": {k: v[0]
                           for k, v in parse_qs(part.query).items()},
                })
                body = json.dumps({
                    "ok": outer.code == 200,
                    "error": None if outer.code == 200 else "refused",
                    "data": {"id": f"j{len(outer.hits)}"}},
                ).encode("utf-8")
                self.send_response(outer.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever,
                         daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


# ------------------------------------------------------------------ R1

def t_forward_exactly_once():
    fleet = ScratchFleet()
    try:
        for i in range(3):
            fleet.post.broadcast("daedalus", "build",
                                 {"id": f"job{i}", "blueprint": "b"},
                                 frm="daedalus")
        r = Relay(post=fleet.post)
        assert r.forward_daedalus() == 3
        letters = fleet.post.read(content.MAILBOX)
        assert len(letters) == 3, f"mailbox got {len(letters)}"
        ticks = fleet.post.since(content.TOPIC, "audit")
        assert len(ticks) == 3, f"topic got {len(ticks)}"

        # restart: same cursors, zero duplicates
        r2 = Relay(post=fleet.post)
        assert r2.forward_daedalus() == 0
        assert len(fleet.post.since(content.TOPIC, "audit")) == 0
    finally:
        fleet.close()
    return "3 forwarded once; restart forwards nothing"


def t_forward_marks_failures():
    fleet = ScratchFleet()
    try:
        fleet.post.broadcast("daedalus", "build-failed",
                             {"id": "job9", "blueprint": "b",
                              "error": "boom"}, frm="daedalus")
        r = Relay(post=fleet.post)
        r.forward_daedalus()
        letters = fleet.post.read(content.MAILBOX)
        assert letters[0]["payload"]["ok"] is False
        assert letters[0]["payload"]["source"] == "daedalus"
    finally:
        fleet.close()
    return "build-failed relays with ok=false"


# ------------------------------------------------------------------ R2

def t_intents_execute_and_file():
    fleet = ScratchFleet()
    try:
        ran = []

        def runner(intent):
            ran.append(intent["type"])
            return intent.get("type") != "explode", "ran"

        r = Relay(post=fleet.post, runner=runner)
        fleet.write_intent({"id": "a", "type": "build",
                            "blueprint": "jsonl-echo"})
        fleet.write_intent({"id": "bad", "type": "explode"})
        fleet.write_intent({"raw": [1, 2]})          # no type -> quarantine
        out = r.drain_intents()
        assert len(out) == 3, out
        # every typed intent reaches the runner; the typeless one does not
        assert "build" in ran and "explode" in ran, ran
        done = os.listdir(content.INTENT_DONE)
        failed = os.listdir(content.INTENT_FAILED)
        assert len(done) == 1 and len(failed) == 2, (done, failed)
        filed = json.load(open(os.path.join(content.INTENT_DONE,
                                            done[0]), encoding="utf-8"))
        assert filed["outcome"] == {"ok": True, "detail": "ran"}
        kinds = [rec["kind"] for rec in
                 fleet.post.since(content.TOPIC, "audit")]
        assert "fleet.build" in kinds, kinds
        # drained lane is empty; second pass is a no-op
        assert not [n for n in os.listdir(content.INTENT_DIR)
                    if n.endswith(".intent.json")]
        assert r.drain_intents() == []
    finally:
        fleet.close()
    return "executed once, filed done/failed, outcomes published"


# ------------------------------------------------------------------ R3

def t_tick_streams_verdict():
    fleet = ScratchFleet()
    try:
        os.makedirs(os.path.join(fleet.tmp, "data"), exist_ok=True)
        with open(os.path.join(fleet.tmp, "data", "health_report.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"mode": "ci", "fail": 0, "fixed": 1, "warn": 0,
                       "checks": [{"check": "g", "status": "pass"}]}, fh)
        r = Relay(post=fleet.post)
        payload = r.tick()
        assert payload["gates"]["fail"] == 0
        assert payload["lanes"] is None or isinstance(payload["lanes"],
                                                      dict)
        recs = fleet.post.since(content.TOPIC, "audit")
        assert recs and recs[-1]["kind"] == "fleet.tick"
        age = fleet.post.heartbeat_age(content.ORGAN)
        assert age is not None, "organ did not beat"
    finally:
        fleet.close()
    return "fleet.tick carries gate verdict + heartbeat"


# ------------------------------------------------------------------ R4

def t_catalogue_contract():
    fleet = ScratchFleet()
    try:
        r = Relay(post=fleet.post)

        def runner(intent):
            return True, "ok"

        r.runner = runner
        fleet.post.broadcast("daedalus", "build",
                             {"id": "j", "blueprint": "b"},
                             frm="daedalus")
        fleet.write_intent({"id": "c1", "type": "build"})
        fleet.write_intent({"id": "c2", "type": "repair"})
        r.run_cycle()
        allowed = TOPICS[content.TOPIC]
        for rec in fleet.post.since(content.TOPIC, "audit"):
            assert rec["kind"] in allowed, \
                f"{rec['kind']} not legal on {content.TOPIC}"
            assert rec["payload"].get("at"), "records must timestamp"
    finally:
        fleet.close()
    return "every record kind is catalogue-legal on 'updates'"


# ------------------------------------------------------------------ R5

def t_cli_status():
    env = dict(os.environ)
    scratch = tempfile.mkdtemp(prefix="relay-cli-")
    env["RATATOSK_ROOT"] = os.path.join(scratch, "post")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "relay", "status"],
            capture_output=True, text=True, timeout=30,
            cwd=WORKSPACE, env=env)
        assert proc.returncode == 0, proc.stderr[-300:]
        body = json.loads(proc.stdout)
        assert body["topic"] == "updates"
        assert body["mailbox"] == content.MAILBOX
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return "status reports topic/mailbox/lane counts"


def t_mind_intents_roundtrip():
    fleet = ScratchFleet()
    try:
        ran = []

        def runner(intent):
            ran.append(intent["type"])
            return True, "mind-ok"

        r = Relay(post=fleet.post, runner=runner)
        fleet.write_mind_intent({"id": "m1", "type": "build",
                                 "blueprint": "jsonl-echo"})
        fleet.write_mind_intent({"raw": 1})            # malformed
        out = r.drain_mind_intents()
        assert len(out) == 2, out
        done = os.listdir(content.MIND_DONE)
        failed = os.listdir(content.MIND_FAILED)
        assert len(done) == 1 and len(failed) == 1, (done, failed)
        # reply letters land in the mind mailbox with correlation id
        replies = [l for l in fleet.post.read(content.MIND_MAILBOX)
                   if l.get("kind") == "fleet.reply"]
        assert any(r_.get("payload", {}).get("intent") == "m1"
                   for r_ in replies), replies
        # venus lane untouched by mind traffic
        assert not [n for n in os.listdir(content.INTENT_DIR)
                    if n.endswith(".intent.json")] if os.path.isdir(
                        content.INTENT_DIR) else True
        return "mind intent executed; reply correlated; malformed filed"
    finally:
        shutil.rmtree(fleet.tmp, ignore_errors=True)
        fleet.close()


def t_mind_knowledge_intent():
    fleet = ScratchFleet()
    try:
        # minimal corpus so the knowledge engine has something to say
        lib = os.path.join(fleet.tmp, "knowledge", "library")
        os.makedirs(lib, exist_ok=True)
        with open(os.path.join(lib, "alpha.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("# Alpha Doctrine\n\nThe alpha protocol requires "
                     "a confirmation gate before every destructive act.\n")
        engine = os.path.join(fleet.tmp, "knowledge", "engine.py")
        src = os.path.join(WORKSPACE, "knowledge", "engine.py")
        shutil.copyfile(src, engine)

        r = Relay(post=fleet.post)                 # real runner path
        fleet.write_mind_intent({"id": "k1", "type": "knowledge",
                                 "query": "alpha protocol confirmation"})
        out = r.drain_mind_intents()
        assert len(out) == 1 and out[0][1] is True, out
        replies = [l for l in fleet.post.read(content.MIND_MAILBOX)
                   if l.get("kind") == "fleet.reply"]
        blob = json.dumps(replies)
        assert "Alpha Doctrine" in blob or "alpha" in blob, blob[:300]
        return "knowledge intent answered from library corpus"
    finally:
        shutil.rmtree(fleet.tmp, ignore_errors=True)
        fleet.close()


def t_mind_priority_cap():
    fleet = ScratchFleet()
    try:
        ran = []
        def runner(intent):
            ran.append(intent.get("id"))
            return True, "ok"
        r = Relay(post=fleet.post, runner=runner)
        for i in range(30):
            fleet.write_mind_intent({"id": f"n{i:02d}", "type": "status"})
        fleet.write_mind_intent({"id": "urgent", "type": "status",
                                 "urgent": True})
        out = r.drain_mind_intents()
        assert len(out) == 25, len(out)          # cap 25 per cycle
        assert ran[0] == "urgent", ran[:3]       # urgent jumps the queue
        pending = [n for n in os.listdir(content.MIND_INTENT_DIR)
                   if n.endswith(".intent.json")]
        assert len(pending) == 6, len(pending)   # 31 - 25 overflow
        out2 = r.drain_mind_intents()            # next pass drains rest
        assert len(out2) == 6, len(out2)
        return "urgent first; cap honoured; overflow queued"
    finally:
        fleet.close()


def t_mind_stale_ttl():
    import time as _t
    fleet = ScratchFleet()
    try:
        ran = []
        old_iso = time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00",
            _t.gmtime(_t.time() - content.MIND_INTENT_TTL_S - 60))
        fresh_id = "fresh1"
        def runner(intent):
            ran.append(intent["id"])
            return True, "ran"
        r = Relay(post=fleet.post, runner=runner)
        fleet.write_mind_intent({"id": "old1", "type": "status",
                                 "ts": old_iso})
        fleet.write_mind_intent({"id": fresh_id, "type": "status"})
        out = r.drain_mind_intents()
        by_id = {n.split("-")[0]: ok for n, ok, _d in out}
        assert ran == [fresh_id], ran
        failed = os.listdir(content.MIND_FAILED)
        assert any("old1" in n for n in failed), failed
        filed = json.load(open(os.path.join(content.MIND_FAILED,
                                            [n for n in failed
                                             if "old1" in n][0]),
                               encoding="utf-8"))
        assert "expired" in filed["error"], filed
        return "stale intent expired unrun; fresh executed"
    finally:
        fleet.close()


def t_mind_dedupe():
    fleet = ScratchFleet()
    try:
        # point the ledger at scratch so the suite never touches real data
        content.MIND_DEDUPE_LEDGER = os.path.join(fleet.tmp,
                                                  "mind_seen.json")
        calls = []
        def runner(intent):
            calls.append(intent.get("id"))
            return True, "executed"
        r = Relay(post=fleet.post, runner=runner)
        body = {"id": "dup9", "type": "status"}
        fleet.write_mind_intent(body)
        first = r.drain_mind_intents()
        assert len(first) == 1 and first[0][1] is True
        fleet.write_mind_intent(body)                # crash-replayed id
        second = r.drain_mind_intents()
        assert len(second) == 1 and second[0][1] is True
        assert second[0][2] == "duplicate ignored", second
        assert calls == ["dup9"], calls              # runner ran once
        replies = [l for l in fleet.post.read(content.MIND_MAILBOX)
                   if l.get("kind") == "fleet.reply"]
        assert len(replies) == 2                     # acked both times
        return "runner once; replay acknowledged with duplicate note"
    finally:
        fleet.close()


def t_mind_subscriptions():
    fleet = ScratchFleet()
    try:
        sub_path = content.MIND_SUBSCRIPTIONS
        os.makedirs(os.path.dirname(sub_path), exist_ok=True)
        with open(sub_path, "w", encoding="utf-8") as fh:
            json.dump({"all": False, "kinds": ["fleet.build"]}, fh)
        r = Relay(post=fleet.post,
                  runner=lambda i: (True, "ok"))
        fleet.write_intent({"id": "v-build", "type": "build",
                            "blueprint": "jsonl-echo"})
        r.run_cycle()                                 # build + tick
        mind_kinds = [l.get("kind")
                      for l in fleet.post.read(content.MIND_MAILBOX)]
        assert "fleet.build" in mind_kinds, mind_kinds
        assert "fleet.tick" not in mind_kinds, mind_kinds
        os.unlink(sub_path)
        return "subscription filter gates the mind mirror"
    finally:
        fleet.close()


# ------------------------------------------------------------------ R6

def t_riley_stream_orders_proofs():
    fleet = ScratchFleet()
    stub = StubRiley()
    content.RILEY_URL = stub.url
    try:
        p = fleet.post
        p.broadcast("daedalus", "build",
                    {"id": "nymph-daphne-a1b2c3",
                     "blueprint": "nymph-hunter"}, frm="daedalus")
        p.broadcast("daedalus", "build-failed",
                    {"id": "nymph-maera-d4e5f6",
                     "blueprint": "nymph-hunter", "error": "blind"},
                    frm="daedalus")
        p.broadcast("daedalus", "build",
                    {"id": "web1-abc999", "blueprint": "jsonl-echo"},
                    frm="daedalus")            # foreign - must never dial
        r = Relay(post=p)
        out = r.riley.stream()
        assert out == {"queued": 2, "retried": 0}, out
        assert len(stub.hits) == 2, stub.hits
        by_seed = {h["qs"]["seed"]: h for h in stub.hits}
        green = [h for h in stub.hits if h["qs"]["count"] == "1"]
        red = [h for h in stub.hits if h["qs"]["count"] ==
               str(content.RED_VARIANTS)]
        assert len(green) == 1 and len(red) == 1, stub.hits
        assert green[0]["qs"]["style"] == content.NYMPH_STYLES["daphne"]
        assert red[0]["qs"]["style"] == content.NYMPH_STYLES["maera"]
        assert all(h["path"] == "/api/jobs" for h in stub.hits)
        assert set(by_seed) == {
            str(order["seed"]) for order in
            (riley_stream.order_for("daphne", True, "nymph-daphne-a1b2c3"),
             riley_stream.order_for("maera", False, "nymph-maera-d4e5f6"))}
        sent = os.listdir(content.RILEY_SENT_DIR)
        assert len(sent) == 2, sent
        filed = json.load(open(os.path.join(content.RILEY_SENT_DIR,
                                            sent[0]), encoding="utf-8"))
        assert filed["outcome"]["state"] == "sent", filed
        renders = [l for l in p.read(content.MAILBOX)
                   if l.get("kind") == "fleet.render"]
        assert len(renders) == 2, renders
        assert {l["payload"]["verdict"] for l in renders} == \
            {"green", "red"}

        # restart: same cursor, zero duplicate dials
        r2 = Relay(post=p)
        assert r2.riley.stream() == {"queued": 0, "retried": 0}
        assert len(stub.hits) == 2, "restart replayed orders"
    finally:
        stub.close()
        fleet.close()
    return "green+red nymph verdicts ordered once; foreign never dialed"


# ------------------------------------------------------------------ R7

def t_riley_spool_retries_when_dark():
    fleet = ScratchFleet()             # studio stays dark here (port 9)
    try:
        p = fleet.post
        p.broadcast("daedalus", "build",
                    {"id": "nymph-arethusa-0f1e2d",
                     "blueprint": "nymph-hunter"}, frm="daedalus")
        r = Relay(post=p)
        out = r.riley.stream()
        assert out == {"queued": 1, "retried": 0}, out
        pending = os.listdir(content.RILEY_PENDING_DIR)
        assert len(pending) == 1, pending          # parked, not lost
        assert not [l for l in p.read(content.MAILBOX)
                    if l.get("kind") == "fleet.render"], \
            "dark studio must stay silent"

        # the studio wakes up; the next pass delivers the parked order
        stub = StubRiley()
        try:
            content.RILEY_URL = stub.url
            out2 = r.riley.stream()
            assert out2 == {"queued": 0, "retried": 1}, out2
            assert len(stub.hits) == 1, stub.hits
            assert os.listdir(content.RILEY_PENDING_DIR) == []
            sent = os.listdir(content.RILEY_SENT_DIR)
            assert len(sent) == 1, sent
            renders = [l for l in p.read(content.MAILBOX)
                       if l.get("kind") == "fleet.render"]
            assert len(renders) == 1 and renders[0]["payload"]["ok"], \
                renders
        finally:
            stub.close()
    finally:
        fleet.close()
    return "dark studio parks silently; wake-up delivers exactly once"


# ------------------------------------------------------------------ R8

def t_riley_refusal_and_seed_determinism():
    fleet = ScratchFleet()
    stub = StubRiley(code=400)         # the studio validates and refuses
    content.RILEY_URL = stub.url
    try:
        # seeds: deterministic per job id, distinct across job ids
        a1 = riley_stream.order_for("daphne", True, "nymph-daphne-a1b2c3")
        a2 = riley_stream.order_for("daphne", True, "nymph-daphne-a1b2c3")
        assert a1 == a2, "same job id must render identically"
        assert a1["seed"] != riley_stream.order_for(
            "daphne", True, "nymph-daphne-ffffff")["seed"]
        unknown = riley_stream.order_for("echo", True, "nymph-echo-x1y2z3")
        assert unknown["params"]["style"] == \
            content.NYMPH_DEFAULT_STYLE, unknown

        p = fleet.post
        p.broadcast("daedalus", "build",
                    {"id": "nymph-taygete-77aa77",
                     "blueprint": "nymph-hunter"}, frm="daedalus")
        r = Relay(post=p)
        out = r.riley.stream()
        assert out == {"queued": 1, "retried": 0}, out
        rejected = os.listdir(content.RILEY_REJECTED_DIR)
        assert len(rejected) == 1, rejected
        filed = json.load(open(os.path.join(content.RILEY_REJECTED_DIR,
                                            rejected[0]),
                               encoding="utf-8"))
        assert filed["outcome"] == {"state": "rejected",
                                    "detail": "refused"}, filed
        assert os.listdir(content.RILEY_PENDING_DIR) == [], \
            "refusals must not retry"

        # second pass: no retry storm, no duplicate letters
        assert r.riley.stream() == {"queued": 0, "retried": 0}
        renders = [l for l in p.read(content.MAILBOX)
                   if l.get("kind") == "fleet.render"]
        assert len(renders) == 1 and not renders[0]["payload"]["ok"], \
            renders
        assert renders[0]["payload"]["state"] == "rejected"
        allowed = TOPICS[content.TOPIC]
        for rec in p.since(content.TOPIC, "audit"):
            if rec["kind"] == "fleet.render":
                assert rec["payload"].get("at"), "records must timestamp"
                assert rec["kind"] in allowed
    finally:
        stub.close()
        fleet.close()
    return "400 files rejected without retry; seeds deterministic"


def t_completions_announce_once():
    """First encounter baselines silently; later done jobs announce
    exactly once; failed/empty jobs never announce."""
    fleet = ScratchFleet()

    def read_cursor():
        with open(content.RILEY_CURSOR, encoding="utf-8") as fh:
            return int(fh.read().strip())

    stub = StubRiley(jobs=[
        {"id": "j1", "kind": "img.art", "engine": "render",
         "status": "done", "out": ["riley-a.png", "riley-a.riley.json"]},
        {"id": "j2", "kind": "vid.art", "engine": "render",
         "status": "running", "out": []},
        {"id": "j3", "kind": "chain", "engine": "pipeline",
         "status": "error", "out": [], "error": "boom"},
        {"id": "j7", "kind": "img.filter", "engine": "render",
         "status": "done", "out": ["warm-x.png"]},
    ])
    content.RILEY_URL = stub.url
    p = fleet.post
    try:
        s = riley_stream.RileyStream(post=p)
        # first encounter with an established studio = silent baseline
        assert s.completions() == 0, "baseline pass must not announce"
        assert os.path.isfile(content.RILEY_CURSOR), "cursor must persist"
        assert read_cursor() == 7

        done = {l["payload"]["job"]: l for l in p.read(content.MAILBOX)
                if l.get("kind") == content.KIND_RENDER_DONE}
        assert not done, f"baseline leaked {sorted(done)}"

        # a later job lands and is announced from the cursor
        stub.jobs.append({"id": "j9", "kind": "vid.gif", "status": "done",
                          "out": ["clip.gif"]})
        assert s.completions() == 1
        late = [l for l in p.read(content.MAILBOX)
                if l.get("kind") == content.KIND_RENDER_DONE]
        assert len(late) == 1 and late[0]["payload"]["job"] == "j9"

        # replay announces nothing new
        assert s.completions() == 0
    finally:
        stub.close()
        fleet.close()
    return "done jobs announce once above cursor; dark studio silent"


def t_completions_dark_studio():
    """Refused connections cost nothing: zero announced, no raise."""
    fleet = ScratchFleet()                  # default URL = port 9 (dark)
    try:
        s = riley_stream.RileyStream(post=fleet.post)
        assert s.completions() == 0
        assert not os.path.exists(content.RILEY_CURSOR)
    finally:
        fleet.close()
    return "dark studio -> silence, no cursor written"


def main():
    print("verify_relay")
    check("forward exactly-once across restart", t_forward_exactly_once)
    check("failures relay with ok=false", t_forward_marks_failures)
    check("intents execute, file and publish", t_intents_execute_and_file)
    check("mind intents roundtrip + correlated replies",
          t_mind_intents_roundtrip)
    check("mind knowledge intent answers from library",
          t_mind_knowledge_intent)
    check("mind priority, cap and overflow queue", t_mind_priority_cap)
    check("mind stale intents expire unrun", t_mind_stale_ttl)
    check("mind duplicate ids acknowledge once-run", t_mind_dedupe)
    check("mind subscription filter gates the mirror",
          t_mind_subscriptions)
    check("constant stream carries verdicts", t_tick_streams_verdict)
    check("buskit catalogue discipline", t_catalogue_contract)
    check("cli status green on scratch bus", t_cli_status)
    check("completions announce exactly-once above cursor",
          t_completions_announce_once)
    check("completions stay silent on a dark studio",
          t_completions_dark_studio)
    check("work stream orders nymph proofs exactly-once",
          t_riley_stream_orders_proofs)
    check("spool parks through a dark studio, delivers on wake",
          t_riley_spool_retries_when_dark)
    check("refusals file without retry; seeds deterministic",
          t_riley_refusal_and_seed_determinism)
    failed = [n for ok, n in RESULTS if not ok]
    print(f"relay: {len(RESULTS) - len(failed)}/{len(RESULTS)} "
          "checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
