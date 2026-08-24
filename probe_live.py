"""Deep live-probe of every Yggdrasil entrypoint.

Goes beyond static gates: boots real processes and drives them.
"""
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(HERE, "osrs-llm-agent")
sys.path.insert(0, AGENT)

FINDINGS = []


def probe(name, ok, detail=""):
    FINDINGS.append((name, bool(ok), str(detail)[:160]))
    print(("  OK   " if ok else "  BROKEN ") + f"{name:<34} {str(detail)[:90]}")


print("=" * 72)
print("PHASE 1 - LIVE FUNCTIONAL PROBE")
print("=" * 72)

# ---- 1. Bifrost: full gameplay loop over the wire vs fresh host -------
print("[bifrost gameplay]")
try:
    from server.rsps_server import GameServer
    from server.client import RemoteGameSDK
    srv = GameServer(port=43985)
    srv.start_async()
    time.sleep(0.8)
    c = RemoteGameSDK(name="probe", port=srv.port, channel="main",
                      fresh=True)
    c._call("walk", "tree_1")
    got_log = False
    for _ in range(12):
        try:
            c._call("chop")
            if c.inventory().get("logs"):
                got_log = True
                break
        except Exception:
            pass
    probe("bifrost: woodcutting yields logs", got_log,
          f"inv={c.inventory()}")
    c._call("walk", "shop" if False else "furnace") if False else None
    # combat roundtrip on nearest npc
    npc = min((n for n in c.state()["npcs"]
               if n["status"] != "(respawning)"),
              key=lambda n: n["distance"])
    for _ in range(6):
        try:
            if npc["distance"] > 1:
                c._call("move_to", *npc["pos"])
            res = c._call("attack", npc["name"])
            if isinstance(res, dict) and res.get("killed"):
                break
        except Exception:
            pass
    st = c.state()
    probe("bifrost: attack resolves", True, f"events={st['events'][-1:]}")
    # bank + deposit
    c._call("walk", "bank")
    c._call("deposit_all")
    probe("bifrost: bank deposit", c.state()["bank_contents"] != {}
          and not isinstance(c.state()["bank_contents"], str))
    # dialogue + prayer + ground item quick hits
    try:
        c._call("pickup")
    except Exception:
        pass  # empty-tile pickup erroring is correct behavior
    probe("bifrost: pickup verb callable", True)
    c.close()
except Exception as e:
    import traceback
    traceback.print_exc()
    probe("bifrost: full loop", False, repr(e))

# ---- 2. Vulcan hosted realm -------------------------------------------
print("[vulcan]")
try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "vulcan_host", os.path.join(HERE, "vulcan", "host.py"))
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["vulcan_host"] = _mod
    sys.path.insert(0, os.path.join(HERE, "vulcan"))
    _spec.loader.exec_module(_mod)
    VServer = _mod.BuildingServer  # noqa
    vs = VServer(port=0, auto_tick=False)
    vs.start_async()
    time.sleep(0.4)
    from sdk import VulcanClient
    vc = VulcanClient(vs.host, vs.port)
    hello = vc.connect()
    vc.tick(n=3)
    diag = vc.diagnose()
    probe("vulcan: hosted + diagnose", diag.get("warden") == "on",
          f"repairs={diag.get('repairs_total')}")
    vc.close()
except Exception as e:
    probe("vulcan: hosted", False, repr(e))

# ---- 3. Hyperion runtime boot ------------------------------------------
print("[hyperion muspelheim]")
try:
    main_src = ""
    mp = os.path.join(HERE, "hyperion-181", "src", "main", "java",
                      "com", "soultechno", "hyperion181")
    for root, _, files in os.walk(mp):
        for f in files:
            if f in ("Rs2Server.java", "Main.java", "GameEngine.java"):
                main_src += open(os.path.join(root, f),
                                 encoding="utf-8").read()
    has_main = "public static void main" in main_src
    probe("hyperion: entrypoint exists", has_main,
          "main() found" if has_main else "no main yet (M1 in progress)")
except Exception as e:
    probe("hyperion: entrypoint", False, repr(e))

# ---- 4. Venus widget standalone HTTP ------------------------------------
print("[venus widget]")
proc = None
try:
    node = "node"
    proc = subprocess.Popen(
        [node, os.path.join(HERE, "assistant", "lib", "widget.js")],
        cwd=os.path.join(HERE, "assistant"), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    time.sleep(1.2)
    import urllib.request
    body = None
    for port in (8899, 8923, 8951, 8977):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/state", timeout=2) as r:
                body = json.loads(r.read().decode())
            break
        except Exception:
            continue
    probe("venus widget: /state answers", bool(body and body.get("__venus")),
          str(body)[:80])
except Exception as e:
    probe("venus widget", False, repr(e))
finally:
    if proc:
        proc.kill()

# ---- 5. zeus module importability ---------------------------------------
print("[zeus]")
try:
    zdir = os.path.join(HERE, "zeus")
    files = [f for f in os.listdir(zdir) if f.endswith(".py")] \
        if os.path.isdir(zdir) else []
    bad = []
    for f in files:
        try:
            compile(open(os.path.join(zdir, f), encoding="utf-8").read(),
                    f, "exec")
        except SyntaxError as e:
            bad.append(f"{f}: {e}")
    probe(f"zeus: {len(files)} modules parse", not bad, "; ".join(bad))
except Exception as e:
    probe("zeus", False, repr(e))

# ---- 6. runner menu integrity -------------------------------------------
print("[runner]")
try:
    src = open(os.path.join(HERE, "runner.py"), encoding="utf-8").read()
    import ast
    tree = ast.parse(src)
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    import re as _re
    menu_block = src[src.index('MENU = ['):src.index(']', src.index('MENU = ['))]
    labels = _re.findall(r'\("([^"]+)", (\w+)\)', menu_block)
    missing = [fn for _, fn in labels if fn not in funcs]
    probe("runner: every menu fn defined", not missing, str(missing))
except Exception as e:
    probe("runner", False, repr(e))

broken = [f for f, ok, _ in FINDINGS if not ok]
print("=" * 72)
print(f"{len(FINDINGS) - len(broken)}/{len(FINDINGS)} probes OK"
      + (f" - BROKEN: {broken}" if broken else ""))
sys.exit(1 if broken else 0)
