"""PTAH server - local REST control plane (stdlib http.server).

Endpoints (all JSON; loopback by default):

  GET  /healthz                                  liveness + version
  GET  /readyz                                   backend readiness (503 if none)
  GET  /metrics                                  backend health/latency counters
  GET  /api/v1/conversations                     list conversations
  POST /api/v1/conversations      {workspace}    create conversation
  GET  /api/v1/conversations/{id}                metadata + status
  POST /api/v1/conversations/{id}/messages       {text, confirm?, wait?}
       wait=true  -> run synchronously, return final status
       wait=false -> run on a worker thread, poll via events
  GET  /api/v1/conversations/{id}/events?after=N incremental event feed

Every response includes ``X-Request-ID``; JSON responses also include
additive ``request_id`` for trace correlation.

Optional bearer auth: pass token=... (Authorization: Bearer <token>).
The kernel itself is the same object the CLI drives - one brain, two
fronts.
"""

import json
import math
import re
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ptah import content
from ptah.request_context import bind_request_context


MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_RUN_TIMEOUT = 600.0
MAX_ACTIVE_RUNS = 32
CONVERSATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _safe_request_id(raw):
    value = str(raw or "").strip()
    if REQUEST_ID.fullmatch(value):
        return value
    return ""


def _new_request_id():
    return f"ptah-{secrets.token_hex(12)}"


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _catalog_provider_name(provider):
    value = str(provider or "").strip()
    return "llama.cpp" if value == "llamacpp" else value


def _configured_local_models(backend_router=None):
    """List local model registrations suitable for VS Code-style clients."""
    from ptah.llm import LOCAL_PROVIDER_DEFAULTS, normalize_provider
    from ptah.llm_probe import _is_local_url, resolve_backend_targets

    rows = []
    seen = set()
    covered = set()

    def add(provider, model="", base_url="", configured=False):
        provider = normalize_provider(provider)
        if provider == "openai" and base_url and _is_local_url(base_url):
            provider = "openai-compatible"
        default_url, default_model = LOCAL_PROVIDER_DEFAULTS.get(
            provider, ("", ""))
        model = str(model or default_model or "").strip()
        base_url = str(base_url or default_url or "").strip()
        if not model or not base_url:
            return
        if provider == "anthropic":
            return
        if provider == "openai-compatible" and not configured:
            return
        if provider not in LOCAL_PROVIDER_DEFAULTS:
            return
        if not _is_local_url(base_url):
            return
        key = (provider, model, base_url)
        if key in seen:
            return
        seen.add(key)
        covered.add(provider)
        rows.append({
            "id": f"{_catalog_provider_name(provider)}/{model}",
            "provider": provider,
            "model": model,
            "base_url": base_url,
        })

    if backend_router is not None:
        for brain in getattr(backend_router, "backends", ()):
            cfg = getattr(brain, "config", None)
            if cfg is None:
                continue
            add(cfg.provider, cfg.model, cfg.base_url, configured=True)
    for target in resolve_backend_targets():
        add(target.provider, target.model, target.base_url, configured=True)
    for provider in ("ollama", "vllm", "lmstudio", "llamacpp", "litellm"):
        if provider not in covered:
            add(provider)
    return rows


def _selected_local_model(model, backend_router=None):
    wanted = str(model or "").strip()
    if not wanted or wanted == "ptah-agent":
        return None
    rows = _configured_local_models(backend_router)
    raw_counts = {}
    for item in rows:
        raw_counts[item["model"]] = raw_counts.get(item["model"], 0) + 1
        if wanted == item["id"]:
            return item
    if raw_counts.get(wanted) == 1:
        return next(item for item in rows if item["model"] == wanted)
    return None


def _remember_local_model(conversation, model, backend_router=None):
    selected = _selected_local_model(model, backend_router)
    changed = False
    if selected is None:
        for key in ("ptah_llm_provider", "ptah_llm_model",
                    "ptah_llm_base_url"):
            if key in conversation.meta:
                conversation.meta.pop(key, None)
                changed = True
    else:
        for key, value in (
                ("ptah_llm_provider", selected["provider"]),
                ("ptah_llm_model", selected["model"]),
                ("ptah_llm_base_url", selected["base_url"])):
            if conversation.meta.get(key) != value:
                conversation.meta[key] = value
                changed = True
    if changed:
        conversation._save_meta()
    return selected


def make_handler(store, runner, token=None, backend_router=None,
                 router=None, max_active_runs=None):
    """Build a request handler bound to a Store and a runner callback.

    runner(conversation, text, confirm) -> RunResult
    """

    backend_router = backend_router or router
    active_limit = (MAX_ACTIVE_RUNS
                    if max_active_runs is None else max_active_runs)
    handler_limit_explicit = max_active_runs is not None

    class Handler(BaseHTTPRequestHandler):
        server_version = f"ptah/{content.VERSION}"

        def log_message(self, fmt, *args):     # quiet by default
            pass

        # ------------------------------------------------------ helpers
        def _request_id(self):
            rid = getattr(self, "_cached_request_id", "")
            if rid:
                return rid
            headers = getattr(self, "headers", None)
            raw = headers.get("X-Request-ID") if headers is not None else ""
            rid = _safe_request_id(raw)
            self._cached_request_id = rid or _new_request_id()
            return self._cached_request_id

        def _json(self, payload, status=200, headers=None):
            rid = self._request_id()
            if isinstance(payload, dict) and "request_id" not in payload:
                payload = dict(payload)
                payload["request_id"] = rid
            blob = json.dumps(payload, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(blob)))
            self.send_header("X-Request-ID", rid)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(blob)

        def _sse(self, chunks, headers=None):
            rid = self._request_id()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.send_header("X-Request-ID", rid)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.close_connection = True
            for chunk in chunks:
                try:
                    self.wfile.write(b"data: " + json.dumps(
                        chunk, ensure_ascii=False,
                        separators=(",", ":")).encode("utf-8") + b"\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            try:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def _authed(self):
            if not token:
                return True
            header = self.headers.get("authorization", "")
            return secrets.compare_digest(header, f"Bearer {token}")

        def _unauthorized(self):
            return self._json({"error": "unauthorized"}, 401,
                              {"WWW-Authenticate": "Bearer"})

        def _body(self):
            try:
                length = int(self.headers.get("content-length", "0"))
                if length < 0 or length > MAX_REQUEST_BYTES:
                    raise ApiError(413, "request body is too large")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ApiError(400, "incomplete request body")
                data = json.loads(raw.decode("utf-8") or "{}")
            except ApiError:
                raise
            except TimeoutError:
                raise ApiError(408, "request body read timed out")
            except (ValueError, UnicodeError, json.JSONDecodeError):
                raise ApiError(400, "invalid JSON body")
            if not isinstance(data, dict):
                raise ApiError(400, "JSON body must be an object")
            return data

        def _conversation(self, cid):
            cid = urllib.parse.unquote(cid)
            if not CONVERSATION_ID.fullmatch(cid):
                raise ApiError(400, "invalid conversation id")
            conv = store.get(cid)
            if conv is None:
                raise ApiError(404, f"no such conversation: {cid}")
            return conv

        def _claim_run(self, conv):
            with self.server._active_lock:
                if conv.status == conv.RUNNING or conv.id in self.server._active:
                    raise ApiError(409, "conversation already running")
                server_limit = getattr(self.server, "max_active_runs", None)
                server_limit_explicit = bool(getattr(
                    self.server, "max_active_runs_explicit", False))
                if server_limit_explicit:
                    limit_value = server_limit
                elif handler_limit_explicit:
                    limit_value = active_limit
                elif server_limit is not None:
                    limit_value = server_limit
                else:
                    limit_value = active_limit
                limit = max(1, int(limit_value))
                if len(self.server._active) >= limit:
                    raise ApiError(503, "server overloaded")
                self.server._active.add(conv.id)

        def _release_run(self, conv):
            with self.server._active_lock:
                self.server._active.discard(conv.id)

        # ------------------------------------------------------- routes
        def _guard(self, fn):
            """Run a route handler; every failure becomes clean JSON."""
            try:
                fn()
            except ApiError as exc:
                self._json({"error": exc.message}, exc.status)
            except (BrokenPipeError, ConnectionResetError):
                pass                  # client vanished - nothing to say
            except Exception:  # noqa: BLE001 - never leak HTML
                try:
                    self._json({"error": "internal server error"}, 500)
                except Exception:
                    pass

        # ------------------------------------------------------- routes
        def do_GET(self):                      # noqa: N802 - stdlib API
            self._guard(self._route_get)

        def do_POST(self):                     # noqa: N802 - stdlib API
            self._guard(self._route_post)

        def _method_not_allowed(self):
            self._json({"error": "method not allowed"}, 405,
                       {"Allow": "GET, POST"})

        do_PUT = _method_not_allowed
        do_PATCH = _method_not_allowed
        do_DELETE = _method_not_allowed
        do_OPTIONS = _method_not_allowed
        do_HEAD = _method_not_allowed

        def send_error(self, code, message=None, explain=None):
            """Keep stdlib parser/method failures in the JSON API contract."""
            try:
                self._json({"error": message or "request rejected"}, code)
            except (BrokenPipeError, ConnectionResetError, OSError):
                self.close_connection = True

        def setup(self):                        # noqa: D401
            super().setup()
            # A client that never finishes its body must not pin a worker.
            self.connection.settimeout(30.0)

        def _route_get(self):
            parsed = urllib.parse.urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            if parsed.path == "/healthz":
                return self._json({"status": "ok",
                                   "version": content.VERSION})
            if parsed.path == "/readyz":
                if backend_router is None:
                    return self._json({"status": "ready", "ready": True,
                                       "version": content.VERSION})
                ready, snapshot = backend_router.readiness()
                payload = {"status": "ready" if ready else "not_ready",
                           "version": content.VERSION}
                payload.update(snapshot)
                return self._json(payload, 200 if ready else 503)
            if not self._authed():
                return self._unauthorized()
            if parsed.path in ("/metrics", "/api/v1/metrics",
                               "/api/v1/backends/metrics"):
                if backend_router is None:
                    return self._json({
                        "ready": True, "backends": [],
                        "total_calls": 0, "total_successes": 0,
                        "total_failures": 0})
                return self._json(backend_router.metrics())
            if parsed.path == "/api/v1/backends":
                if backend_router is None:
                    return self._json({"backends": []})
                return self._json({
                    "backends": backend_router.metrics()["backends"]})
            if parts[:2] == ["v1", "models"]:
                return self._json({
                    "object": "list",
                    "data": [{"id": "ptah-agent", "object": "model",
                              "owned_by": content.REALM}] + [
                                  {"id": item["id"], "object": "model",
                                   "owned_by": _catalog_provider_name(
                                       item["provider"])}
                                  for item in
                                  _configured_local_models(backend_router)]})
            if parts[:3] == ["api", "v1", "conversations"]:
                if len(parts) == 3:
                    return self._json({"conversations": store.list()})
                cid = parts[3]
                conv = self._conversation(cid)
                if len(parts) == 4:
                    return self._json(conv.meta)
                if len(parts) == 5 and parts[4] == "events":
                    q = urllib.parse.parse_qs(parsed.query)
                    try:
                        after = int((q.get("after") or ["0"])[0])
                    except (TypeError, ValueError):
                        raise ApiError(400, "after must be an integer")
                    if after < 0:
                        raise ApiError(400, "after must be non-negative")
                    chunk, total = conv.slice(after)
                    return self._json({
                        "status": conv.status,
                        "total": total,
                        "events": [e.to_dict() for e in chunk]})
            raise ApiError(404, "unknown route")

        def _route_post(self):
            parts = [p for p in
                     urllib.parse.urlparse(self.path).path.split("/")
                     if p]
            if not self._authed():
                return self._unauthorized()
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
                    timeout_s = self._timeout(body)
                    self._claim_run(conv)
                    result_holder = {}

                    def work():
                        with bind_request_context(
                                self._request_id(), route=self.path,
                                conversation_id=conv.id):
                            try:
                                result_holder["result"] = runner(
                                    conv, text, confirm)
                            except Exception as exc:  # noqa: BLE001
                                result_holder["error"] = exc
                            finally:
                                self._release_run(conv)

                    if wait:
                        worker = threading.Thread(target=work, daemon=True)
                        worker.start()
                        worker.join(timeout_s)
                        if worker.is_alive():
                            raise ApiError(504, "run timed out")
                        if "error" in result_holder:
                            conv.set_status(conv.ERROR)
                            raise ApiError(500, "agent run failed")
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
            if (len(parts) == 3 and
                    parts[:2] == ["v1", "chat"] and
                    parts[2] == "completions"):
                return self._openai_completion()
            raise ApiError(404, "unknown route")

        def _timeout(self, body):
            value = body.get("timeout_s", 180)
            if isinstance(value, bool):
                raise ApiError(400, "timeout_s must be a number")
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ApiError(400, "timeout_s must be a number")
            if not math.isfinite(value) or value < 0:
                raise ApiError(400, "timeout_s must be finite and non-negative")
            return min(value, MAX_RUN_TIMEOUT)

        def _openai_completion(self):
            """OpenAI-compatible single-shot gateway (non-streaming).

            Continuity: send the returned X-Ptah-Conversation-ID back as
            a request header to keep talking to the same conversation.
            """
            body = self._body()
            stream = body.get("stream", False)
            if not isinstance(stream, bool):
                raise ApiError(400, "stream must be a boolean")
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ApiError(400, "messages must be a non-empty array")
            model = body.get("model", "ptah-agent")
            if not isinstance(model, str) or not model.strip():
                raise ApiError(400, "model must be a non-empty string")
            user_text = ""
            for msg in reversed(messages):
                if not isinstance(msg, dict):
                    raise ApiError(400, "each message must be an object")
                if msg.get("role") not in {"system", "user", "assistant",
                                           "tool"}:
                    raise ApiError(400, "message role is invalid")
                if msg.get("role") == "user":
                    content_value = msg.get("content", "")
                    if isinstance(content_value, str):
                        user_text = content_value
                    elif isinstance(content_value, list):
                        user_text = "".join(
                            part.get("text", "")
                            for part in content_value
                            if isinstance(part, dict) and
                            isinstance(part.get("text", ""), str))
                    else:
                        raise ApiError(400, "message content must be text")
                    break
            if not user_text:
                raise ApiError(400, "messages must contain a user turn")
            cid = self.headers.get("X-Ptah-Conversation-ID")
            conv = store.get(cid) if cid else None
            if cid and conv is None:
                raise ApiError(404, f"no such conversation: {cid}")
            if conv is None:
                conv = store.create(workspace_root=".")
            _remember_local_model(conv, model, backend_router)
            self._claim_run(conv)
            result_holder = {}

            def work():
                with bind_request_context(
                        self._request_id(), route=self.path,
                        conversation_id=conv.id):
                    try:
                        result_holder["result"] = runner(conv, user_text, False)
                    except Exception as exc:  # noqa: BLE001
                        result_holder["error"] = exc
                    finally:
                        self._release_run(conv)

            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            worker.join(self._timeout(body))
            if worker.is_alive():
                raise ApiError(504, "agent run timed out")
            if "error" in result_holder:
                conv.set_status(conv.ERROR)
                raise ApiError(500, "agent run failed")

            from ptah import events as ev
            answer = ""
            for event in reversed(conv.events):
                if event.TYPE == "agent_message":
                    answer = event.text
                    break
                if event.TYPE == "confirmation_required":
                    answer = ("[waiting for human confirmation] "
                              + str(event.reason))
                    break
            payload = {
                "id": f"chatcmpl-ptah-{conv.id}",
                "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant",
                                         "content": answer}}],
            }
            if stream:
                created = int(time.time())
                chunks = [
                    {"id": payload["id"], "object": "chat.completion.chunk",
                     "created": created, "model": payload["model"],
                     "choices": [{"index": 0,
                                              "delta": {"role": "assistant"}}]},
                    {"id": payload["id"], "object": "chat.completion.chunk",
                     "created": created, "model": payload["model"],
                     "choices": [{"index": 0, "delta": {"content": answer},
                                              "finish_reason": None}]},
                    {"id": payload["id"], "object": "chat.completion.chunk",
                     "created": created, "model": payload["model"],
                     "choices": [{"index": 0, "delta": {},
                                              "finish_reason": "stop"}]},
                ]
                return self._sse(chunks,
                                             {"X-Ptah-Conversation-ID": conv.id})
            return self._json(payload, 200,
                                          {"X-Ptah-Conversation-ID": conv.id})

    return Handler


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, server_address, handler_cls, max_active_runs=None):
        super().__init__(server_address, handler_cls)
        self._active_lock = threading.RLock()
        self._active = set()
        self.max_active_runs_explicit = max_active_runs is not None
        value = MAX_ACTIVE_RUNS if max_active_runs is None else max_active_runs
        self.max_active_runs = max(1, int(value))


def serve(store, runner, host=None, port=None, token=None,
          backend_router=None, router=None, max_active_runs=None):
    """Blocking serve loop. Returns the server object after shutdown."""
    host = host or content.SERVER_HOST
    port = port if port is not None else content.SERVER_PORT
    handler = make_handler(store, runner, token=token,
                           backend_router=backend_router, router=router,
                           max_active_runs=max_active_runs)
    httpd = ApiServer((host, port), handler, max_active_runs=max_active_runs)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return httpd
