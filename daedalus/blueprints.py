"""DAEDALUS blueprints - server designs the workshop can weave.

Each blueprint is a complete deterministic design: file templates plus
the self-test gate that proves a woven instance works. Blueprints may
declare named `faults`; injecting one exercises the workshop's
verify-fix-retry loop offline - proof the builder converges without
needing an LLM.
"""

import json
import os
import sys

_GOTH_CORPUS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge", "goth", "corpus.json")
try:
    with open(_GOTH_CORPUS_PATH, encoding="utf-8") as _fh:
        GOTH_CORPUS_SNAPSHOT = _fh.read()
except OSError:  # pragma: no cover - fallback keeps weaving possible
    GOTH_CORPUS_SNAPSHOT = json.dumps({
        "policy": "cultural/aesthetic material only; nothing sexualized",
        "topics": {}, "facts_nightly_pool": [],
    })

ECHO_SERVER = '''"""JSON-lines echo server (DAEDALUS-woven).

House contract: one JSON object per line in; the same object echoed
with "echo": true added. Run: python echo_server.py [port]
"""

import json
import socket
import sys


def serve(host="127.0.0.1", port=0):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    srv.settimeout(0.5)
    print(f"echo up on {srv.getsockname()[1]}", flush=True)
    try:
        while True:
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            with conn:
                buf = conn.makefile("rwb")
                for raw in buf:
                    if not raw.strip():
                        continue
                    obj = json.loads(raw.decode("utf-8"))
                    obj["echo"] = True
                    buf.write((json.dumps(obj) + "\\n")
                              .encode("utf-8"))
                    buf.flush()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
'''

ECHO_VERIFY = '''"""Self-test gate for the woven echo server (exit 0 = pass)."""

import json
import socket
import subprocess
import sys
import time

proc = subprocess.Popen([sys.executable, "echo_server.py", "0"],
                        stdout=subprocess.PIPE, text=True)
try:
    line = proc.stdout.readline()
    port = int(line.split("on ")[1])
    # readiness retry: under parallel load the listener can refuse
    # its first moments - poll until the deadline instead of dying
    deadline = time.time() + 15
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            break
        except OSError:
            assert proc.poll() is None, "server died before accepting"
            assert time.time() < deadline, "server never accepted"
            time.sleep(0.1)
    f = s.makefile("rwb")
    f.write(b'{"ping": 1}\\n')
    f.flush()
    resp = json.loads(f.readline().decode("utf-8"))
    assert resp.get("echo") is True, f"echo flag missing: {resp}"
    assert resp.get("ping") == 1, resp
    s.close()
    print("echo gate green")
    sys.exit(0)
finally:
    proc.terminate()
'''

HTTP_HEALTH = '''"""Minimal HTTP /health server (DAEDALUS-woven).

Writes its bound port to port.txt so the gate can find it.
"""

import http.server
import json


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    import sys
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    with open("port.txt", "w") as fh:
        fh.write(str(srv.server_address[1]))
    print("health up", flush=True)
    srv.serve_forever()
'''

HTTP_HEALTH_VERIFY = '''"""Self-test gate for the woven health server."""

import json
import subprocess
import sys
import time
import urllib.request

proc = subprocess.Popen([sys.executable, "health_server.py"],
                        stdout=subprocess.DEVNULL)
try:
    deadline = time.time() + 10
    while not __import__("os").path.exists("port.txt"):
        assert time.time() < deadline, "server never wrote port.txt"
        time.sleep(0.1)
    port = int(open("port.txt").read())
    # readiness retry: a refused connection right after bind is a
    # scheduling artifact under load, not a broken weave - poll on
    deadline = time.time() + 15
    while True:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=5) as r:
                assert json.loads(r.read()).get("ok") is True
            break
        except AssertionError:
            raise
        except Exception as exc:  # noqa: BLE001 - gate retries all
            assert proc.poll() is None, \
                "server died before accepting: %r" % (exc,)
            assert time.time() < deadline, "server never answered"
            time.sleep(0.1)
    print("health gate green")
    sys.exit(0)
finally:
    proc.terminate()
'''

KV_SERVER = '''"""Persistent JSON-lines KV store (DAEDALUS-woven).

Protocol: {"cmd": "set", "k": ..., "v": ...} | {"cmd": "get", "k": ...}
         | {"cmd": "del", "k": ...} - one JSON response per line.
State persists to kv.json on every mutation. Run: python kv_server.py
"""

import json
import os
import socket
import sys

MODE = "{{MODE}}"


def _load():
    if os.path.exists("kv.json"):
        with open("kv.json", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def serve(host="127.0.0.1", port=0):
    store = _load()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    srv.settimeout(0.5)
    print(f"kv up on {srv.getsockname()[1]} mode={MODE}", flush=True)
    try:
        while True:
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            with conn:
                buf = conn.makefile("rwb")
                for raw in buf:
                    if not raw.strip():
                        continue
                    req = json.loads(raw.decode("utf-8"))
                    cmd = req.get("cmd")
                    if cmd == "set":
                        store[req["k"]] = req["v"]
                        resp = {"ok": True}
                    elif cmd == "get":
                        resp = {"ok": True,
                                "v": store.get(req["k"])}
                    elif cmd == "del":
                        store.pop(req["k"], None)
                        resp = {"ok": True}
                    else:
                        resp = {"ok": False,
                                "error": f"unknown cmd {cmd!r}"}
                    if cmd in ("set", "del"):
                        with open("kv.json", "w",
                                  encoding="utf-8") as fh:
                            json.dump(store, fh)
                    buf.write((json.dumps(resp) + "\\n")
                              .encode("utf-8"))
                    buf.flush()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
'''

KV_VERIFY = '''"""Self-test gate for the woven KV store (exit 0 = pass)."""

import json
import socket
import subprocess
import sys
import time

src = open("kv_server.py", encoding="utf-8").read()
assert "{{" not in src, "unresolved template placeholder"

proc = subprocess.Popen([sys.executable, "kv_server.py", "0"],
                        stdout=subprocess.PIPE, text=True)
try:
    line = proc.stdout.readline()
    port = int(line.split("on ")[1].split()[0])
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    f = s.makefile("rwb")

    def ask(obj):
        f.write((json.dumps(obj) + "\\n").encode("utf-8"))
        f.flush()
        return json.loads(f.readline().decode("utf-8"))

    assert ask({"cmd": "set", "k": "a", "v": 7})["ok"] is True
    got = ask({"cmd": "get", "k": "a"})
    assert got["v"] == 7, got
    ask({"cmd": "del", "k": "a"})
    assert ask({"cmd": "get", "k": "a"})["v"] is None
    persisted = json.load(open("kv.json", encoding="utf-8"))
    assert "a" not in persisted, "del did not persist"
    s.close()
    print("kv gate green")
    sys.exit(0)
finally:
    proc.terminate()
'''

BEAT_WORKER = '''"""Beat worker (DAEDALUS-woven): bounded heartbeat loop.

Writes beats.jsonl, one line per beat, then exits cleanly -
the house liveness doctrine in miniature.
"""

import json
import time

BEATS = {{BEATS}}
INTERVAL_S = {{INTERVAL_S}}

with open("beats.jsonl", "w", encoding="utf-8") as fh:
    for i in range(BEATS):
        fh.write(json.dumps({"beat": i + 1,
                             "t": round(time.time(), 3)}) + "\\n")
        fh.flush()
        time.sleep(INTERVAL_S)
print(f"{BEATS} beats done", flush=True)
'''

BEAT_VERIFY = '''"""Self-test gate for the woven beat worker."""

import json
import subprocess
import sys

proc = subprocess.Popen([sys.executable, "beat_worker.py"],
                        stdout=subprocess.PIPE, text=True)
try:
    out = proc.communicate(timeout=30)[0]
    assert proc.returncode == 0, f"worker exited {proc.returncode}"
    lines = [ln for ln in open("beats.jsonl", encoding="utf-8")
             if ln.strip()]
    assert lines, "no beats written"
    first = json.loads(lines[0])
    assert first["beat"] == 1 and "t" in first, first
    print("beat gate green")
    sys.exit(0)
finally:
    proc.terminate()
'''


GOTH_ORACLE = '''"""Goth oracle - JSON-lines culture query server (DAEDALUS-woven).

Protocol: one JSON object per line in, one JSON response per line out.
  {"cmd": "topics"}                    -> {"ok": true, "topics": [...]}
  {"cmd": "query", "topic": "styles"}  -> {"ok": true, "topic": ..., "data": ...}
  {"cmd": "fact", "n": 3}              -> {"ok": true, "fact": "..."}
Corpus loads from goth_corpus.json beside this file. Content policy:
cultural/aesthetic material only; nothing sexualized.
Run: python goth_oracle.py [port]
"""

import json
import os
import socket
import sys

ALIASES = {
    "history": "history", "timeline": "history",
    "styles": "substyles", "substyles": "substyles",
    "icons": "icons", "muses": "icons",
    "music": "music_map", "bands": "music_map",
    "look": "fashion_guide", "fashion": "fashion_guide",
    "women": "women_of_goth", "muses": "icons",
    "aesthetics": "mature_aesthetics_academic",
    "glossary": "glossary",
}


def _load():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "goth_corpus.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def serve(host="127.0.0.1", port=0):
    corpus = _load()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    srv.settimeout(0.5)
    print(f"goth-oracle up on {srv.getsockname()[1]}", flush=True)
    try:
        while True:
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            with conn:
                buf = conn.makefile("rwb")
                for raw in buf:
                    if not raw.strip():
                        continue
                    req = json.loads(raw.decode("utf-8"))
                    cmd = req.get("cmd")
                    if cmd == "topics":
                        keys = sorted(ALIASES)
                        resp = {"ok": True, "topics": keys}
                    elif cmd == "query":
                        key = ALIASES.get(req.get("topic", ""))
                        data = corpus["topics"].get(key) if key else None
                        if data is None:
                            resp = {"ok": False,
                                    "error": ("unknown topic "
                                              f"{req.get('topic')!r}")}
                        else:
                            resp = {"ok": True, "topic": key,
                                    "data": data}
                    elif cmd == "fact":
                        pool = corpus.get("facts_nightly_pool", [])
                        n = abs(int(req.get("n", 0)))
                        resp = {"ok": True,
                                "fact": (pool[n % len(pool)]
                                         if pool else "")}
                    else:
                        resp = {"ok": False,
                                "error": f"unknown cmd {cmd!r}"}
                    buf.write((json.dumps(resp) + "\\n")
                              .encode("utf-8"))
                    buf.flush()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve(port=int(sys.argv[1]) if len(sys.argv[1:]) else 0)
'''

GOTH_ORACLE_VERIFY = '''"""Self-test gate for the woven goth oracle (exit 0 = pass)."""

import json
import socket
import subprocess
import sys

proc = subprocess.Popen([sys.executable, "goth_oracle.py", "0"],
                        stdout=subprocess.PIPE, text=True)
try:
    line = proc.stdout.readline()
    port = int(line.split("on ")[1].split()[0])
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    f = s.makefile("rwb")

    def ask(obj):
        f.write((json.dumps(obj) + "\\n").encode("utf-8"))
        f.flush()
        return json.loads(f.readline().decode("utf-8"))

    topics = ask({"cmd": "topics"})
    assert topics.get("ok") is True, topics
    assert len(topics["topics"]) >= 6, topics
    assert "styles" in topics["topics"], topics

    got = ask({"cmd": "query", "topic": "styles"})
    assert got.get("ok") is True, got
    names = [entry["name"] for entry in got["data"]]
    assert any(n == "Trad Goth" for n in names), names

    hist = ask({"cmd": "query", "topic": "history"})
    assert hist.get("ok") is True and len(hist["data"]) >= 5, hist

    women = ask({"cmd": "query", "topic": "women"})
    assert women.get("ok") is True, women
    assert "frontwomen_beyond_icons" in women["data"], women

    bad = ask({"cmd": "query", "topic": "nope"})
    assert bad.get("ok") is False, bad

    fact = ask({"cmd": "fact", "n": 2})
    assert fact.get("ok") is True and fact["fact"], fact
    again = ask({"cmd": "fact", "n": 2})
    assert again["fact"] == fact["fact"], "fact not deterministic"
    s.close()
    print("goth-oracle gate green")
    sys.exit(0)
finally:
    proc.terminate()
'''


BLUEPRINTS = {
    "jsonl-echo": {
        "description": "authoritative JSON-lines echo server",
        "files": {"echo_server.py": ECHO_SERVER,
                  "verify_echo.py": ECHO_VERIFY},
        "gate": [sys.executable, "verify_echo.py"],
        # faults: name -> (file, find, replace). Injected on weave when
        # the spec asks for them; the repair pass restores canonical
        # text. "cosmetic_doc" is deliberately innocent - it exercises
        # culprit isolation (an injected change that cannot fail).
        # NOTE: Windows clamps negative listen() backlogs and
        # json.loads accepts bytes on py3.6+ - both make innocent
        # faults. A real independent breaker must fail fast AND
        # independently: silencing the startup banner starves the
        # gate's port discovery.
        "faults": {
            "drop_echo": ("echo_server.py",
                          'obj["echo"] = True', "pass"),
            "silent_start": ("echo_server.py",
                             'print(f"echo up on '
                             '{srv.getsockname()[1]}", flush=True)',
                             "pass"),
            "cosmetic_doc": ("echo_server.py",
                             "(DAEDALUS-woven)", "(rewoven)"),
        },
    },
    "http-health": {
        "description": "minimal HTTP /health server",
        "files": {"health_server.py": HTTP_HEALTH,
                  "verify_health.py": HTTP_HEALTH_VERIFY},
        "gate": [sys.executable, "verify_health.py"],
        "faults": {},
    },

    "kv-store": {
        "description": "persistent JSON-lines key/value store",
        "files": {"kv_server.py": KV_SERVER,
                  "verify_kv.py": KV_VERIFY},
        "gate": [sys.executable, "verify_kv.py"],
        "params": {"MODE": "lean"},
        "faults": {
            # one unambiguous line - skipping the dump skips persistence
            "skip_persist": ("kv_server.py",
                             "json.dump(store, fh)", "pass"),
        },
    },
    "beat-worker": {
        "description": "bounded heartbeat loop writing beats.jsonl",
        "files": {"beat_worker.py": BEAT_WORKER,
                  "verify_beat.py": BEAT_VERIFY},
        "gate": [sys.executable, "verify_beat.py"],
        "params": {"BEATS": "3", "INTERVAL_S": "0.05"},
        "faults": {
            "zero_beats": ("beat_worker.py",
                           "range(BEATS)", "range(0)"),
        },
    },
    # Godot 4.x orb-collector: weave-time-baked world; the self-test
    # gate is a pure-Python deterministic twin proving replay + WIN
    # headlessly (no engine binary needed). See blueprint_godot.py.

    "goth-oracle": {
        "description": ("gothic culture query server over "
                        "knowledge/goth/corpus.json (cultural material only)"),
        "files": {"goth_oracle.py": GOTH_ORACLE,
                  "goth_corpus.json": GOTH_CORPUS_SNAPSHOT,
                  "verify_goth.py": GOTH_ORACLE_VERIFY},
        "gate": [sys.executable, "verify_goth.py"],
        "faults": {
            # empty topic index - independent breaker: starves the
            # gate's first assertion until the repair pass restores it
            "empty_index": ("goth_oracle.py",
                            "keys = sorted(ALIASES)", "keys = []"),
        },
    },
}
try:
    from daedalus.blueprint_godot import FILES as _GODOT_FILES, \
        FAULTS as _GODOT_FAULTS
    BLUEPRINTS["godot-game"] = {
        "description": "deterministic Godot orb-collector "
                       "(python-twin proven)",
        "files": _GODOT_FILES,
        "gate": [sys.executable, "verify_game_twin.py"],
        "faults": dict(_GODOT_FAULTS),
    }
except ImportError:  # pragma: no cover - optional target
    pass

try:
    from daedalus.blueprint_deskmate import FILES as _DESK_FILES, \
        FAULTS as _DESK_FAULTS
    BLUEPRINTS["deskmate"] = {
        "description": "local project-design desk for VENUS "
                       "(card template/validate/scaffold)",
        "files": _DESK_FILES,
        "gate": [sys.executable, "verify_deskmate.py"],
        "faults": dict(_DESK_FAULTS),
    }
except ImportError:  # pragma: no cover - optional target
    pass


def blueprint_names():
    return sorted(BLUEPRINTS)
