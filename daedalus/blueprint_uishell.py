"""DAEDALUS ui-shell blueprint - the house design system, weavable.

Weaves the token-driven dark shell from
docs/plans/ui-design-system-plan.md into a self-contained app:
one stdlib HTTP server, achromatic near-black surfaces, a single
functional accent, pill/circle geometry, 44px targets, three-region
shell (rail / content / console), universal card primitive, and the
house JSON contract (every response carries "error").

Same doctrine as every other blueprint: the woven instance must prove
itself inside the ATLAS jail before it seals - tokens, geometry,
card set, activation flow, and the error path all pinned by the gate.

Exports BLUEPRINT in the blueprint_nymph shape.
"""

import sys

UI_SERVER = '''"""UI shell server (DAEDALUS-woven).

Serves the house design system as one page + one tiny JSON API.
Contract: every JSON response carries "error"; dark-first tokens;
single functional accent; pills and circles; 44px minimum targets.

Run: python ui_server.py [port]
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACCENT = "{{ACCENT}}"
BG_BASE = "{{BG_BASE}}"

INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>House Shell</title>
<style>
:root{
  --bg-base:{{BG_BASE}};
  --bg-elevated:#181818;
  --bg-control:#1f1f1f;
  --fg-primary:#ffffff;
  --fg-secondary:#b3b3b3;
  --fg-muted:#696969;
  --accent:{{ACCENT}};
  --radius-pill:9999px;
  --radius-circle:50%;
  --target-min:44px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--bg-base);
  color:var(--fg-primary);
  font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;
  font-size:16px;line-height:1.3;
  display:grid;grid-template-columns:220px 1fr;
  grid-template-rows:1fr auto;height:100vh;
}
#rail{grid-row:1/3;background:var(--bg-base);padding:24px 16px}
#rail h1{font-size:24px;font-weight:700;margin-bottom:16px}
#rail a{display:block;color:var(--fg-secondary);text-decoration:none;
  padding:12px;font-size:14px;border-radius:4px;min-height:44px}
#rail a:hover,#rail a[aria-current]{color:var(--fg-primary);
  background:var(--bg-control)}
#content{padding:24px;display:grid;gap:16px;
  grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
  align-content:start;overflow-y:auto}
.card{background:var(--bg-elevated);border-radius:8px;padding:16px;
  box-shadow:rgba(0,0,0,.3) 0 8px 16px;cursor:pointer;
  min-height:44px;border:none;color:inherit;text-align:left;width:100%}
.card.active{outline:2px solid var(--accent)}
.art{width:100%;aspect-ratio:1;border-radius:4px;
  background:linear-gradient(135deg,var(--accent),#191414)}
.card h2{font-size:18px;font-weight:600;margin-top:12px}
.card p{font-size:14px;color:var(--fg-secondary)}
#console{grid-column:2;background:var(--bg-elevated);
  box-shadow:rgba(0,0,0,.5) 0 8px 24px;display:flex;gap:12px;
  align-items:center;padding:12px 24px}
.pill{border-radius:var(--radius-pill);border:none;cursor:pointer;
  background:var(--accent);color:#000;font-size:14px;font-weight:700;
  letter-spacing:1.4px;text-transform:uppercase;
  min-width:var(--target-min);min-height:var(--target-min);
  padding:0 24px}
.circle{border-radius:var(--radius-circle);width:56px;height:56px}
</style>
</head>
<body>
<nav id="rail"><h1>House</h1>
<a href="#" aria-current="true">Home</a><a href="#">Library</a></nav>
<main id="content"></main>
<footer id="console">
  <button class="pill circle" id="play" aria-label="play">&#9654;</button>
  <button class="pill" id="reset">Reset</button>
  <span id="status" style="color:var(--fg-secondary);font-size:14px">
  ready</span>
</footer>
<script>
async function refresh(){
  const s=await fetch("/api/state").then(r=>r.json());
  const c=document.getElementById("content");
  c.innerHTML="";
  for(const card of s.cards){
    const b=document.createElement("button");
    b.className="card"+(s.active===card.id?" active":"");
    b.innerHTML="<div class='art'></div><h2>"+card.title+
      "</h2><p>"+card.detail+"</p>";
    b.onclick=async()=>{await act(card.id)};
    c.appendChild(b);
  }
  document.getElementById("status").textContent=
    s.active?("active: "+s.active):"ready";
}
async function act(id){
  await fetch("/api/action",{method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({card:id})});
  await refresh();
}
document.getElementById("reset").onclick=
  ()=>act(document.querySelector(".card.active")
    ?JSON.parse(document.getElementById("content")
      .firstChild.dataset||"{}")&&refresh():refresh());
refresh();
</script>
</body></html>"""

_CARDS = [
    {"id": "tokens", "title": "Tokens",
     "detail": "color, type, geometry"},
    {"id": "shell", "title": "Shell",
     "detail": "rail, content, console"},
    {"id": "cards", "title": "Cards",
     "detail": "the universal primitive"},
    {"id": "motion", "title": "Motion",
     "detail": "inform, focus, celebrate"},
]
CARDS = list(_CARDS)

STATE = {"active": None}


def respond(handler, obj, code=200, ctype="application/json"):
    body = json.dumps(obj).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = INDEX.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            respond(self, {"error": None, "cards": CARDS,
                           "active": STATE["active"],
                           "tokens": {"accent": ACCENT,
                                      "bgBase": BG_BASE}})
        else:
            respond(self, {"error": "not-found",
                           "path": self.path}, 404)

    def do_POST(self):
        if self.path != "/api/action":
            respond(self, {"error": "not-found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            respond(self, {"error": "bad-json"}, 400)
            return
        if req.get("card") not in {c["id"] for c in CARDS}:
            respond(self, {"error": "unknown-card"}, 400)
            return
        STATE["active"] = req["card"]
        respond(self, {"error": None, "active": STATE["active"]})

    def log_message(self, *_a):
        pass


def serve(host="127.0.0.1", port=0):
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"uishell up on {srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
'''

UI_GATE = '''"""Self-test gate for the woven UI shell (exit 0 = pass).

Pins the house law inside the jail: startup banner announces the
port, the page carries the dark token block + pill/circle geometry +
three-region shell ids, /api/state honors the error contract with a
non-empty card set, activation round-trips, unknown cards fail the
error path, and canonical defaults surface via /api/tokens.
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request

ok = True


def need(cond, why):
    global ok
    if cond:
        print(f"  gate: ok - {why}")
    else:
        ok = False
        print(f"  gate: FAIL - {why}")


proc = subprocess.Popen([sys.executable, "ui_server.py"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True)
line = proc.stdout.readline()
need(line.startswith("uishell up on "), f"banner announced ({line[:40]})")
port = int(line.strip().split()[-1])
base = f"http://127.0.0.1:{port}"

try:
    html = urllib.request.urlopen(base + "/", timeout=10).read().decode()

    for token in ("--bg-base:", "--bg-elevated:", "--bg-control:",
                  "--fg-primary:", "--fg-secondary:",
                  "--radius-pill:9999px", "--radius-circle:50%",
                  "--target-min:44px"):
        need(token in html, f"token {token} present")

    for region in ('id="rail"', 'id="content"', 'id="console"'):
        need(region in html, f"region {region} present")

    need('class="pill"' in html, "pill button shipped")
    need('class="pill circle"' in html, "circular control shipped")

    state = json.load(urllib.request.urlopen(base + "/api/state",
                                             timeout=10))
    need(state.get("error") is None, "state carries null error")
    need(isinstance(state.get("cards"), list) and len(state["cards"]) >= 3,
         "card set non-empty")

    tokens = state.get("tokens", {})
    need(tokens.get("bgBase") == "{{BG_BASE}}",
         f"canonical dark base (got {tokens.get('bgBase')})")
    need(tokens.get("accent") == "{{ACCENT}}",
         f"canonical accent (got {tokens.get('accent')})")

    req = urllib.request.Request(
        base + "/api/action",
        data=json.dumps({"card": "tokens"}).encode(),
        headers={"Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=10))
    need(resp.get("error") is None and resp.get("active") == "tokens",
         "activation round-trips")

    state = json.load(urllib.request.urlopen(base + "/api/state",
                                             timeout=10))
    need(state.get("active") == "tokens", "activation persists")

    bad = urllib.request.Request(
        base + "/api/action",
        data=json.dumps({"card": "ghost"}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(bad, timeout=10)
        need(False, "unknown card rejected")
    except urllib.error.HTTPError as exc:
        body = json.load(exc)
        need(exc.code == 400 and body.get("error") == "unknown-card",
             "error path carries named error")

    try:
        urllib.request.urlopen(base + "/api/nope", timeout=10)
        need(False, "missing route rejected")
    except urllib.error.HTTPError as exc:
        body = json.load(exc)
        need(exc.code == 404 and body.get("error") == "not-found",
             "missing route names its error")
finally:
    proc.terminate()

print("ui-shell gate green")
sys.exit(0 if ok else 1)
'''

FILES = {
    "ui_server.py": UI_SERVER,
    "verify_uishell.py": UI_GATE,
}

FAULTS = {
    # white canvas: the whole room changes - tokens endpoint betrays it
    "flat_theme": ("ui_server.py",
                   'BG_BASE = "{{BG_BASE}}"',
                   'BG_BASE = "#ffffff"'),
    # empty shelf: the shell ships nothing to render
    "mute_cards": ("ui_server.py",
                   "CARDS = list(_CARDS)",
                   "CARDS = []"),
    # square buttons break the identity: geometry law violated
    "square_buttons": ("ui_server.py",
                       "--radius-pill:9999px",
                       "--radius-pill:0px"),
    # deliberately innocent - exercises culprit isolation
    "cosmetic_doc": ("ui_server.py",
                     "(DAEDALUS-woven)", "(rewoven)"),
}

BLUEPRINT = {
    "description": "house design-system UI shell "
                   "(dark tokens, card primitive, error-contract API)",
    "files": FILES,
    "gate": [sys.executable, "verify_uishell.py"],
    "params": {"ACCENT": "#1ed760", "BG_BASE": "#121212"},
    "faults": dict(FAULTS),
}
