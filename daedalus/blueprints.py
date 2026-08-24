"""DAEDALUS blueprints - server designs the workshop can weave.

Each blueprint is a complete deterministic design: file templates plus
the self-test gate that proves a woven instance works. Blueprints may
declare named `faults`; injecting one exercises the workshop's
verify-fix-retry loop offline - proof the builder converges without
needing an LLM.
"""

import sys

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

proc = subprocess.Popen([sys.executable, "echo_server.py", "0"],
                        stdout=subprocess.PIPE, text=True)
try:
    line = proc.stdout.readline()
    port = int(line.split("on ")[1])
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
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
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=5) as r:
        assert json.loads(r.read()).get("ok") is True
    print("health gate green")
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
        # the spec asks for them; the fix pass restores canonical text.
        "faults": {
            "drop_echo": ("echo_server.py",
                          'obj["echo"] = True', "pass"),
        },
    },
    "http-health": {
        "description": "minimal HTTP /health server",
        "files": {"health_server.py": HTTP_HEALTH,
                  "verify_health.py": HTTP_HEALTH_VERIFY},
        "gate": [sys.executable, "verify_health.py"],
        "faults": {},
    },
}


def blueprint_names():
    return sorted(BLUEPRINTS)
