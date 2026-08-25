"""RELAY - stable bridges between DAEDELUS, VENUS and RILEY.

One organ owns every crossing between the workshop (DAEDALUS), the
operator's face (VENUS) and the studio (RILEY):

  outbound (fleet -> Venus)
    forward_daedalus() relays the workshop's build/build-failed topic
    records onto the `updates` topic and into the `venus` mailbox -
    exactly-once, crash-tolerant, via ratatosk's persistent seq cursors.
    tick() appends the constant update stream: gate verdicts from the
    last doctor run, lane occupancy, heartbeats.

  inbound (Venus -> fleet)
    drain_intents() claims JSON intent files from
    assistant/data/relay/to-fleet/ (Venus is the only writer there,
    relay the only consumer), executes them - commission a build,
    run a repair sweep, answer a status probe - files them under
    done/ or failed/, and broadcasts the outcome on `updates`.

  work stream (workshop -> studio)
    riley.stream() consumes nymph-hunter build verdicts under their own
    cursor and queues a seeded proof-card render per retinue nymph in
    the RILEY studio's loopback job queue (see riley_stream.py).

Everything rides the ratatosk filesystem bus: no ports, no sockets,
restart-safe (the RILEY lane dials the studio's own loopback HTTP API
- that port belongs to RILEY, not to the bus). Envelope discipline is
buskit's contract; the suite in verify_relay.py proves each seam
including restart replay.

CLI:  python -m relay once | watch [--every S] | status |
      send --type build --blueprint jsonl-echo [--name web1] |
      send --type repair [--note why] |
      riley [--status]
"""

import json
import os
import subprocess
import sys
import time

from ratatosk.bus import Post

from . import content
from .riley_stream import RileyStream


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Relay:
    """The bridge. All state lives in ratatosk cursors and the
    intent lane's directory moves - a killed daemon resumes with no
    duplicates and no gaps."""

    def __init__(self, post=None, runner=None):
        self.post = post if post is not None else Post()
        # runner(spec_dict) -> (ok, detail): swappable for tests and
        # for callers that want builds executed in-process.
        self.runner = runner if runner is not None else _run_intent
        # the studio work stream shares this post office (own cursor)
        self.riley = RileyStream(post=self.post)

    # ---------------- outbound ----------------

    def _emit(self, kind, payload):
        """One catalogue-legal broadcast + mailbox mirrors (venus+mind)."""
        self.post.broadcast(content.TOPIC, kind, payload,
                            frm=content.ORGAN)
        for box in (content.MAILBOX, content.MIND_MAILBOX):
            try:
                self.post.send(box, kind, payload, frm=content.ORGAN)
            except Exception:
                pass                  # mirrors are best-effort; topic rules

    def forward_daedalus(self, limit=100):
        """Daedalus -> updates/venus, exactly-once per seq cursor."""
        recs = self.post.since("daedalus", "relay", limit=limit)
        forwarded = 0
        for rec in recs:
            ok = rec.get("kind") != "build-failed"
            self._emit(content.KIND_BUILD, {
                "source": "daedalus",
                "ok": bool(ok),
                "job": rec.get("payload", {}).get("id"),
                "blueprint": rec.get("payload", {}).get("blueprint"),
                "at": rec.get("ts") or _iso(),
            })
            forwarded += 1
        return forwarded

    def tick(self):
        """The constant update stream: one heartbeat record carrying
        the fleet's proof-of-life. Never raises."""
        report = _read_json(os.path.join(content.WORKSPACE,
                                         content.REPORT_PATH)) or {}
        red = [c.get("check") for c in report.get("checks", [])
               if c.get("status") == "fail"]
        lanes = _daedalus_lanes()
        payload = {
            "at": _iso(),
            "gates": {"fail": report.get("fail"),
                      "fixed": report.get("fixed"),
                      "warn": report.get("warn"),
                      "red": red},
            "lanes": lanes,
            "mode": report.get("mode"),
        }
        self._emit(content.KIND_TICK, payload)
        try:
            self.post.beat(content.ORGAN, note="tick")
        except Exception:
            pass
        return payload

    # ---------------- inbound ----------------

    def drain_intents(self, limit=25):
        """Claim, execute and file every pending Venus intent."""
        return self._drain_dir(content.INTENT_DIR, content.INTENT_DONE,
                               content.INTENT_FAILED, "venus-intent",
                               self.runner, limit)

    def drain_mind_intents(self, limit=25):
        """Claim, execute and file every pending MIND intent.

        Mirrors the venus lane; every outcome is additionally answered
        back into the `mind` mailbox as a fleet.reply record carrying
        the intent id so the mind layer can correlate requests.
        """
        return self._drain_dir(content.MIND_INTENT_DIR, content.MIND_DONE,
                               content.MIND_FAILED, "mind-intent",
                               self.runner, limit,
                               reply_box=content.MIND_MAILBOX)

    def _drain_dir(self, intent_dir, done_dir, failed_dir, source,
                   runner, limit, reply_box=None):
        out = []
        os.makedirs(intent_dir, exist_ok=True)
        names = sorted(n for n in os.listdir(intent_dir)
                       if n.endswith(".intent.json"))
        for name in names[:max(0, limit)]:
            src = os.path.join(intent_dir, name)
            intent = _read_json(src)
            if not isinstance(intent, dict) or \
                    not isinstance(intent.get("type"), str):
                _file_away(src, failed_dir,
                           {"error": "malformed intent"})
                out.append((name, False, "malformed intent"))
                continue
            try:
                ok, detail = runner(intent)
            except Exception as exc:            # noqa: BLE001 - evidence
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            kind = {"build": content.KIND_BUILD,
                    "repair": content.KIND_REPAIR}.get(
                intent["type"], content.KIND_TICK)
            payload = {
                "source": source,
                "intent": intent.get("id") or name,
                "type": intent["type"],
                "ok": bool(ok),
                "detail": str(detail)[:400],
                "at": _iso(),
            }
            self._emit(kind, payload)
            if reply_box:
                try:
                    self.post.send(reply_box, "fleet.reply", dict(
                        payload), frm=content.ORGAN)
                except Exception:
                    pass                        # reply mirror best-effort
            dest_dir = done_dir if ok else failed_dir
            _file_away(src, dest_dir, {"outcome":
                                       {"ok": bool(ok),
                                        "detail": str(detail)[:400]}})
            out.append((name, bool(ok), detail))
        return out

    # ---------------- cycle ----------------

    def run_cycle(self):
        out = {"forwarded": self.forward_daedalus(),
               "intents": self.drain_intents(),
               "mind_intents": self.drain_mind_intents(),
               "tick": self.tick()}
        try:
            out["riley"] = self.riley.stream()
        except Exception as exc:         # noqa: BLE001 - stream must flow
            out["riley"] = {"error": f"{type(exc).__name__}: {exc}"}
        return out


# ------------------------------------------------------------------ helpers

def _run_intent(intent):
    """Execute one intent against the live fleet. Returns (ok, detail)."""
    kind = intent.get("type")
    if kind == "build":
        cmd = [sys.executable, "-m", "daedalus", "build",
               "--blueprint", str(intent.get("blueprint") or "jsonl-echo")]
        if intent.get("name"):
            cmd += ["--name", str(intent["name"])]
        return _run_cmd(cmd, content.DAEDALUS_TIMEOUT_S)
    if kind == "repair":
        return _repair_sweep()
    if kind == "knowledge":
        return _knowledge_answer(intent)
    if kind == "status":
        return True, "alive"
    return False, f"unknown intent type: {kind!r}"


def _knowledge_answer(intent):
    """Answer a knowledge query from the curated library (read-only)."""
    query = str(intent.get("query") or "").strip()
    if not query:
        return False, "knowledge intent needs a non-empty 'query'"
    engine_path = os.path.join(content.WORKSPACE, "knowledge",
                               "engine.py")
    if not os.path.isfile(engine_path):
        return False, "knowledge organ not available"
    if content.WORKSPACE not in sys.path:
        sys.path.insert(0, content.WORKSPACE)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "knowledge_engine", engine_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    top = min(int(intent.get("top", 3) or 3), 10)
    hits = module.search(query, top=top)
    if not hits:
        return True, "(no matches)"
    lines = [f"{h['title']} [{h['doc']}] :: {h['snippet']}"
             for h in hits]
    return True, " | ".join(lines)[:400]


def _run_cmd(cmd, timeout_s):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout_s}s: {' '.join(cmd)}"
    tail = ((proc.stdout or "") + (proc.stderr or "")).strip()
    tail = " | ".join(tail.splitlines()[-3:])[:400]
    return proc.returncode == 0, tail or f"exit {proc.returncode}"


def _repair_sweep():
    """Safe remediation sweep with published proof: doctor's own
    check+fix pass, summarized to counts and the red list."""
    here = content.WORKSPACE
    if here not in sys.path:
        sys.path.insert(0, here)
    import doctor as doctor_mod          # repo-root module
    doc = doctor_mod.Doctor(ci=True)
    summary = doc.run()
    red = [c.get("check") for c in summary.get("checks", [])
           if c.get("status") == "fail"]
    ok = summary.get("fail", 1) == 0
    return ok, (f"doctor sweep: {summary.get('fail', '?')} fail, "
                f"{summary.get('fixed', 0)} fixed"
                + (f"; red: {red}" if red else ""))


def _daedalus_lanes():
    """Best-effort lane snapshot; a sleeping workshop is valid state."""
    code = ("import json;from daedalus.kernel import Workshop;"
            "print(json.dumps(Workshop().status(),default=str))")
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            timeout=content.STATUS_TIMEOUT_S, cwd=content.WORKSPACE)
        if proc.returncode == 0:
            return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:                    # noqa: BLE001 - degrade quietly
        pass
    return None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _file_away(src, dest_dir, extra):
    """Move an intent to done/failed, merging the outcome into it."""
    os.makedirs(dest_dir, exist_ok=True)
    body = _read_json(src)
    if not isinstance(body, dict):
        body = {"raw": None}
    body.update(extra)
    body["filed_at"] = _iso()
    dest = os.path.join(dest_dir, os.path.basename(src))
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=1, default=str)
    try:
        os.remove(src)
    except OSError:
        pass
    os.replace(tmp, dest)


def watch(every_s=None):
    """The constant update stream. Runs until interrupted."""
    every = float(every_s or content.TICK_EVERY_S)
    relay = Relay()
    print(f"[relay] bridging daedalus<->venus, tick every {every:g}s",
          flush=True)
    while True:
        try:
            result = relay.run_cycle()
            print(json.dumps({"forwarded": result["forwarded"],
                              "intents": len(result["intents"])},
                             default=str), flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:         # noqa: BLE001 - stream must flow
            print(f"[relay] cycle error: {type(exc).__name__}: {exc}",
                  flush=True)
        time.sleep(every)
