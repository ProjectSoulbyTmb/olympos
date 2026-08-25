"""Verify suite for RELAY - the daedalus<->venus bridges.

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

Run:  python relay/verify_relay.py      Exit: 0 green / 1 red.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)
sys.path.insert(0, WORKSPACE)

from ratatosk.bus import Post                 # noqa: E402
from buskit.envelope import TOPICS            # noqa: E402

from relay import content                     # noqa: E402
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
    """A relay wired to a throwaway post office + intent lanes."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="relay-verify-")
        self.post = Post(root=os.path.join(self.tmp, "post"))
        self.intent_dir = os.path.join(self.tmp, "to-fleet")
        self.mind_dir = os.path.join(self.tmp, "from-mind")
        self._saved = (content.INTENT_DIR, content.INTENT_DONE,
                       content.INTENT_FAILED, content.WORKSPACE,
                       content.MIND_INTENT_DIR, content.MIND_DONE,
                       content.MIND_FAILED, content.MIND_DEDUPE_LEDGER)
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

    def restore(self):
        (content.INTENT_DIR, content.INTENT_DONE,
         content.INTENT_FAILED, content.WORKSPACE,
         content.MIND_INTENT_DIR, content.MIND_DONE,
         content.MIND_FAILED, content.MIND_DEDUPE_LEDGER) = self._saved

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
        (content.INTENT_DIR, content.INTENT_DONE,
         content.INTENT_FAILED, content.WORKSPACE,
         content.MIND_INTENT_DIR, content.MIND_DONE,
         content.MIND_FAILED, content.MIND_DEDUPE_LEDGER) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)


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
    failed = [n for ok, n in RESULTS if not ok]
    print(f"relay: {len(RESULTS) - len(failed)}/{len(RESULTS)} "
          "checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
