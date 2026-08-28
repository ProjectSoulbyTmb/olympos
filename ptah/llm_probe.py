"""ptah.llm_probe

Lightweight probe for local OpenAI-compatible backends.

Design goals:
- stdlib-only (urllib) and no network activity at import time
- explicit invocation only (the CLI calls into the probe functions)
- restrict probing to loopback/local endpoints for safety
- report reachability, model reported by the server, whether the server
  speaks SSE streaming for the chat/completions transport, whether tool/
  function_call style responses are present, and simple latency/throughput
  measurements for a small probe request.

Policy:
- This probe is intended for local OpenAI-compatible transports only.
- Allowed targets:
  * explicit --base-url (always accepted for OpenAI-compatible probes)
  * provider aliases configured in LLMConfig that map to local backends
    (ollama, vllm, lmstudio, llamacpp, litellm, openai-compatible)
  * provider 'openai' only when PTAH_BASE_URL or PTAH_LLM_ENDPOINT env var is
    explicitly set (or when --base-url is provided). We do NOT silently
    default to localhost:8000 for the 'openai' provider.
- Disallowed targets:
  * anthropic (different transport) and unknown providers are rejected before
    any network activity.

ProbeResult fields:
- models: optional list of model ids retrieved from GET /models, may be None
- models_error: optional error string describing non-fatal failure to fetch models
- can_stream/supports_tool_calls: tri-state Optional[bool] (True/False/None)
  where None means 'unknown'
- When a streaming POST is rejected (HTTP 400/404/405) a non-streaming fallback
  is attempted and reported via can_stream=False; stream-capable servers return
  can_stream=True.

The probe raises LLMProbeError on explicit failures (unreachable, malformed
responses, disallowed remote endpoints). Callers (CLI/tests) should catch and
render errors as needed.
"""


from dataclasses import dataclass
import json
import time
import urllib.request
import urllib.error
import socket
from typing import Optional, List, Iterable
from urllib.parse import urlparse
import ipaddress

USER_AGENT = "ptah-probe/1"


class LLMProbeError(Exception):
    """Probe failure with a machine-readable kind and human message."""

    def __init__(self, kind: str, message: str):
        super().__init__(f"[{kind}] {message}")
        self.kind = kind
        self.message = message


@dataclass
class ProbeResult:
    base_url: str
    endpoint: str
    model_requested: Optional[str]
    model_reported: Optional[str]
    reachable: bool
    # None = unknown, True = yes, False = no
    can_stream: Optional[bool]
    supports_tool_calls: Optional[bool]
    latency_s: float
    throughput_bytes_per_s: float
    response_size: int
    models: Optional[List[str]] = None
    models_error: Optional[str] = None


@dataclass
class BackendTarget:
    """A named backend configuration used by the benchmark.

    This is deliberately configuration-only.  Constructing targets never
    resolves hosts or opens a socket.
    """

    name: str
    provider: str
    model: str = ""
    base_url: str = ""
    api_key: Optional[str] = None


def _parse_backend_spec(spec):
    """Parse ``provider[=model][@base_url]`` without contacting anything."""
    if isinstance(spec, BackendTarget):
        return spec
    if isinstance(spec, dict):
        return BackendTarget(
            name=str(spec.get("name") or spec.get("provider") or "backend"),
            provider=str(spec.get("provider") or "openai"),
            model=str(spec.get("model") or ""),
            base_url=str(spec.get("base_url") or spec.get("endpoint") or ""),
            api_key=spec.get("api_key"))
    if isinstance(spec, (tuple, list)) and len(spec) >= 2:
        name, value = str(spec[0]), spec[1]
        if hasattr(value, "provider") and hasattr(value, "base_url"):
            return BackendTarget(name, getattr(value, "provider", name),
                                 getattr(value, "model", ""),
                                 getattr(value, "base_url", ""),
                                 getattr(value, "api_key", None))
        if hasattr(value, "config"):
            cfg = value.config
            return BackendTarget(name, getattr(cfg, "provider", name),
                                 getattr(cfg, "model", ""),
                                 getattr(cfg, "base_url", ""),
                                 getattr(cfg, "api_key", None))
        return BackendTarget(name, getattr(value, "provider", name),
                             getattr(value, "model", ""), getattr(value, "base_url", ""),
                             getattr(value, "api_key", None))
    text = str(spec or "").strip()
    if not text:
        return BackendTarget("backend", "openai")
    base_url = ""
    if "@" in text:
        text, base_url = text.split("@", 1)
    model = ""
    if "=" in text:
        provider, model = text.split("=", 1)
    else:
        provider = text
    return BackendTarget(provider.strip(), provider.strip(), model.strip(), base_url.strip())


def resolve_backend_targets(specs: Optional[Iterable] = None):
    """Resolve benchmark targets from explicit specs or PTAH environment.

    The primary provider and ``PTAH_LLM_FALLBACKS`` are included when no
    explicit specs are supplied.  Missing configuration remains a target with
    an empty URL so the report can say ``unavailable`` rather than silently
    dialing a default service.
    """
    import os
    from ptah.llm import (LLMConfig, LOCAL_ENV_TAGS, LOCAL_PROVIDER_DEFAULTS,
                          normalize_provider)

    if isinstance(specs, dict):
        explicit = []
        for name, value in specs.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("name", name)
            else:
                item = (name, value)
            explicit.append(item)
    else:
        explicit = list(specs or ())
    if explicit:
        raw_targets = [_parse_backend_spec(item) for item in explicit]
    else:
        cfg = LLMConfig.from_env()
        raw_targets = [BackendTarget("primary", cfg.provider, cfg.model,
                                     cfg.base_url, cfg.api_key or None)]
        fallback_specs = [item.strip() for item in
                          os.environ.get("PTAH_LLM_FALLBACKS", "").split(",")
                          if item.strip()]
        raw_targets.extend(_parse_backend_spec(item) for item in fallback_specs)
        # Include aliases that have explicit environment configuration even
        # when they are not the selected primary/fallback provider.
        configured_names = {target.provider for target in raw_targets}
        for alias_provider, tag in LOCAL_ENV_TAGS.items():
            if alias_provider in configured_names:
                continue
            alias_url = (os.environ.get(f"PTAH_{tag}_URL") or
                         os.environ.get(f"PTAH_{tag}_BASE_URL") or
                         os.environ.get(f"PTAH_{tag}_ENDPOINT") or "")
            alias_model = os.environ.get(f"PTAH_{tag}_MODEL") or ""
            alias_key = os.environ.get(f"PTAH_{tag}_API_KEY") or ""
            if alias_url or alias_model or alias_key:
                raw_targets.append(BackendTarget(
                    alias_provider, alias_provider, alias_model, alias_url,
                    alias_key or None))

    targets = []
    for index, target in enumerate(raw_targets):
        provider = normalize_provider(target.provider)
        default_url, default_model = LOCAL_PROVIDER_DEFAULTS.get(
            provider, ("", ""))
        tag = LOCAL_ENV_TAGS.get(provider)
        env = os.environ.get
        alias_url = alias_model = alias_key = ""
        if tag:
            alias_url = (env(f"PTAH_{tag}_URL") or
                         env(f"PTAH_{tag}_BASE_URL") or
                         env(f"PTAH_{tag}_ENDPOINT") or "")
            alias_model = env(f"PTAH_{tag}_MODEL") or ""
            alias_key = env(f"PTAH_{tag}_API_KEY") or ""
        canonical_url = env("PTAH_BASE_URL") or env("PTAH_LLM_ENDPOINT") or ""
        canonical_model = env("PTAH_LLM_MODEL") or ""
        base_url = target.base_url or canonical_url or alias_url or default_url
        model = target.model or canonical_model or alias_model or default_model
        name = target.name or provider or f"backend-{index + 1}"
        if any(item.name == name for item in targets):
            name = f"{name}-{index + 1}"
        targets.append(BackendTarget(name, provider, model, base_url,
                                     target.api_key or alias_key or
                                     (env("PTAH_API_KEY") or None)))
    return targets


def _is_local_url(url: str) -> bool:
    """Return True only for exact loopback hosts using http scheme.

    Avoids substring-based checks which can be bypassed by crafted hostnames
    (for example "127.0.0.1.evil.com"). Accepts literal "localhost" and
    IP addresses that are loopback (127.0.0.0/8, ::1). Historically some
    local setups use 0.0.0.0; include it for compatibility but do not accept
    arbitrary hostnames containing loopback substrings.
    """
    if not url:
        return False
    p = urlparse(url)
    # require explicit http scheme for probes (local dev servers usually use http)
    if p.scheme.lower() != "http":
        return False
    host = p.hostname
    if not host:
        return False
    # exact hostname check
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
        # true loopback addresses (127.0.0.0/8, ::1)
        if ip.is_loopback:
            return True
        # historically accepted binding address; keep for compatibility
        if str(ip) == "0.0.0.0":
            return True
    except Exception:
        # non-IP hostnames are rejected unless they are localhost
        return False
    return False


def _append_chat_path(base: str) -> str:
    base = (base or "").rstrip("/")
    path = "/chat/completions"
    if base.lower().endswith(path):
        return base
    return base + path


def _append_models_path(base: str) -> str:
    base = (base or "").rstrip("/")
    path = "/models"
    if base.lower().endswith(path):
        return base
    return base + path


def _parse_first_event_from_sse(text: str):
    """Return first JSON payload found in an SSE-like payload (data: ... lines).
    Returns a dict or None.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            data = line[len("data:"):].strip()
            # some servers prefix with a blank or send [DONE]
            if data == "[DONE]":
                continue
            try:
                return json.loads(data)
            except Exception:
                # ignore parse errors here; caller may attempt non-stream parse
                return None
    return None


def probe(base_url: str, model: Optional[str] = None,
          provider: str = "openai", api_key: Optional[str] = None,
          timeout_s: float = 5.0) -> ProbeResult:
    """Probe the provided local OpenAI-compatible base URL.

    - base_url should be a loopback/local URL (http://127.0.0.1:PORT/v1 or
      similar). The function will raise LLMProbeError if the URL looks remote
      or uses a non-http scheme.
    - model is optional; if provided it is sent in the request.
    - provider and api_key, if supplied, are used to follow common header
      conventions (e.g. Anthropic uses x-api-key).

    On success returns a ProbeResult. On failure raises LLMProbeError.
    """
    if not base_url:
        raise LLMProbeError("config", "no base_url provided")
    if not _is_local_url(base_url):
        raise LLMProbeError("remote_endpoint", "refusing to probe non-local endpoint")

    # Try to fetch model inventory via GET /models (non-fatal)
    models = None
    models_error = None
    headers_json = {
        "content-type": "application/json",
        "accept": "application/json",
        "user-agent": USER_AGENT,
    }
    # include auth header for model inventory if provided
    if api_key:
        if provider == "anthropic":
            headers_json["x-api-key"] = api_key
        else:
            headers_json["authorization"] = "Bearer " + api_key

    models_endpoint = _append_models_path(base_url)
    try:
        req_m = urllib.request.Request(models_endpoint, headers=headers_json, method="GET")
        with urllib.request.urlopen(req_m, timeout=timeout_s) as mresp:
            raw = mresp.read(65536)
            try:
                parsed = json.loads(raw.decode("utf-8", errors="replace") or "{}")
            except Exception as exc:
                models_error = f"invalid JSON: {exc}"
                parsed = None
            if parsed is not None:
                ids = []
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("data"), list):
                        for item in parsed.get("data"):
                            if isinstance(item, dict) and item.get("id"):
                                ids.append(item.get("id"))
                            elif isinstance(item, str):
                                ids.append(item)
                    elif isinstance(parsed.get("models"), list):
                        for item in parsed.get("models"):
                            if isinstance(item, dict) and item.get("id"):
                                ids.append(item.get("id"))
                            elif isinstance(item, str):
                                ids.append(item)
                elif isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and item.get("id"):
                            ids.append(item.get("id"))
                        elif isinstance(item, str):
                            ids.append(item)
                if ids:
                    models = ids
                else:
                    # no recognized model list present
                    models_error = models_error or "no models listed"
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read()[:400]
        except Exception:
            body = b""
        models_error = f"HTTP {exc.code}: {body!r}"
    except urllib.error.URLError as exc:
        models_error = f"network error: {exc}"
    except socket.timeout as exc:
        models_error = f"timeout: {exc}"
    except Exception as exc:
        models_error = f"error: {exc}"

    endpoint = _append_chat_path(base_url)
    model_req = model or "probe-model"
    headers_stream = {
        "content-type": "application/json",
        "accept": "text/event-stream",
        "user-agent": USER_AGENT,
    }
    if api_key:
        if provider == "anthropic":
            headers_stream["x-api-key"] = api_key
        else:
            headers_stream["authorization"] = "Bearer " + api_key

    # sample messages: tiny payload
    payload = {
        "model": model_req,
        "messages": [{"role": "system", "content": "ptah probe"}],
        "max_tokens": 2,
        "temperature": 0.0,
    }

    # Try streaming first (non-blocking attempt: we read a small initial chunk)
    data = json.dumps({**payload, "stream": True}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, headers=headers_stream, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            ct = (resp.getheader("content-type") or "").lower()
            # read an initial chunk (may be the full response for non-streaming
            # servers); keep it small to avoid blocking against a long-lived
            # stream.
            try:
                raw = resp.read(4096)
            except socket.timeout as exc:
                raise LLMProbeError("timeout", f"timed out while reading stream: {exc}")
            elapsed = time.perf_counter() - t0
            size = len(raw or b"")
            text = (raw.decode("utf-8", errors="replace") if raw else "")
            # detect SSE by content-type or presence of `data:`/`event:` markers
            sse_markers = ("text/event-stream" in ct or "data:" in text or "event:" in text)
            if sse_markers:
                # streaming supported; attempt to parse the first event
                first = _parse_first_event_from_sse(text)
                # if we didn't get a parseable event yet, read a bounded amount more
                if first is None:
                    try:
                        more = resp.read(65536)
                    except Exception:
                        more = b""
                    if more:
                        size += len(more)
                        text_more = text + more.decode("utf-8", errors="replace")
                        first = _parse_first_event_from_sse(text_more)
                # If still no parseable JSON completion event, treat as malformed
                if first is None:
                    raise LLMProbeError("malformed", "no parseable JSON completion event in SSE stream")
                # require choices for a valid completion event
                if not isinstance(first, dict) or not first.get("choices"):
                    raise LLMProbeError("malformed", "no choices in SSE JSON event")
                model_reported = first.get("model") if isinstance(first, dict) else None
                supports_tool_calls = None
                if isinstance(first, dict):
                    for choice in first.get("choices", []) or []:
                        # choice may contain `delta` with a `function_call` or `tool_calls`
                        delta = choice.get("delta") or {}
                        if delta.get("function_call") or delta.get("tool_calls"):
                            supports_tool_calls = True
                            break
                # throughput measured over the initial read period
                throughput = (size / max(elapsed, 1e-6)) if elapsed > 0 else 0.0
                return ProbeResult(base_url=base_url, endpoint=endpoint,
                                   model_requested=model_req, model_reported=model_reported,
                                   reachable=True, can_stream=True,
                                   supports_tool_calls=supports_tool_calls,
                                   latency_s=round(elapsed, 3),
                                   throughput_bytes_per_s=round(throughput, 1),
                                   response_size=size, models=models,
                                   models_error=models_error)
            # Otherwise, server likely returned JSON even to a streaming request.
            # Fall through to a non-streaming parse: combine the chunk we read
            # with a bounded remainder and parse as JSON.
            rest = b""
            try:
                rest = resp.read(65536)
            except Exception:
                rest = b""
            full = (raw or b"") + (rest or b"")
            elapsed = time.perf_counter() - t0
            size = len(full)
            try:
                parsed = json.loads(full.decode("utf-8", errors="replace") or "{}")
            except Exception as exc:
                raise LLMProbeError("malformed", f"invalid JSON response: {exc}")
            # require a choices list for a valid chat/completions response
            if not isinstance(parsed, dict) or not parsed.get("choices"):
                raise LLMProbeError("malformed", "no choices in response")
            model_reported = parsed.get("model")
            supports_tool_calls = None
            # inspect choices for function_call / tool_calls evidence
            choices = parsed.get("choices") or []
            if choices:
                first_choice = choices[0]
                message = first_choice.get("message") or {}
                if message.get("function_call") or first_choice.get("tool_calls") or message.get("tool_calls"):
                    supports_tool_calls = True
            throughput = (size / max(elapsed, 1e-6)) if elapsed > 0 else 0.0
            return ProbeResult(base_url=base_url, endpoint=endpoint,
                               model_requested=model_req, model_reported=model_reported,
                               reachable=True, can_stream=False,
                               supports_tool_calls=supports_tool_calls,
                               latency_s=round(elapsed, 3),
                               throughput_bytes_per_s=round(throughput, 1),
                               response_size=size, models=models,
                               models_error=models_error)
    except urllib.error.HTTPError as exc:
        # If the server explicitly rejects a streaming request with a
        # 4xx that indicates streaming isn't supported, attempt a fallback
        # non-streaming request instead of failing reachability.
        try:
            code = exc.code
        except Exception:
            code = None
        if code in (400, 404, 405):
            # fallback to non-streaming POST
            data_ns = json.dumps({**payload, "stream": False}).encode("utf-8")
            req_ns = urllib.request.Request(endpoint, data=data_ns, headers=headers_json, method="POST")
            t0_ns = time.perf_counter()
            try:
                with urllib.request.urlopen(req_ns, timeout=timeout_s) as resp2:
                    # bounded reads and JSON parse as in the non-stream branch
                    try:
                        raw2 = resp2.read(4096)
                    except socket.timeout as exc2:
                        raise LLMProbeError("timeout", f"timed out while reading fallback response: {exc2}")
                    rest2 = b""
                    try:
                        rest2 = resp2.read(65536)
                    except Exception:
                        rest2 = b""
                    full2 = (raw2 or b"") + (rest2 or b"")
                    elapsed2 = time.perf_counter() - t0_ns
                    size2 = len(full2)
                    try:
                        parsed2 = json.loads(full2.decode("utf-8", errors="replace") or "{}")
                    except Exception as exc2:
                        raise LLMProbeError("malformed", f"invalid JSON response from fallback: {exc2}")
                    if not isinstance(parsed2, dict) or not parsed2.get("choices"):
                        raise LLMProbeError("malformed", "no choices in fallback response")
                    model_reported2 = parsed2.get("model")
                    supports_tool_calls2 = None
                    choices2 = parsed2.get("choices") or []
                    if choices2:
                        first_choice = choices2[0]
                        message = first_choice.get("message") or {}
                        if message.get("function_call") or first_choice.get("tool_calls") or message.get("tool_calls"):
                            supports_tool_calls2 = True
                    throughput2 = (size2 / max(elapsed2, 1e-6)) if elapsed2 > 0 else 0.0
                    return ProbeResult(base_url=base_url, endpoint=endpoint,
                                       model_requested=model_req, model_reported=model_reported2,
                                       reachable=True, can_stream=False,
                                       supports_tool_calls=supports_tool_calls2,
                                       latency_s=round(elapsed2, 3),
                                       throughput_bytes_per_s=round(throughput2, 1),
                                       response_size=size2, models=models,
                                       models_error=models_error)
            except urllib.error.HTTPError as exc2:
                body = b""
                try:
                    body = exc2.read()[:400]
                except Exception:
                    body = b""
                raise LLMProbeError("http", f"HTTP {exc2.code}: {body!r}")
            except urllib.error.URLError as exc2:
                raise LLMProbeError("network", f"network error in fallback: {exc2}")
            except socket.timeout as exc2:
                raise LLMProbeError("timeout", f"timed out in fallback: {exc2}")
        # otherwise, surface the HTTP error as a probe failure
        body = b""
        try:
            body = exc.read()[:400]
        except Exception:
            body = b""
        raise LLMProbeError("http", f"HTTP {exc.code}: {body!r}")
    except urllib.error.URLError as exc:
        raise LLMProbeError("network", f"network error: {exc}")
    except socket.timeout as exc:
        raise LLMProbeError("timeout", f"timed out: {exc}")


# ---- repeatable benchmark/report --------------------------------


def _capability_value(values):
    observed = [value for value in values if value is not None]
    if not observed:
        return None
    if all(value is True for value in observed):
        return True
    if all(value is False for value in observed):
        return False
    return None


_UNAVAILABLE_ERROR_KINDS = frozenset(
    ("config", "remote_endpoint", "network", "timeout"))


def benchmark_backends(backends=None, runs=1, timeout_s=5.0):
    """Run a small compatibility benchmark for every configured backend.

    Each backend is probed independently and failures are captured in its
    row.  Thus an offline alias cannot hide the results of a reachable local
    server.  Network activity happens only while this function is called.
    """
    try:
        count = int(runs)
    except (TypeError, ValueError):
        raise ValueError("runs must be a positive integer")
    if count < 1:
        raise ValueError("runs must be a positive integer")
    targets = resolve_backend_targets(backends)
    rows = []
    for target in targets:
        measurements = []
        errors = []
        for _ in range(count):
            try:
                result = probe(target.base_url, model=target.model,
                               provider=target.provider, api_key=target.api_key,
                               timeout_s=timeout_s)
                measurements.append(result)
            except LLMProbeError as exc:
                errors.append({"kind": exc.kind, "message": exc.message})
            except Exception as exc:  # noqa: BLE001 - report per backend
                errors.append({"kind": "error", "message": str(exc)[:300]})
        latencies = [item.latency_s for item in measurements]
        throughputs = [item.throughput_bytes_per_s for item in measurements]
        if measurements:
            latest = measurements[-1]
            status = "available" if not errors else "partial"
            row = {
                "name": target.name,
                "provider": target.provider,
                "model": target.model,
                "base_url": target.base_url,
                "endpoint": latest.endpoint,
                "status": status,
                "reachable": True,
                "runs_requested": count,
                "runs_succeeded": len(measurements),
                "runs_failed": len(errors),
                "latency_s": {
                    "min": round(min(latencies), 6),
                    "avg": round(sum(latencies) / len(latencies), 6),
                    "max": round(max(latencies), 6),
                },
                "throughput_bytes_per_s": {
                    "min": round(min(throughputs), 3),
                    "avg": round(sum(throughputs) / len(throughputs), 3),
                    "max": round(max(throughputs), 3),
                },
                "response_size": latest.response_size,
                "can_stream": _capability_value(
                    [item.can_stream for item in measurements]),
                "supports_tool_calls": _capability_value(
                    [item.supports_tool_calls for item in measurements]),
                "models": latest.models,
                "models_error": latest.models_error,
                "errors": errors,
            }
        else:
            error = errors[-1] if errors else {
                "kind": "config", "message": "no probe attempts made"}
            # A local endpoint that cannot be contacted is unavailable, not a
            # backend response error.  Reserve ``error`` for servers that
            # answered but returned malformed/rejected responses.
            unavailable = error["kind"] in _UNAVAILABLE_ERROR_KINDS
            row = {
                "name": target.name,
                "provider": target.provider,
                "model": target.model,
                "base_url": target.base_url,
                "endpoint": _append_chat_path(target.base_url)
                if target.base_url else "",
                "status": "unavailable" if unavailable else "error",
                "reachable": not unavailable,
                "runs_requested": count,
                "runs_succeeded": 0,
                "runs_failed": len(errors) or count,
                "latency_s": None,
                "throughput_bytes_per_s": None,
                "response_size": 0,
                "can_stream": None,
                "supports_tool_calls": None,
                "models": None,
                "models_error": None,
                "errors": errors or [error],
            }
        rows.append(row)
    available = sum(row["status"] in ("available", "partial")
                    for row in rows)
    return {
        "schema": "ptah-backend-benchmark-v1",
        "runs": count,
        "timeout_s": float(timeout_s),
        "backends": rows,
        "summary": {
            "configured": len(rows),
            "available": available,
            "unavailable": sum(row["status"] == "unavailable" for row in rows),
            "errors": sum(
                any(item.get("kind") not in _UNAVAILABLE_ERROR_KINDS
                    for item in row["errors"])
                for row in rows),
        },
    }


# Friendly names used by integrations and operators.
benchmark = benchmark_backends
compatibility_report = benchmark_backends


# ---- CLI helper -------------------------------------------------





def probe_from_env_or_args(base_url: Optional[str] = None, model: Optional[str] = None, timeout_s: float = 5.0) -> ProbeResult:
    """Resolve a sensible local base_url from explicit arg or environment.

    Policy and semantics:
    - Use the project's LLMConfig.from_env() conventions to determine provider,
      base_url and api_key where available.
    - Allowed to probe only OpenAI-compatible local transports:
      * An explicit --base-url always wins (keeps compatibility with callers).
      * Provider aliases (ollama, vllm, lmstudio, llamacpp, litellm,
        openai-compatible) as configured in LLMConfig are allowed and may
        supply a loopback default.
      * Provider 'openai' is only allowed when PTAH_BASE_URL or
        PTAH_LLM_ENDPOINT is explicitly set in the environment (or when an
        explicit --base-url is passed). We DO NOT silently default to
        localhost:8000 for the 'openai' provider.
    - Reject anthropic and unknown providers before performing any network
      activity.

    The function does not perform network I/O itself; it validates local
    configuration and then delegates to :func:`probe` which performs the
    actual network probe.
    """
    import os
    try:
        from ptah.llm import LLMConfig, LOCAL_PROVIDER_DEFAULTS
        cfg = LLMConfig.from_env()
    except Exception:
        cfg = None

    # Explicit base_url argument always takes precedence.
    if base_url:
        # If the configured provider is anthropic, do not probe it even when
        # an explicit base URL is provided; this probe only supports
        # OpenAI-compatible transports.
        provider = cfg.provider if cfg is not None else "openai"
        # Allow only 'openai' or known local provider aliases when an explicit
        # base_url is provided. Reject anthropic and unknown providers early
        # before any network interaction.
        if provider == "anthropic":
            raise LLMProbeError("config", "provider 'anthropic' is not probeable by this tool")
        if provider not in ("openai",) and provider not in LOCAL_PROVIDER_DEFAULTS:
            raise LLMProbeError("config", f"unknown or unsupported provider {provider!r}")
        model_choice = model or (cfg.model if cfg is not None else None)
        api_key = cfg.api_key if cfg is not None else os.environ.get('PTAH_API_KEY') or os.environ.get('OPENAI_API_KEY') or None
        return probe(base_url, model=model_choice, provider=provider, api_key=api_key, timeout_s=timeout_s)

    # No explicit base_url: require a configured local backend.
    if cfg is None:
        # If we can't import LLMConfig, fall back to environment checks only.
        candidate = os.environ.get('PTAH_BASE_URL') or os.environ.get('PTAH_LLM_ENDPOINT') or ""
        if not candidate:
            raise LLMProbeError("config", "no local backend configured; set PTAH_BASE_URL/PTAH_LLM_ENDPOINT or pass --base-url")
        api_key = os.environ.get('PTAH_API_KEY') or os.environ.get('OPENAI_API_KEY') or None
        model_choice = model or None
        return probe(candidate, model=model_choice, provider="openai", api_key=api_key, timeout_s=timeout_s)

    provider = cfg.provider
    api_key = cfg.api_key or None
    model_choice = model or (cfg.model if cfg.model else None)

    # Reject anthropic and unknown providers early.
    if provider == "anthropic":
        raise LLMProbeError("config", "provider 'anthropic' is not probeable by this tool")
    if provider not in ("openai",) and provider not in LOCAL_PROVIDER_DEFAULTS:
        raise LLMProbeError("config", f"unknown or unsupported provider {provider!r}")

    # Local provider aliases (ollama/vllm/lmstudio/llamacpp/litellm/openai-compatible)
    # may supply a loopback default via LOCAL_PROVIDER_DEFAULTS and are
    # acceptable when configured as the provider.
    if provider in LOCAL_PROVIDER_DEFAULTS:
        candidate = cfg.base_url or LOCAL_PROVIDER_DEFAULTS.get(provider, ("", ""))[0]
        if not candidate:
            raise LLMProbeError("config", f"no base_url configured for provider {provider!r}")
        return probe(candidate, model=model_choice, provider=provider, api_key=api_key, timeout_s=timeout_s)

    # At this point provider == "openai". Only allow probing if the base URL
    # was explicitly set in the environment (PTAH_BASE_URL or PTAH_LLM_ENDPOINT)
    # or the caller passed --base-url. Do not accept the implicit localhost
    # default for 'openai'.
    if provider == "openai":
        if os.environ.get('PTAH_BASE_URL') or os.environ.get('PTAH_LLM_ENDPOINT'):
            candidate = cfg.base_url
            if not candidate:
                raise LLMProbeError("config", "PTAH_BASE_URL/PTAH_LLM_ENDPOINT set but empty")
            return probe(candidate, model=model_choice, provider=provider, api_key=api_key, timeout_s=timeout_s)
        else:
            raise LLMProbeError("config", "no local backend configured for provider 'openai'; set PTAH_BASE_URL/PTAH_LLM_ENDPOINT or pass --base-url")


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(prog="ptah.llm_probe",
                                 description="Probe a local OpenAI-compatible backend")

    ap.add_argument('--base-url', help='explicit base URL to probe')
    ap.add_argument('--model', help='model to request', default=None)
    ap.add_argument('--timeout', type=float, default=5.0, help='probe timeout seconds')
    ap.add_argument('--json', action='store_true', help='print JSON summary')

    args = ap.parse_args()
    try:
        res = probe_from_env_or_args(args.base_url, args.model, timeout_s=args.timeout)
    except LLMProbeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    if args.json:
        from dataclasses import asdict
        out = asdict(res)
        print(json.dumps(out))
        sys.exit(0)
    # human readable output
    print(f"base_url: {res.base_url}")
    print(f"endpoint: {res.endpoint}")
    print(f"reachable: {res.reachable}")
    if res.model_reported:
        print(f"model_reported: {res.model_reported}")
    sys.exit(0)
