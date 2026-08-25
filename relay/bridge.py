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
        """Catalogue-legal broadcast + mailbox mirrors (venus always;
        mind honours its subscription filter)."""
        self.post.broadcast(content.TOPIC, kind, payload,
                            frm=content.ORGAN)
        try:
            self.post.send(content.MAILBOX, kind, payload,
                           frm=content.ORGAN)
        except Exception:
            pass                      # mirror is best-effort; topic rules
        kinds, all_kinds = _mind_subscriptions()
        if not all_kinds and kinds and kind not in kinds:
            return                    # mind opted out of this kind
        try:
            self.post.send(content.MIND_MAILBOX, kind, payload,
                           frm=content.ORGAN)
        except Exception:
            pass

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

    def drain_mind_intents(self, limit=None):
        """Claim, execute and file every pending MIND intent.

        Mind-lane semantics (beyond the venus lane):
          - urgent intents jump the queue
          - intents older than MIND_INTENT_TTL_S expire unrun
          - duplicate ids (crash-replayed writers) are acknowledged as
            duplicates via the seen-ledger; the runner runs once
          - at most MIND_MAX_PER_DRAIN execute per cycle; overflow stays
            queued for the next pass

        Every outcome is additionally answered back into the `mind`
        mailbox as a fleet.reply record carrying the intent id so the
        mind layer can correlate requests.
        """
        return self._drain_dir(
            content.MIND_INTENT_DIR, content.MIND_DONE,
            content.MIND_FAILED, "mind-intent", self.runner,
            limit if limit is not None else content.MIND_MAX_PER_DRAIN,
            reply_box=content.MIND_MAILBOX, mind_semantics=True)

    def _drain_dir(self, intent_dir, done_dir, failed_dir, source,
                   runner, limit, reply_box=None, mind_semantics=False):
        out = []
        os.makedirs(intent_dir, exist_ok=True)
        entries = []
        for name in sorted(n for n in os.listdir(intent_dir)
                           if n.endswith(".intent.json")):
            src = os.path.join(intent_dir, name)
            intent = _read_json(src)
            entries.append((name, src, intent))
        if mind_semantics:
            # urgent intents jump the queue; then stable filename order
            entries.sort(key=lambda e: (
                0 if (e[2] or {}).get("urgent") else 1, e[0]))
        executed = 0
        seen_ledger = _load_seen() if mind_semantics else {}
        ledger_dirty = False
        for name, src, intent in entries:
            if mind_semantics and executed >= limit:
                break                                  # stays queued
            if not isinstance(intent, dict) or \
                    not isinstance(intent.get("type"), str):
                _file_away(src, failed_dir,
                           {"error": "malformed intent"})
                out.append((name, False, "malformed intent"))
                continue
            key = _intent_key(intent)
            if mind_semantics and key in seen_ledger:
                # acknowledge the replay so the mind side learns the
                # intent was already executed - silence reads as loss
                # and turns crash replays into infinite redrives
                if reply_box:
                    try:
                        self.post.send(reply_box, "fleet.reply", {
                            "source": source,
                            "intent": str(intent.get("id") or name),
                            "type": intent.get("type"),
                            "ok": True,
                            "detail": "duplicate of earlier intent "
                                      f"{seen_ledger[key]}",
                            "at": _iso(),
                        }, frm=content.ORGAN)
                    except Exception:
                        pass        # ack mirror stays best-effort
                _file_away(src, done_dir, {"outcome": {
                    "ok": True, "duplicate": True,
                    "detail": f"duplicate of earlier intent "
                              f"{seen_ledger[key]}"}})
                out.append((name, True, "duplicate ignored"))
                continue
            if mind_semantics:
                stale = _stale_reason(intent)
                if stale:
                    _file_away(src, failed_dir,
                               {"error": stale})
                    out.append((name, False, stale))
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
            executed += 1
            if mind_semantics:
                seen_ledger[key] = str(intent.get("id") or name)
                ledger_dirty = True
        if mind_semantics and ledger_dirty:
            _save_seen(seen_ledger)
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
        try:
            out["riley_done"] = self.riley.completions()
        except Exception as exc:         # noqa: BLE001 - lane never raises
            out["riley_done"] = {"error": f"{type(exc).__name__}: {exc}"}
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


def _intent_key(intent):
    """Stable dedupe key: declared id or content hash."""
    declared = intent.get("id")
    if declared:
        return f"id:{declared}"
    blob = json.dumps(intent, sort_keys=True,
                      ensure_ascii=False).encode("utf-8")
    import hashlib
    return "sha:" + hashlib.sha256(blob).hexdigest()[:32]


def _stale_reason(intent):
    """TTL check for intents that carry their own timestamp."""
    ttl = content.MIND_INTENT_TTL_S
    ts = intent.get("ts")
    if not ts:
        return None                       # undated intents never expire
    try:
        if isinstance(ts, (int, float)):
            age = time.time() - float(ts)
        else:
            from datetime import datetime
            stamp = str(ts).replace("Z", "+00:00")
            age = time.time() - datetime.fromisoformat(stamp).timestamp()
    except (ValueError, TypeError, OSError):
        return None                       # unparsable dates are trusted
    if age > ttl:
        return f"expired: intent is {int(age)}s old (ttl {ttl}s)"
    return None


def _load_seen():
    try:
        with open(content.MIND_DEDUPE_LEDGER, encoding="utf-8") as fh:
            ledger = json.load(fh)
        if isinstance(ledger, dict):
            # prune oldest beyond the cap
            if len(ledger) > content.MIND_LEDGER_MAX:
                keep = sorted(ledger.items(),
                              key=lambda kv: kv[1])[-content.MIND_LEDGER_MAX:]
                return dict(keep)
            return ledger
    except (OSError, ValueError):
        pass
    return {}


def _save_seen(ledger):
    try:
        os.makedirs(os.path.dirname(content.MIND_DEDUPE_LEDGER),
                    exist_ok=True)
        with open(content.MIND_DEDUPE_LEDGER + ".tmp", "w",
                  encoding="utf-8") as fh:
            json.dump(ledger, fh)
        os.replace(content.MIND_DEDUPE_LEDGER + ".tmp",
                   content.MIND_DEDUPE_LEDGER)
    except OSError:
        pass                              # dedupe degrades to no-op


def _mind_subscriptions():
    """Kinds MIND wants mirrored; default = everything."""
    path = content.MIND_SUBSCRIPTIONS
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        kinds = data.get("kinds")
        if isinstance(kinds, list) and kinds:
            return set(kinds), data.get("all") is True
        return None, data.get("all", True)
    except (OSError, ValueError):
        return None, True


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
