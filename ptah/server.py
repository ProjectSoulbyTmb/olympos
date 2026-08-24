"""PTAH server - local REST control plane (stdlib http.server).

Endpoints (all JSON; loopback by default):

  GET  /healthz                                  liveness + version
  GET  /api/v1/conversations                     list conversations
  POST /api/v1/conversations      {workspace}    create conversation
  GET  /api/v1/conversations/{id}                metadata + status
  POST /api/v1/conversations/{id}/messages       {text, confirm?, wait?}
       wait=true  -> run synchronously, return final status
       wait=false -> run on a worker thread, poll via events
  GET  /api/v1/conversations/{id}/events?after=N incremental event feed

Optional bearer auth: pass token=... (Authorization: Bearer <token>).
The kernel itself is the same object the CLI drives - one brain, two
fronts.
"""

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ptah import content


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def make_handler(store, runner, token=None):
    """Build a request handler bound to a Store and a runner callback.

    runner(conversation, text, confirm) -> RunResult
    """

    class Handler(BaseHTTPRequestHandler):
        server_version = f"ptah/{content.VERSION}"

        def log_message(self, fmt, *args):     # quiet by default
            pass

        # ------------------------------------------------------ helpers
        def _json(self, payload, status=200):
            blob = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)

        def _authed(self):
            if not token:
                return True
            header = self.headers.get("authorization", "")
            return header == f"Bearer {token}"

        def _body(self):
            try:
                length = int(self.headers.get("content-length", "0"))
                data = json.loads(
                    self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, json.JSONDecodeError):
                raise ApiError(400, "invalid JSON body")
            if not isinstance(data, dict):
                raise ApiError(400, "JSON body must be an object")
            return data

        def _conversation(self, cid):
            conv = store.get(cid)
            if conv is None:
                raise ApiError(404, f"no such conversation: {cid}")
            return conv

        # ------------------------------------------------------- routes
        def do_GET(self):                      # noqa: N802 - stdlib API
            parsed = urllib.parse.urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            try:
                if parsed.path == "/healthz":
                    return self._json({"status": "ok",
                                       "version": content.VERSION})
                if not self._authed():
                    return self._json({"error": "unauthorized"}, 401)
                if parts[:3] == ["api", "v1", "conversations"]:
                    if len(parts) == 3:
                        return self._json(
                            {"conversations": store.list()})
                    cid = parts[3]
                    conv = self._conversation(cid)
                    if len(parts) == 4:
                        return self._json(conv.meta)
                    if len(parts) == 5 and parts[4] == "events":
                        q = urllib.parse.parse_qs(parsed.query)
                        after = int((q.get("after") or ["0"])[0])
                        chunk, total = conv.slice(after)
                        return self._json({
                            "status": conv.status,
                            "total": total,
                            "events": [e.to_dict() for e in chunk]})
                raise ApiError(404, "unknown route")
            except ApiError as exc:
                return self._json({"error": exc.message}, exc.status)
            except (TypeError, ValueError) as exc:
                return self._json({"error": str(exc)}, 400)

        def do_POST(self):                     # noqa: N802 - stdlib API
            parts = [p for p in urllib.parse.urlparse(self.path).path.split("/")
                     if p]
            try:
                if not self._authed():
                    return self._json({"error": "unauthorized"}, 401)
                if parts[:3] == ["api", "v1", "conversations"]:
                    if len(parts) == 3:
                        body = self._body()
                        workspace = body.get("workspace") or "."
                        conv = store.create(workspace)
                        return self._json(conv.meta, 201)
                    if len(parts) == 5 and parts[4] == "messages":
                        conv = self._conversation(parts[3])
                        body = self._body()
                        text = str(body.get("text", ""))
                        confirm = bool(body.get("confirm", False))
                        wait = bool(body.get("wait", True))
                        timeout_s = min(float(body.get("timeout_s", 180)),
                                        600.0)
                        if conv.status == conv.RUNNING:
                            raise ApiError(409,
                                           "conversation already running")
                        result_holder = {}

                        def work():
                            result_holder["result"] = runner(
                                conv, text, confirm)

                        if wait:
                            worker = threading.Thread(target=work)
                            worker.start()
                            worker.join(timeout_s)
                            if worker.is_alive():
                                raise ApiError(504, "run timed out")
                            res = result_holder.get("result")
                            return self._json({
                                "id": conv.id, "status": conv.status,
                                "reason": getattr(res, "reason", None),
                                "iterations": getattr(res, "iterations", 0),
                            })
                        threading.Thread(target=work, daemon=True).start()
                        return self._json({"id": conv.id, "started": True},
                                          202)
                raise ApiError(404, "unknown route")
            except ApiError as exc:
                return self._json({"error": exc.message}, exc.status)
            except (TypeError, ValueError) as exc:
                return self._json({"error": str(exc)}, 400)

    return Handler


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(store, runner, host=None, port=None, token=None):
    """Blocking serve loop. Returns the server object after shutdown."""
    host = host or content.SERVER_HOST
    port = port if port is not None else content.SERVER_PORT
    handler = make_handler(store, runner, token=token)
    httpd = ApiServer((host, port), handler)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return httpd
