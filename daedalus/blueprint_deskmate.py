"""DAEDALUS blueprint: deskmate - a project-design desk for VENUS.

Weaves a small HTTP service that gives any desktop panel (Venus
plugin, PTAH tool, curl) a local design assistant:

    GET  /health          -> liveness
    GET  /card/template   -> the design-card-v0 starter (schema shape)
    POST /card/validate   -> {ok, valid, errors[]} for a design card
    POST /scaffold        -> {name, kind, target} -> filled starter card

House contracts hold: every response carries ``error``; loopback only;
port written to ``port.txt`` for the gate and for Venus discovery.
Validation honours ``VALIDATE_STRICT`` - flipping it to False is the
injected-fault seam that proves the gate actually bites.
"""

import json

# Targets DAEDALUS can currently weave (kept in sync manually with
# the blueprint catalogue; deskmate suggests, operator decides).
KNOWN_TARGETS = ["godot-game", "jsonl-echo", "http-health"]

CARD_TEMPLATE = {
    "$schema": "yggdrasil/design-card-v0",
    "name": "",
    "kind": "game | app",
    "target": "godot-game",
    "intent": "One paragraph: what it does for the player/user.",
    "inputs": [],
    "outputs": [],
    "entities": [
        {"name": "", "fields": {}, "notes": ""}
    ],
    "invariants": [
        "Statements that must be true after every tick/operation."
    ],
    "acceptance": [
        {"given": "", "when": "", "then": ""}
    ],
    "constraints": {
        "stdlib_only": True,
        "network": "deny-by-default",
        "secrets": "none-at-build-time",
    },
}

VALIDATE_STRICT = True


def validate_card(card):
    """-> list[str] problems. Empty list means the card is buildable."""
    if not VALIDATE_STRICT:
        return []
    p = []
    if not isinstance(card, dict):
        return ["card must be an object"]
    name = str(card.get("name") or "").strip()
    if not name:
        p.append("name required")
    if card.get("kind") not in ("game", "app"):
        p.append("kind must be 'game' or 'app'")
    if card.get("target") not in KNOWN_TARGETS:
        p.append(f"unknown target: {card.get('target')!r}")
    if len(str(card.get("intent") or "").strip()) < 20:
        p.append("intent too short (<20 chars) - describe the value")
    ents = card.get("entities")
    if not isinstance(ents, list) or not ents:
        p.append("entities must be a non-empty list")
    else:
        for e in ents:
            if not isinstance(e, dict) or not e.get("name"):
                p.append("every entity needs a name")
                break
    acc = card.get("acceptance")
    if not isinstance(acc, list) or not acc:
        p.append("acceptance criteria required")
    else:
        for a in acc:
            if not isinstance(a, dict) or not all(
                    str(a.get(k, "")).strip()
                    for k in ("given", "when", "then")):
                p.append("acceptance rows need given/when/then")
                break
    return p


def scaffold(card):
    """Fill a starter design card from a minimal request."""
    name = str(card.get("name") or "unnamed").strip() or "unnamed"
    kind = card.get("kind") if card.get("kind") in ("game", "app") \
        else "app"
    target = card.get("target") if card.get("target") in KNOWN_TARGETS \
        else "godot-game"
    out = json.loads(json.dumps(CARD_TEMPLATE))  # deep copy
    out.update({
        "name": name,
        "kind": kind,
        "target": target,
        "intent": (f"{name}: a {kind} that "
                   f"{card.get('hint', 'delivers its core loop')}."),
        "entities": [{"name": "world", "fields": {}, "notes": ""}],
        "acceptance": [{"given": "a fresh start", "when": "the core "
                        "loop completes once",
                        "then": "state digest matches expectation"}],
    })
    return out


SERVER = '''"""DESKMATE - local project-design desk (DAEDALUS-woven).

Endpoints:
  GET  /health         -> {"ok": true, ...}
  GET  /card/template  -> {"ok": true, "template": {...}}
  POST /card/validate  -> {"ok": true, "valid": bool, "errors": [...]}
  POST /scaffold       -> {"ok": true, "card": {...}}

Loopback only; bound port written to port.txt for discovery.
"""

import http.server
import json
import os

VALIDATE_STRICT = __STRICT__

TEMPLATE = __TEMPLATE__
TARGETS = __TARGETS__


def validate_card(card):
    if not VALIDATE_STRICT:
        return []
    p = []
    if not isinstance(card, dict):
        return ["card must be an object"]
    if not str(card.get("name") or "").strip():
        p.append("name required")
    if card.get("kind") not in ("game", "app"):
        p.append("kind must be game|app")
    if card.get("target") not in TARGETS:
        p.append(f"unknown target: {{card.get('target')!r}}")
    if len(str(card.get("intent") or "").strip()) < 20:
        p.append("intent too short")
    ents = card.get("entities")
    if not isinstance(ents, list) or not ents:
        p.append("entities must be a non-empty list")
    acc = card.get("acceptance")
    if not isinstance(acc, list) or not acc:
        p.append("acceptance criteria required")
    return p


def scaffold(req):
    req = req if isinstance(req, dict) else {{}}
    name = str(req.get("name") or "unnamed").strip() or "unnamed"
    kind = req.get("kind") if req.get("kind") in ("game", "app") \\
        else "app"
    target = req.get("target") if req.get("target") in TARGETS \\
        else TARGETS[0]
    return {{
        "$schema": "yggdrasil/design-card-v0",
        "name": name, "kind": kind, "target": target,
        "intent": name + ": describe the core loop here.",
        "inputs": [], "outputs": [],
        "entities": [{{"name": "world", "fields": {{}}, "notes": ""}}],
        "invariants": ["state digest is deterministic per seed"],
        "acceptance": [{{"given": "fresh start",
                        "when": "one full loop",
                        "then": "digest matches"}}],
        "constraints": {{"stdlib_only": True,
                        "network": "deny-by-default"}},
    }}


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send({"ok": True, "error": None,
                        "service": "deskmate"})
        elif self.path == "/card/template":
            self._send({"ok": True, "error": None,
                        "template": TEMPLATE})
        else:
            self._send({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self._send({"ok": False, "error": "bad json"}, 400)
            return
        if self.path == "/card/validate":
            errs = validate_card(req)
            self._send({"ok": True, "error": None,
                        "valid": not errs, "errors": errs})
        elif self.path == "/scaffold":
            self._send({"ok": True, "error": None,
                        "card": scaffold(req)})
        else:
            self._send({"ok": False, "error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with open("port.txt", "w") as fh:
        fh.write(str(srv.server_address[1]))
    print("deskmate up", flush=True)
    srv.serve_forever()
'''

SERVER = (SERVER
          # the embedded source was authored format-style (doubled
          # braces); collapse them now - we inject via .replace()
          .replace("{{", "{").replace("}}", "}")
          .replace("__STRICT__", repr(VALIDATE_STRICT))
          .replace("__TEMPLATE__", repr(CARD_TEMPLATE))
          .replace("__TARGETS__", repr(KNOWN_TARGETS)))

GATE = '''"""Self-test gate for DESKMATE (exit 0 = pass)."""

import json
import os
import subprocess
import sys
import time
import urllib.request

# stale-port guard: a previous attempt's port.txt would point at a
# dead server (fix/retry passes re-weave into the same directory)
if os.path.exists("port.txt"):
    os.remove("port.txt")

proc = subprocess.Popen([sys.executable, "deskmate_server.py"],
                        stdout=subprocess.DEVNULL)
try:
    deadline = time.time() + 10
    while not os.path.exists("port.txt"):
        assert time.time() < deadline, "server never wrote port.txt"
        time.sleep(0.1)
    port = int(open("port.txt").read())
    base = f"http://127.0.0.1:{port}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=5) as r:
            return json.loads(r.read())

    def post(path, obj):
        req = urllib.request.Request(
            base + path, data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    assert get("/health")["ok"] is True, "health failed"
    tpl = get("/card/template")
    assert tpl["ok"] and "entities" in tpl["template"], tpl

    good = post("/scaffold", {"name": "orb-collector",
                              "kind": "game",
                              "target": "godot-game"})
    assert good["ok"] and good["card"]["name"] == "orb-collector", good

    v = post("/card/validate", good["card"])
    assert v["valid"] is True and v["errors"] == [], v

    bad = post("/card/validate", {"name": "", "kind": "weapon"})
    assert bad["valid"] is False and bad["errors"], \
        "strict validation did not bite"
    print("deskmate gate green")
    sys.exit(0)
finally:
    proc.terminate()
'''


def files():
    return {
        "deskmate_server.py": SERVER,
        "verify_deskmate.py": GATE,
        "VENUS.md": VENUS_MD,
    }


VENUS_MD = """\
# DESKMATE for Venus panels

Boot: `python deskmate_server.py` (writes port.txt).
Read the port, then call:

```js
const base = `http://127.0.0.1:${port}`;
await fetch(`${base}/card/template`).then(r => r.json());
await fetch(`${base}/scaffold`, { method: "POST",
  body: JSON.stringify({ name: "my-game", kind: "game" })});
await fetch(`${base}/card/validate`, { method: "POST",
  body: JSON.stringify(card) });
```

Every response carries `error` (null when fine). Loopback only.
"""


FILES = files()
FILES_DEF = FILES  # backwards-compatible alias
FAULTS = {
    # strict validation off -> the bad-card check stops biting
    "no_validation": ("deskmate_server.py",
                      "VALIDATE_STRICT = True",
                      "VALIDATE_STRICT = False"),
    # template endpoint loses its payload
    "lost_template": ("deskmate_server.py",
                      '"template": TEMPLATE',
                      '"template": {}'),
}
