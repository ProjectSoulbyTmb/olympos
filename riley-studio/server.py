#!/usr/bin/env python3
"""server - Riley Studio's loopback-only HTTP API.

    python server.py [--port 8288] [--host 127.0.0.1] [--data-dir PATH]
                     [--comfy-url URL] [--ai-home PATH]

Binds 127.0.0.1 unless explicitly overridden. Endpoints (all JSON,
{"ok": true, ...} envelope):

    GET  /                    tiny human index
    GET  /api/status          engine + comfy + queue vitals
    GET  /api/models          manifest, install state, tier advice
    POST /api/models/pull     {"key": "sd15"} background download
    POST /api/generate        {"kind": "...", "model": "...", params...}
    GET  /api/job/<id>        one job record
    GET  /api/jobs            recent jobs (?limit=N)
    GET  /api/gallery         finished outputs with metadata
    GET  /api/file?p=relpath  serve a generated file (path-jailed)
"""
import argparse
import json
import os
import shutil
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import VERSION, comfy, graphs, models  # noqa: E402
from engine.queue import JobQueue  # noqa: E402


class Engine(object):
    """Process-wide state: queue + download registry."""

    def __init__(self, data_dir, comfy_url, ai_home):
        self.data_dir = data_dir
        self.comfy_url = comfy_url
        self.ai_home = ai_home
        self.queue = JobQueue(data_dir, ai_home=ai_home, comfy_base=comfy_url)
        self.downloads = {}   # key -> {"written":n,"total":n,"error":None}
        self._dl_lock = threading.Lock()
        self.queue.start()

    def snapshot(self):
        st = comfy.status(self.comfy_url)
        free = shutil.disk_usage(self.data_dir).free
        return {
            "version": VERSION,
            "comfy": {"up": bool(st),
                      "vram_total_mb": ((st or {}).get("devices") or [{}])[0]
                      .get("vram_total", 0) // (1024 * 1024)},
            "queue": self.queue.counts(),
            "disk_free": free,
            "ai_home": self.ai_home,
            "installed_models": sorted(models.installed(self.ai_home)),
        }

    def pull(self, key):
        meta = models.MODELS.get(key)
        if not meta:
            return False, "unknown model %r" % key
        with self._dl_lock:
            if key in self.downloads:
                return False, "already downloading"
            self.downloads[key] = {"written": 0, "total": 0, "error": None}

        def worker():
            try:
                for entry in meta["files"]:
                    dest = models._file_dest(self.ai_home, entry)

                    def cb(written, total, key=key):
                        d = self.downloads.get(key)
                        if d:
                            d["written"], d["total"] = written, total
                    if os.path.isfile(dest):
                        continue
                    models.download(entry["url"], dest, progress_cb=cb)
                d = self.downloads.get(key)
                if d:
                    d["done"] = True
            except Exception as exc:  # noqa: BLE001 - reported to client
                d = self.downloads.get(key)
                if d:
                    d["error"] = str(exc)[:400]

        threading.Thread(target=worker, daemon=True).start()
        return True, "started"


def _gallery(data_dir):
    root = os.path.join(data_dir, "outputs")
    items = []
    if not os.path.isdir(root):
        return items
    for jid in sorted(os.listdir(root), reverse=True):
        folder = os.path.join(root, jid)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            ext = name.rsplit(".", 1)[-1].lower()
            if ext in ("png", "jpg", "jpeg", "webp"):
                kind = "image"
            elif ext in ("webm", "mp4", "gif"):
                kind = "video"
            else:
                continue
            items.append({
                "job": jid, "name": name, "kind": kind,
                "bytes": os.path.getsize(path),
                "mtime": int(os.path.getmtime(path)),
                "path": "outputs/%s/%s" % (jid, name)})
    return items


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RileyStudio/" + VERSION

        def log_message(self, fmt, *args):  # quiet by default
            pass

        def _json(self, code, payload=None, **extra):
            data = dict(payload or {})
            data.update(extra)
            body = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path.rstrip("/") or "/"
            q = urllib.parse.parse_qs(parsed.query)
            if route == "/":
                return self._json(200, {
                    "ok": True, "service": "riley-studio",
                    "version": VERSION,
                    "see": ["/api/status", "/api/models", "/api/gallery"]})
            if route == "/api/status":
                return self._json(200, dict(ok=True, **engine.snapshot()))
            if route == "/api/models":
                installed = models.installed(engine.ai_home)
                view = models.manifest_view()
                for key, item in view.items():
                    have = installed.get(key, {})
                    need = len(models.MODELS[key]["files"])
                    item["complete"] = len(have) == need
                    item["have_roles"] = sorted(have)
                dl = {k: dict(v) for k, v in engine.downloads.items()}
                return self._json(
                    200, ok=True, models=view, downloads=dl,
                    recommended=models.pick_tier(),
                    vram_mb=models.detect_vram_mb())
            if route == "/api/jobs":
                limit = min(200, int((q.get("limit") or ["50"])[0]))
                return self._json(200, ok=True,
                                  jobs=engine.queue.recent(limit))
            if route.startswith("/api/job/"):
                jid = route.split("/")[-1]
                rec = engine.queue.get(jid)
                if not rec:
                    return self._json(404, {"ok": False,
                                            "error": "no such job"})
                return self._json(200, ok=True, job=rec)
            if route == "/api/gallery":
                return self._json(200, ok=True,
                                  items=_gallery(engine.data_dir))
            if route == "/api/file":
                rel = (q.get("p") or [""])[0]
                base = os.path.realpath(engine.data_dir)
                full = os.path.realpath(os.path.join(base, rel))
                if not full.startswith(base + os.sep):
                    return self._json(403, {"ok": False,
                                            "error": "jailed path"})
                if not os.path.isfile(full):
                    return self._json(404, {"ok": False,
                                            "error": "not found"})
                body = open(full, "rb").read()
                ctype = "application/octet-stream"
                if full.endswith(".png"):
                    ctype = "image/png"
                elif full.endswith(".webm"):
                    ctype = "video/webm"
                elif full.endswith(".gif"):
                    ctype = "image/gif"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            route = urllib.parse.urlparse(self.path).path.rstrip("/")
            try:
                length = min(int(self.headers.get("Content-Length") or 0),
                             1 << 20)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json(400, {"ok": False, "error": "bad json"})
            if route == "/api/generate":
                kind = str(payload.pop("kind", ""))
                allowed = set(graphs.BUILDERS) | \
                    {"upscale", "export_mp4", "export_gif"}
                if not kind or kind not in allowed:
                    return self._json(400, {
                        "ok": False,
                        "error": "kind must be one of %s"
                                 % sorted(allowed)})
                jid = engine.queue.submit(kind, payload)
                return self._json(202, ok=True, job=jid)
            if route == "/api/models/pull":
                key = str(payload.get("key", ""))
                started, msg = engine.pull(key)
                code = 202 if started else 409
                return self._json(code, ok=started, message=msg)
            return self._json(404, {"ok": False, "error": "not found"})

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="Riley Studio engine API")
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    default_data = os.environ.get("RILEY_STUDIO_DATA") or \
        os.path.join(here, "data")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8288)
    ap.add_argument("--data-dir", default=default_data)
    ap.add_argument("--comfy-url",
                    default=os.environ.get("RILEY_STUDIO_COMFY_URL")
                    or comfy.DEFAULT_BASE)
    ap.add_argument("--ai-home", default=models.default_ai_home(repo_root))
    args = ap.parse_args(argv)

    os.makedirs(args.data_dir, exist_ok=True)
    engine = Engine(args.data_dir, args.comfy_url, args.ai_home)
    httpd = ThreadingHTTPServer((args.host, args.port),
                                make_handler(engine))
    print("riley-studio engine v%s on http://%s:%s (data=%s, ai=%s)"
          % (VERSION, args.host, httpd.server_address[1],
             args.data_dir, args.ai_home), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
