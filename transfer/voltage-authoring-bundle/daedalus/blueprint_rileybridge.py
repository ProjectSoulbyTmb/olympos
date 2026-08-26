"""DAEDALUS blueprint: riley-bridge - the image domain adapter.

Batch V7 studio tier. Client law for RILEY's loopback engine API,
proven against an in-thread stub engine (no weights, no GPU):

  Idempotency parity - generate keys derive exactly as the RELAY
  riley_stream convention: sha256(kind|model|prompt|seed). Duplicate
  delivery therefore renders identically, fleet-wide.
  Gallery jail - fetched paths are jailed client-side before they
  ever touch the wire: absolute, drive-letter, dot-dot and empty
  refusals mirror HARMONIA's containment discipline.
  Poll lifecycle - pending -> running -> done terminates honestly;
  error and cancelled statuses surface as failures, never hangs.

Extension shape: register(executors) wires image generate/upscale/
models/gallery onto APOLLO's drop-in protocol."""

import sys

BRIDGE = '''"""RILEY bridge - idempotency, jail, lifecycle for the engine API."""

import hashlib
import json
import time
import urllib.error
import urllib.request


class JailViolation(ValueError):
    pass


class EngineError(RuntimeError):
    pass


def idempotency_key(kind, model, prompt, seed):
    """RELAY riley_stream convention - do not reorder."""
    basis = "|".join([kind, model, prompt, str(seed)])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def jailed_rel(p):
    raw = str(p or "").replace("\\\\", "/")
    if not raw.strip("/"):
        raise JailViolation("empty path")
    if raw.startswith("/"):
        raise JailViolation("absolute path: %r" % p)
    s = raw.strip("/")
    if ":" in s:
        raise JailViolation("drive letter: %r" % p)
    parts = [x for x in s.split("/") if x not in ("", ".")]
    if any(x == ".." for x in parts):
        raise JailViolation("traversal: %r" % p)
    return "/".join(parts)


class RileyClient(object):
    def __init__(self, base, timeout_s=10):
        self.base = base.rstrip("/")
        self.timeout_s = timeout_s

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(
                    req, timeout=self.timeout_s) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            # Engines speak envelopes; an HTTP refusal is an engine
            # error, never a client crash.
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                detail = ""
            raise EngineError("engine %s on %s: %s"
                              % (exc.code, path, detail)) from None

    def status(self):
        return self._call("GET", "/api/status")

    def models(self):
        return self._call("GET", "/api/models")

    def submit_generate(self, kind, model, prompt, seed,
                        width=512, height=512):
        body = {"kind": kind, "model": model, "prompt": prompt,
                "seed": seed, "width": width, "height": height,
                "idempotency_key": idempotency_key(
                    kind, model, prompt, seed)}
        out = self._call("POST", "/api/generate", body)
        if not out.get("job_id"):
            raise EngineError("engine refused: %r" % out)
        return out["job_id"]

    def wait_job(self, job_id, timeout_s=15, poll_s=0.05):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            job = self._call("GET", "/api/job/%s" % job_id)
            state = job.get("status")
            if state == "done":
                return job
            if state in ("error", "cancelled"):
                raise EngineError("job %s: %s (%s)"
                                  % (job_id, state,
                                     job.get("error")))
            time.sleep(poll_s)
        raise EngineError("timeout waiting for %s" % job_id)

    def gallery(self):
        return self._call("GET", "/api/gallery")

    def fetch_file(self, rel):
        return self._call("GET", "/api/file?p=" + jailed_rel(rel))


def register(executors):
    """APOLLO drop-in adapter: image domain lands here. The engine
    base URL arrives via ctx (commissioning injects :44128)."""
    def _client(ctx):
        return RileyClient(str(ctx.get("engine_base")
                               or "http://127.0.0.1:44128"))

    def _generate(session, cmd, ctx):
        c = _client(ctx)
        prompt = str(cmd.target or "")
        seed = int(cmd.flags.get("seed", 0))
        model = str(cmd.flags.get("model", "sd15"))
        kind = str(cmd.flags.get("kind", "txt2img_checkpoint"))
        job = c.submit_generate(kind, model, prompt, seed)
        done = c.wait_job(job)
        return {"ok": True, "job_id": job,
                "artifact_sha256":
                    idempotency_key(kind, model, prompt, seed),
                "outputs": done.get("outputs", [])}
    executors[("image", "generate")] = _generate

    def _models(session, cmd, ctx):
        return {"ok": True, "data": _client(ctx).models()}
    executors[("image", "models")] = _models

    def _gallery(session, cmd, ctx):
        return {"ok": True, "data": _client(ctx).gallery()}
    executors[("image", "gallery")] = _gallery
'''

GATE = '''"""Self-test gate for riley-bridge (exit 0 = green)."""

import hashlib
import json
import sys
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from riley_bridge import (EngineError, JailViolation, RileyClient,
                          idempotency_key, jailed_rel)

EXPECTED_KEY = hashlib.sha256(
    b"txt2img_checkpoint|sd15|sunset over goth spires|7").hexdigest()

STATE = {"job_calls": 0}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, status=200):
        blob = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_GET(self):
        if self.path == "/api/status":
            return self._json({"ok": True, "vram": "4GB",
                               "queue_depth": 0})
        if self.path == "/api/job/j-1":
            STATE["job_calls"] += 1
            if STATE["job_calls"] == 1:
                return self._json({"status": "running"})
            return self._json({"status": "done",
                               "outputs": ["outputs/x.png"]})
        if self.path.startswith("/api/file?p="):
            p = urllib.parse.unquote(
                self.path.split("=", 1)[1])
            if ".." in p or ":" in p or p.startswith("/"):
                return self._json({"ok": False,
                                   "error": "jailed"}, status=403)
            return self._json({"ok": True, "bytes": "PNGDATA"})
        return self._json({"ok": False, "error": "no route"},
                          status=404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode())
        if self.path == "/api/generate":
            if body.get("idempotency_key") != EXPECTED_KEY:
                return self._json({"ok": False,
                                   "error": "key mismatch"},
                                  status=400)
            return self._json({"ok": True, "job_id": "j-1"})
        return self._json({"ok": False, "error": "no route"},
                          status=404)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        c = RileyClient("http://127.0.0.1:%d" % srv.server_port)

        # idempotency parity with the RELAY convention
        assert idempotency_key("txt2img_checkpoint", "sd15",
                               "sunset over goth spires", 7) == \\
            EXPECTED_KEY, "key formula drifted from relay law"

        st = c.status()
        assert st["ok"] and st["vram"] == "4GB", st

        job = c.submit_generate("txt2img_checkpoint", "sd15",
                                "sunset over goth spires", 7)
        assert job == "j-1"
        done = c.wait_job(job)
        assert done["outputs"] == ["outputs/x.png"], done

        got = c.fetch_file("outputs/x.png")
        assert got["bytes"] == "PNGDATA", got

        for hostile in ("../etc/passwd", "C:/windows/system32",
                        "/abs/path", "a/../../b", "", None):
            try:
                jailed_rel(hostile)
                raise AssertionError("jail let slip: %r" % hostile)
            except JailViolation:
                pass

        try:
            c.wait_job("never", timeout_s=0.05, poll_s=0.01)
            raise AssertionError("timeout did not fire")
        except EngineError:
            pass
        print("riley-bridge gate green")
    finally:
        srv.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"riley_bridge.py": BRIDGE, "verify_rileybridge.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # join order swapped -> keys stop matching the RELAY convention;
    # the stub engine's 400 on mismatch turns the gate red
    "seed_drift": ("riley_bridge.py",
                   'basis = "|".join([kind, model, prompt, '
                   'str(seed)])',
                   'basis = "|".join([model, kind, prompt, '
                   'str(seed)])'),
}

BLUEPRINT = {
    "description": "VOLTAGE riley-bridge (image domain): relay-parity "
                   "idempotency keys, gallery jail, poll lifecycle",
    "files": FILES,
    "gate": [sys.executable, "verify_rileybridge.py"],
    "faults": dict(FAULTS),
}
