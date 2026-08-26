"""MIND surfaces - HTTP plumbing: request/response types + server loop.

The loop knows nothing about OBS or production state. It parses a
request, asks the registry which surface owns the route, writes the
answer. That is all it will ever do.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_BODY_BYTES = 64 * 1024


class RequestError(ValueError):
    pass


class ServerError(Exception):
    pass


class Request:
    def __init__(self, method: str, path: str, query: dict,
                 headers, body: bytes, remote: str):
        self.method = method
        self.path = path
        self.query = query          # first-value dict
        self.headers = headers      # case-insensitive
        self.body = body
        self.remote = remote

    def json(self) -> dict:
        if not self.body:
            return {}
        try:
            parsed = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestError(f"body is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RequestError("body must be a JSON object")
        return parsed

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name, default)


class Response:
    def __init__(self, status: int = 200, body: bytes = b"",
                 content_type: str = "text/plain; charset=utf-8"):
        self.status = int(status)
        self.body = bytes(body)
        self.content_type = content_type

    @classmethod
    def json(cls, obj, status: int = 200) -> "Response":
        return cls(status=status,
                   body=json.dumps(obj).encode("utf-8"),
                   content_type="application/json")

    @classmethod
    def html(cls, text: str, status: int = 200) -> "Response":
        return cls(status=status, body=text.encode("utf-8"),
                   content_type="text/html; charset=utf-8")

    @classmethod
    def text(cls, message: str, status: int = 200) -> "Response":
        return cls(status=status, body=message.encode("utf-8"))


class StreamingResponse(Response):
    """No Content-Length; close-delimited stream of byte chunks (SSE)."""

    streaming = True

    def __init__(self, content_type: str, chunks):
        super().__init__(200, b"", content_type)
        self.chunks = chunks


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    registry = None

    def log_message(self, fmt, *args):
        pass  # quiet; the journal is the record

    def _run(self):
        method = self.command
        split = urlsplit(self.path)
        query = {k: v[0] for k, v in
                 parse_qs(split.query, keep_blank_values=True).items()}
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._write(Response.json({"error": "body too large"},
                                      status=413))
            return
        body = self.rfile.read(length) if length else b""
        request = Request(method, split.path, query, self.headers,
                          body, self.client_address[0])

        surface = self.registry.resolve(method, split.path) \
            if self.registry else None
        if surface is None:
            not_found = (Response.json({"error": "not found"}, 404)
                         if split.path.startswith("/api")
                         else Response.text("not found", 404))
            self._write(not_found)
            return
        try:
            response = surface.handle(request)
        except RequestError as exc:
            response = Response.json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001 - surface bugs answer 500
            response = Response.json({"error":
                                      f"{type(exc).__name__}: {exc}"}, 500)
        self._write(response)

    def _write(self, response: Response):
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Cache-Control", "no-cache")
            if getattr(response, "streaming", False):
                self.send_header("Connection", "close")
                self.end_headers()
                for chunk in response.chunks:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                self.close_connection = True
            else:
                self.send_header("Content-Length", str(len(response.body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(response.body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    do_GET = _run
    do_POST = _run
    do_HEAD = _run


class MindHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def build_server(registry, host: str = "127.0.0.1",
                 port: int = 0) -> MindHTTPServer:
    """Bind an HTTP server speaking to this registry (port 0 = ephemeral).

    Caller starts it via serve_forever() in a thread (see director).
    """
    handler = type("BoundHandler", (_Handler,),
                   {"registry": registry})
    server = MindHTTPServer((host, port), handler)
    return server


def selftest(tmp_dir: str = None) -> int:
    import urllib.request
    import urllib.error

    failures = []

    def check(name, cond):
        if not cond:
            print(f"http.{name}: FAIL")
            failures.append(name)

    from .base import Surface, Registry

    echo = Surface()
    echo.name, echo.route, echo.methods = "echo", "/echo", ("POST",)
    echo.handle = lambda req: Response.json({
        "path": req.path, "q": req.query, "body": req.json()})

    boom = Surface()
    boom.name, boom.route, boom.methods = "boom", "/boom", ("GET",)
    boom.handle = lambda req: 1 / 0

    reg = Registry()
    reg.register(echo)
    reg.register(boom)

    server = build_server(reg, "127.0.0.1", 0)
    port = server.server_address[1]
    worker = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05},
                              daemon=True)
    worker.start()
    try:
        base = f"http://127.0.0.1:{port}"

        def fetch(path, data=None, method=None):
            req = urllib.request.Request(base + path, data=data,
                                         method=method)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, resp.read().decode()
            except urllib.error.HTTPError as err:
                return err.code, err.read().decode()

        check("registry-exact-match",
              reg.resolve("POST", "/echo") is echo
              and reg.resolve("GET", "/echo") is None
              and reg.resolve("POST", "/nope") is None)

        status, out = fetch("/echo?a=1",
                            data=b'{"hello": true}')
        import json as j
        parsed = j.loads(out)
        check("post-echo-roundtrip",
              status == 200 and parsed["body"] == {"hello": True}
              and parsed["q"] == {"a": "1"})

        status, _ = fetch("/missing")
        check("unknown-route-404", status == 404)
        status, _ = fetch("/api/missing")
        check("api-404-is-json", status == 404)

        status, out = fetch("/boom")
        check("crash-answers-500", status == 500)

        status, out = fetch("/echo", data=b"{bad json")
        check("bad-json-400", status == 400)
    finally:
        server.shutdown()
        server.server_close()
    print(f"surfaces.http selftest: "
          f"{'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
