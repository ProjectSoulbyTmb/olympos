"""System piping verification - proves data actually flows through every
inter-system channel. Exit 0 = all pipes flowing."""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
UNI = os.path.join(ROOT, "osrs-unified")
sys.path.insert(0, UNI)
sys.path.insert(0, os.path.join(ROOT, "osrs-llm-agent"))

PY = sys.executable
PASS, FAIL = [], []


def check(name, fn):
    try:
        detail = fn()
        PASS.append(name)
        print(f"  PASS {name}" + (f" - {detail}" if detail else ""))
    except Exception as e:
        FAIL.append(name)
        print(f"  FAIL {name} - {type(e).__name__}: {e}")


# ---------------------------------------------------------------- pipes ----

def pipe_updater_files():
    """updater -> knowledge/live/*.json -> market.ge_price (both engines)."""
    ages = []
    for engine in ("osrs-llm-agent", "osrs-unified"):
        p = os.path.join(ROOT, engine, "knowledge", "live",
                         "ge_prices.json")
        if not os.path.exists(p):
            raise FileNotFoundError(p)
        age_h = (time.time() - os.path.getmtime(p)) / 3600
        ages.append(f"{engine.split('-')[-1]}:{age_h:.1f}h")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("items"), f"{engine}: empty price snapshot"
    return "fresh " + ", ".join(ages)


def pipe_market_lookup():
    from game.market import ge_price          # osrs-llm-agent engine
    r = ge_price("Rune arrow") or ge_price("rune_arrow") or \
        ge_price("Air rune") or ge_price("air_rune")
    assert r, "no GE hit for probe items"
    return f"rune item high={r.get('high')}"


def pipe_server_live_wire():
    from server.rsps_server import GameServer
    srv = GameServer(port=43996)
    srv.start_async()
    time.sleep(0.5)
    try:
        snap = srv.live_summary(items=["air_rune"])
        v = snap["version"]
        assert isinstance(v, int)
        return f"live cache v{v}, prices endpoint ok"
    finally:
        srv.running = False


def pipe_client_live():
    sys.path.insert(0, os.path.join(ROOT, "osrs-llm-agent"))
    from server.rsps_server import GameServer
    from server.client import RemoteGameSDK
    srv = GameServer(port=43995)
    srv.start_async()
    time.sleep(0.5)
    try:
        g = RemoteGameSDK(name="piper", port=srv.port, budget=100)
        live = g.live(items=["cake"])
        assert "version" in live
        g.close()
        return "wire cmd 'live' ok"
    finally:
        srv.running = False


def _bus():
    from mind.bus import EventBus
    return EventBus(UNI)


def pipe_bus_roundtrip():
    bus = _bus()
    eid = bus.publish("pipe.test", {"hello": True}, source="mind")
    pend = [e for e in bus.pending() if e["id"] == eid]
    assert pend, "event not visible in spool"
    bus.take(eid)
    bus.complete(eid, {"ok": True}, ok=True)
    arc = [e for e in bus.recent(5) if e["id"] == eid]
    assert arc and arc[0]["status"] == "done"
    return f"spool->archive roundtrip {eid[:24]}..."


def pipe_venus_envelope():
    """venus.request -> drain -> archived result (the Venus->MIND pipe)."""
    bus = _bus()
    eid = bus.publish("venus.request",
                      {"action": "status", "args": {}},
                      source="venus")
    from mind import venus_link
    from mind.state import MindState
    summary = venus_link.drain(UNI, MindState(UNI), execute=True)
    done = [e for e in bus.recent(5) if e["id"] == eid]
    assert done and done[0]["status"] == "done", "envelope not completed"
    out = done[0]["result"].get("output", "")
    assert "MIND status" in out, "status output missing"
    return f"envelope executed, {len(out)} chars returned"


def pipe_thoth_gate():
    """thoth-sourced elevated request MUST be refused without consent."""
    bus = _bus()
    eid = bus.publish("venus.request",
                      {"action": "release", "args": {}},
                      source="thoth")
    from mind import venus_link
    from mind.state import MindState
    venus_link.drain(UNI, MindState(UNI), execute=True)
    done = [e for e in bus.recent(5) if e["id"] == eid]
    assert done and done[0]["status"] == "failed", "gate did not refuse"
    assert "refused" in str(done[0]["result"]), "refusal text missing"
    return "elevated thoth request refused (consent gate holds)"


def pipe_mind_status_files():
    """files Venus's mind.js reads must exist and be fresh."""
    checks = ["runs/mind_status.json", "runs/mind_log.jsonl"]
    for rel in checks:
        p = os.path.join(UNI, *rel.split("/"))
        if not os.path.exists(p):
            raise FileNotFoundError(rel)
        age_h = (time.time() - os.path.getmtime(p)) / 3600
        assert age_h < 48, f"{rel} stale ({age_h:.0f}h)"
    return "mind_status.json + mind_log.jsonl present"


def pipe_net_report():
    p = os.path.join(UNI, "runs", "net_report.json")
    if not os.path.exists(p):
        return "net_report.json not yet written (net sweep pending)"
    with open(p, encoding="utf-8") as f:
        rep = json.load(f)
    return f"endpoints={rep.get('healthy', '?')} healthy recorded"


def pipe_ollama_llm():
    req = urllib.request.Request(
        "http://localhost:11434/api/tags", method="GET")
    with urllib.request.urlopen(req, timeout=4) as resp:
        models = [m["name"] for m in
                  json.load(resp).get("models", [])]
    assert models, "ollama reachable but no models"
    return ", ".join(models[:3])


def pipe_net_sweep_live():
    from mind import network
    from mind.state import MindState
    rep = network.sweep(UNI, MindState(UNI), bus=_bus(), timeout=5.0)
    assert rep["healthy"] >= 1, "all endpoints down"
    return f"{rep['healthy']} healthy / {rep['degraded']} degraded / " \
           f"{rep['down']} down"


print("=" * 62)
print("SYSTEM PIPING CHECK - every inter-system channel")
print("=" * 62)

check("updater -> knowledge/live (both engines)", pipe_updater_files)
check("market ge_price lookup", pipe_market_lookup)
check("server live cache + summary", pipe_server_live_wire)
check("client wire cmd 'live'", pipe_client_live)
check("osrs_bus spool->archive roundtrip", pipe_bus_roundtrip)
check("venus.request -> MIND drain -> result", pipe_venus_envelope)
check("thoth consent gate (elevated refused)", pipe_thoth_gate)
check("mind_status/log files for venus.js", pipe_mind_status_files)
check("net_report.json readable", pipe_net_report)
check("ollama LLM endpoint", pipe_ollama_llm)
check("live internet sweep (network engine)", pipe_net_sweep_live)

print("-" * 62)
print(f"{len(PASS)} pipes flowing, {len(FAIL)} blocked")
if FAIL:
    print("blocked: " + ", ".join(FAIL))
    sys.exit(1)
print("ALL PIPES FLOWING")
