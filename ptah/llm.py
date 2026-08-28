"""PTAH LLM access with one OpenAI-compatible local transport.

``openai`` and the local aliases (Ollama, vLLM, LM Studio, llama.cpp and
LiteLLM) all use ``POST {base_url}/chat/completions`` and return the same
``Reply`` shape.  ``anthropic`` retains its native Messages transport and
``scripted`` is the deterministic offline adapter.  ``Reply`` also carries
provider-neutral tool calls, and ``stream`` normalizes OpenAI SSE and
Anthropic event streams into incremental replies.

Configuration is env-only and never probes a server at boot.  Local
aliases supply sensible loopback defaults and do not require an API key;
explicit endpoint/model values always win over alias values.

``base_url`` is the server base (for example ``http://127.0.0.1:8000/v1``);
the transport appends its provider path.  A URL that already ends in the
provider path is also accepted, so ``.../v1/chat/completions`` is not doubled.
"""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ptah import content
from ptah.request_context import get_request_id


LOCAL_PROVIDER_ALIASES = {
    "ollama": "ollama",
    "vllm": "vllm",
    "lmstudio": "lmstudio",
    "lm-studio": "lmstudio",
    "lm_studio": "lmstudio",
    "lm studio": "lmstudio",
    "llama.cpp": "llamacpp",
    "llama-cpp": "llamacpp",
    "llama_cpp": "llamacpp",
    "llama cpp": "llamacpp",
    "llamacpp": "llamacpp",
    "litellm": "litellm",
    "openai-compatible": "openai-compatible",
    "openai_compatible": "openai-compatible",
    "local": "openai-compatible",
    "local-openai": "openai-compatible",
}

LOCAL_PROVIDER_DEFAULTS = {
    "ollama": ("http://127.0.0.1:11434/v1", "llama3.2"),
    "vllm": ("http://127.0.0.1:8000/v1", "local-model"),
    "lmstudio": ("http://127.0.0.1:1234/v1", "local-model"),
    "llamacpp": ("http://127.0.0.1:8080/v1", "local-model"),
    "litellm": ("http://127.0.0.1:4000/v1", "local-model"),
    "openai-compatible": ("http://127.0.0.1:8000/v1", "local-model"),
}

LOCAL_ENV_TAGS = {
    "ollama": "OLLAMA",
    "vllm": "VLLM",
    "lmstudio": "LMSTUDIO",
    "llamacpp": "LLAMA_CPP",
    "litellm": "LITELLM",
    "openai-compatible": "OPENAI_COMPATIBLE",
}


def normalize_provider(provider):
    """Return the stable provider name used for transport selection."""
    value = (provider or "openai").strip().lower()
    return LOCAL_PROVIDER_ALIASES.get(value, value)


class LLMError(Exception):
    """Classified LLM failure."""

    def __init__(self, kind, message, status=None):
        super().__init__(f"[{kind}] {message}")
        self.kind = kind
        self.status = status


RETRYABLE_STATUSES = {429, 500, 502, 503, 504, 529}


@dataclass
class LLMConfig:
    provider: str = "openai"            # openai | anthropic | scripted | local
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout_s: float = content.HTTP_TIMEOUT_S
    max_retries: int = content.HTTP_MAX_RETRIES
    backoff_base_s: float = content.HTTP_BACKOFF_BASE_S

    @classmethod
    def from_env(cls, prefix="PTAH"):
        """Build config without network access.

        Precedence is canonical key > selected backend alias key > default.
        The historical LM Studio keys remain aliases when the provider is
        left at its default ``openai`` value.
        """
        env = os.environ.get
        provider = normalize_provider(env(f"{prefix}_LLM_PROVIDER"))
        tag = LOCAL_ENV_TAGS.get(provider)
        alias_url = alias_model = alias_key = ""
        if tag:
            alias_url = (env(f"{prefix}_{tag}_URL")
                         or env(f"{prefix}_{tag}_BASE_URL")
                         or env(f"{prefix}_{tag}_ENDPOINT")
                         or env(f"{tag}_URL")
                         or env(f"{tag}_BASE_URL")
                         or env(f"{tag}_ENDPOINT") or "")
            alias_model = (env(f"{prefix}_{tag}_MODEL")
                           or env(f"{tag}_MODEL") or "")
            alias_key = (env(f"{prefix}_{tag}_API_KEY")
                         or env(f"{tag}_API_KEY") or "")
        # Keep the original LM Studio seam working for default openai users.
        if provider == "openai":
            alias_url = (alias_url or env(f"{prefix}_LMSTUDIO_URL")
                         or env(f"{prefix}_LMSTUDIO_ENDPOINT") or "")
            alias_model = alias_model or env(f"{prefix}_LMSTUDIO_MODEL") or ""
            alias_key = alias_key or env(f"{prefix}_LMSTUDIO_API_KEY") or ""
        default_url, default_model = LOCAL_PROVIDER_DEFAULTS.get(
            provider, ("", ""))
        if provider == "openai":
            default_model = "gpt-4o-mini"
        elif provider == "anthropic":
            default_model = "claude-sonnet-4-5"
        default_key = (env("ANTHROPIC_API_KEY") if provider == "anthropic"
                       else env("OPENAI_API_KEY")) or ""
        key = env(f"{prefix}_API_KEY") or alias_key or default_key
        base_url = (env(f"{prefix}_BASE_URL")
                    or env(f"{prefix}_LLM_ENDPOINT")
                    or alias_url or default_url)
        model = env(f"{prefix}_LLM_MODEL") or alias_model or default_model
        return cls(provider=provider, model=model, api_key=key,
                   base_url=base_url)


@dataclass
class Reply:
    text: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0
    tool_calls: list = field(default_factory=list)
    finish_reason: str = ""


# ------------------------------------------------------------- scripted
class ScriptedLLM:
    """Deterministic offline brain: pops one reply per call."""

    provider = "scripted"
    transport = "scripted"

    def __init__(self, replies, model="scripted"):
        self._replies = list(replies)
        self.model = model
        self.calls = []

    def complete(self, system, messages, tools=None, tool_choice=None):
        t0 = time.perf_counter()
        call = {"system": system, "messages": list(messages)}
        request_id = get_request_id()
        if request_id:
            call["request_id"] = request_id
        if tools is not None:
            call["tools"] = tools
        if tool_choice is not None:
            call["tool_choice"] = tool_choice
        self.calls.append(call)
        if not self._replies:
            raise LLMError("bad_response", "scripted brain exhausted")
        item = self._replies.pop(0)
        if isinstance(item, Reply):
            reply = item
            reply.model = reply.model or self.model
            reply.usage = _normalized_usage(reply.usage)
        else:
            reply = Reply(text=str(item), model=self.model,
                          usage={"input": 0, "output": 0})
        reply.latency_s = round(time.perf_counter() - t0, 3)
        return reply

    def stream(self, system, messages, tools=None, tool_choice=None):
        """Yield incremental :class:`Reply` objects from a provider stream.

        ``text`` is the new text for that event (not the accumulated text).
        Tool calls are emitted once, in their normalized final form, after
        all argument fragments have arrived.  The final event may therefore
        contain only usage/tool-call metadata.
        """
        # Scripted replies are intentionally atomic but expose the same API.
        reply = self.complete(system, messages, tools=tools,
                              tool_choice=tool_choice)
        yield reply

    # keep parity with LLM API used by callers/tests
    @property
    def config(self):
        return LLMConfig(provider="scripted", model=self.model)


# ----------------------------------------------------------------- real
class LLM:
    def __init__(self, config=None):
        self.config = config or LLMConfig()
        self.config.provider = normalize_provider(self.config.provider)
        if self.config.provider not in ("openai", "anthropic") and \
                self.config.provider not in LOCAL_PROVIDER_DEFAULTS:
            raise LLMError("config",
                           f"unknown provider {self.config.provider!r}")

    @property
    def provider(self):
        """Configured name; local aliases still share the OpenAI transport."""
        return self.config.provider

    @property
    def transport(self):
        return "anthropic" if self.config.provider == "anthropic" \
            else "openai-compatible"

    # ---- public ----
    def complete(self, system, messages, tools=None, tool_choice=None):
        t0 = time.perf_counter()
        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                reply = self._once(system, messages, tools=tools,
                                   tool_choice=tool_choice)
                reply.latency_s = round(time.perf_counter() - t0, 3)
                return reply
            except _Transient as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                delay = min(8.0, self.config.backoff_base_s * (2 ** attempt))
                if exc.retry_after:
                    delay = max(delay, exc.retry_after)
                time.sleep(delay)
        raise LLMError(last_error.kind, f"gave up after retries: "
                       f"{last_error}", status=last_error.status)

    def stream(self, system, messages, tools=None, tool_choice=None):
        """Stream normalized provider events as incremental ``Reply`` values."""
        t0 = time.perf_counter()
        emitted = False
        for attempt in range(self.config.max_retries + 1):
            try:
                req = urllib.request.Request(
                    self._endpoint(),
                    data=self._payload(system, messages, stream=True,
                                       tools=tools, tool_choice=tool_choice),
                    headers=dict(self._headers(),
                                 **{"accept": "text/event-stream"}),
                    method="POST")
                with urllib.request.urlopen(
                        req, timeout=self.config.timeout_s) as resp:
                    for reply in self._parse_stream(resp):
                        emitted = True
                        reply.latency_s = round(time.perf_counter() - t0, 3)
                        yield reply
                return
            except _Transient as exc:
                if emitted or attempt >= self.config.max_retries:
                    raise LLMError(exc.kind, f"gave up after retries: "
                                   f"{exc}", status=exc.status) from None
                delay = min(8.0, self.config.backoff_base_s * (2 ** attempt))
                if exc.retry_after:
                    delay = max(delay, exc.retry_after)
                time.sleep(delay)
            except LLMError as exc:
                if exc.kind == "bad_response" and not emitted:
                    if attempt >= self.config.max_retries:
                        raise LLMError(
                            "bad_response", f"gave up after retries: {exc}",
                            status=exc.status) from None
                    delay = min(8.0, self.config.backoff_base_s * (2 ** attempt))
                    time.sleep(delay)
                    continue
                raise
            except (urllib.error.HTTPError, urllib.error.URLError,
                    TimeoutError, ConnectionError, OSError) as exc:
                transient = self._classify_http_error(exc)
                if not isinstance(transient, _Transient):
                    raise transient
                if emitted or attempt >= self.config.max_retries:
                    raise LLMError(transient.kind, f"gave up after retries: "
                                   f"{transient}", status=transient.status)
                time.sleep(min(8.0, self.config.backoff_base_s * (2 ** attempt)))

    # ---- internals ----
    def _endpoint(self):
        if self.config.provider == "anthropic":
            base = self.config.base_url or "https://api.anthropic.com/v1"
            return _append_path(base, "/messages")
        default = LOCAL_PROVIDER_DEFAULTS.get(self.config.provider, ("", ""))[0]
        base = self.config.base_url or default or "https://api.openai.com/v1"
        return _append_path(base, "/chat/completions")

    def _is_local(self):
        base = (self.config.base_url or "").lower()
        if not base and self.config.provider in LOCAL_PROVIDER_DEFAULTS:
            return True
        return any(host in base for host in (
            "://localhost", "://127.0.0.1", "://[::1]", "://0.0.0.0"))

    def _headers(self):
        request_id = get_request_id()
        if self.config.provider == "anthropic":
            headers = {
                "content-type": "application/json",
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "user-agent": content.USER_AGENT,
            }
            if request_id:
                headers["x-request-id"] = request_id
            return headers
        if not self.config.api_key and not self._is_local():
            raise LLMError("auth", "missing API key (set PTAH_API_KEY)")
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.config.api_key}",
            "user-agent": content.USER_AGENT,
        }
        if self.config.api_key:
            headers["authorization"] = "Bearer " + self.config.api_key
        else:
            headers.pop("authorization", None)
        if request_id:
            headers["x-request-id"] = request_id
        return headers

    def _payload(self, system, messages, stream=False, tools=None,
                 tool_choice=None):
        def message_payload(message):
            # Preserve OpenAI tool-call fields while retaining the historical
            # role/content-only message contract.
            return {key: message[key] for key in (
                "role", "content", "name", "tool_call_id", "tool_calls",
                "function_call")
                    if key in message}

        if self.config.provider == "anthropic":
            payload = {
                "model": self.config.model,
                "system": system,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "messages": [message_payload(m) for m in messages],
            }
            if stream:
                payload["stream"] = True
            if tools is not None:
                payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
            return json.dumps(payload).encode("utf-8")
        chat = [{"role": "system", "content": system}]
        chat += [message_payload(m) for m in messages]
        payload = {
            "model": self.config.model,
            "messages": chat,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if stream:
            payload["stream"] = True
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return json.dumps(payload).encode("utf-8")

    def _parse(self, raw):
        data = json.loads(raw.decode("utf-8"))
        if self.config.provider == "anthropic":
            blocks = data.get("content") or []
            text = "".join(block.get("text", "") for block in blocks
                           if block.get("type") == "text")
            tool_calls = _anthropic_tool_calls(blocks)
            usage = data.get("usage") or {}
            usage_in = usage.get("input_tokens", 0)
            usage_out = usage.get("output_tokens", 0)
        else:
            choices = data.get("choices") or []
            if not choices:
                raise LLMError("bad_response", "no choices in response")
            message = choices[0].get("message", {})
            text = _text_content(message.get("content", ""))
            tool_calls = _openai_tool_calls(
                message.get("tool_calls"), message.get("function_call"))
            usage = data.get("usage") or {}
            usage_in = usage.get("prompt_tokens", usage.get(
                "input_tokens", usage.get("prompt_eval_count", 0)))
            usage_out = usage.get("completion_tokens", usage.get(
                "output_tokens", usage.get("eval_count", 0)))
        return Reply(text=text or "", model=data.get("model", "")
                     or self.config.model,
                     usage=_normalized_usage(
                         {"input": usage_in, "output": usage_out}),
                     tool_calls=tool_calls,
                     finish_reason=(choices[0].get("finish_reason", "")
                                    if self.config.provider != "anthropic"
                                    else data.get("stop_reason", "")) or "")

    def _once(self, system, messages, tools=None, tool_choice=None):
        req = urllib.request.Request(
            self._endpoint(),
            data=self._payload(system, messages, tools=tools,
                               tool_choice=tool_choice),
            headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_s) \
                    as resp:
                return self._parse(resp.read())
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()[:400]
            except OSError:
                pass
            classified = self._classify_http_error(exc, body)
            if isinstance(classified, _Transient):
                raise classified
            raise classified
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                OSError) as exc:
            raise _Transient("network", str(exc))

    def _classify_http_error(self, exc, body=None):
        if isinstance(exc, urllib.error.HTTPError):
            if body is None:
                try:
                    body = exc.read()[:400]
                except OSError:
                    body = b""
            kind = ("rate_limit" if exc.code == 429 else
                    "auth" if exc.code in (401, 403) else
                    "server" if exc.code >= 500 else "bad_request")
            retry_after = None
            try:
                retry_after = float(exc.headers.get("Retry-After") or 0) \
                    or None
            except (TypeError, ValueError):
                pass
            message = f"HTTP {exc.code}: {body!r}"
            if exc.code in RETRYABLE_STATUSES:
                return _Transient(kind, message, status=exc.code,
                                  retry_after=retry_after)
            return LLMError(kind, message, status=exc.code)
        return _Transient("network", str(exc))

    def _parse_stream(self, response):
        if self.config.provider == "anthropic":
            return _parse_anthropic_stream(response, self.config.model)
        return _parse_openai_stream(response, self.config.model)


class _Transient(Exception):
    def __init__(self, kind, message, status=None, retry_after=None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


def _normalized_usage(usage):
    """Normalize provider-specific token names to the Reply contract."""
    usage = usage or {}
    input_tokens = usage.get("input", usage.get(
        "prompt_tokens", usage.get("input_tokens", 0)))
    output_tokens = usage.get("output", usage.get(
        "completion_tokens", usage.get("output_tokens", 0)))
    return {"input": input_tokens or 0, "output": output_tokens or 0}


def _parse_arguments(arguments):
    """Return tool arguments as a JSON object, regardless of provider shape."""
    if isinstance(arguments, dict):
        return arguments
    if not arguments:
        return {}
    if isinstance(arguments, str):
        try:
            value = json.loads(arguments)
        except (TypeError, ValueError) as exc:
            raise LLMError("bad_response",
                           f"invalid tool arguments: {exc}") from None
        if isinstance(value, dict):
            return value
    raise LLMError("bad_response", "tool arguments must be a JSON object")


def _text_content(content_value):
    """Coerce text blocks used by newer compatible servers to plain text."""
    if isinstance(content_value, str):
        return content_value
    if isinstance(content_value, list):
        return "".join(item.get("text", "") for item in content_value
                       if isinstance(item, dict))
    return ""


def _openai_tool_calls(calls=None, function_call=None):
    """Normalize chat-completions ``tool_calls`` and legacy function calls."""
    if calls is None and function_call:
        calls = [{"id": "call-0", "type": "function",
                  "function": function_call}]
    result = []
    for index, call in enumerate(calls or ()):
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        name = function.get("name") or call.get("name") or ""
        if not name:
            continue
        result.append({
            "id": call.get("id") or f"call-{index}",
            "name": name,
            "arguments": _parse_arguments(function.get(
                "arguments", call.get("arguments", {}))),
        })
    return result


def _anthropic_tool_calls(blocks):
    result = []
    for index, block in enumerate(blocks or ()):
        if isinstance(block, dict) and block.get("type") == "tool_use":
            result.append({
                "id": block.get("id") or f"call-{index}",
                "name": block.get("name", ""),
                "arguments": _parse_arguments(block.get("input", {})),
            })
    return [call for call in result if call["name"]]


def _iter_sse_events(response):
    """Yield ``(event name, data)`` pairs from a standard SSE response."""
    event_name = ""
    data = []
    for raw in response:
        line = (raw.decode("utf-8", errors="replace")
                if isinstance(raw, bytes) else str(raw)).rstrip("\r\n")
        if not line:
            if data:
                yield event_name, "\n".join(data)
            event_name, data = "", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event_name, "\n".join(data)


class _StreamToolCalls:
    """Accumulate fragmented OpenAI/Anthropic tool arguments."""

    def __init__(self):
        self.calls = {}

    def openai(self, calls):
        for index, call in enumerate(calls or ()):
            if not isinstance(call, dict):
                continue
            key = call.get("index", index)
            function = call.get("function") or {}
            item = self.calls.setdefault(key, {
                "id": call.get("id") or f"call-{key}",
                "name": "",
                "arguments": "",
            })
            item["id"] = call.get("id") or item["id"]
            item["name"] += function.get("name") or call.get("name") or ""
            arguments = function.get("arguments",
                                    call.get("arguments", ""))
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments)
            item["arguments"] += arguments or ""

    def anthropic_start(self, block):
        if block.get("type") != "tool_use":
            return
        key = block.get("_index", block.get("index", len(self.calls)))
        self.calls[key] = {
            "id": block.get("id") or f"call-{key}",
            "name": block.get("name", ""),
            "arguments": (json.dumps(block["input"])
                          if block.get("input") else ""),
        }

    def anthropic_delta(self, delta):
        # Anthropic identifies a content block by index on the event, which
        # the parser supplies before calling this method.
        key = delta.get("_index", len(self.calls))
        item = self.calls.setdefault(key, {
            "id": f"call-{key}", "name": "", "arguments": ""})
        item["arguments"] += delta.get("partial_json", "")

    def normalized(self):
        result = []
        for item in self.calls.values():
            try:
                arguments = _parse_arguments(item["arguments"])
            except LLMError:
                continue
            result.append({
                "id": item["id"],
                "name": item["name"],
                "arguments": arguments,
            })
        return [item for item in result if item["name"]]


def _json_event(data):
    try:
        return json.loads(data)
    except (TypeError, ValueError) as exc:
        raise LLMError("bad_response", f"invalid stream event: {exc}") from None


def _parse_openai_stream(response, default_model):
    calls = _StreamToolCalls()
    model = default_model
    usage = {}
    finish_reason = ""
    emitted_text = False
    saw_done = False
    for _event, raw_data in _iter_sse_events(response):
        if raw_data.strip() == "[DONE]":
            saw_done = True
            break
        data = _json_event(raw_data)
        model = data.get("model") or model
        if data.get("usage"):
            usage = data["usage"]
        choices = data.get("choices") or []
        text = ""
        for choice in choices:
            delta = choice.get("delta") or {}
            content_delta = delta.get("content", "")
            if isinstance(content_delta, str):
                text += content_delta
            elif isinstance(content_delta, list):
                text += "".join(part.get("text", "") for part in content_delta
                                if isinstance(part, dict))
            calls.openai(delta.get("tool_calls"))
            if delta.get("function_call"):
                calls.openai([{"index": 0,
                               "function": delta["function_call"]}])
            finish_reason = choice.get("finish_reason") or finish_reason
        if text:
            emitted_text = True
            yield Reply(text=text, model=model)
    if not saw_done:
        raise LLMError("bad_response", "openai stream ended before [DONE]")
    normalized = calls.normalized()
    if normalized or usage or finish_reason or not emitted_text:
        yield Reply(text="", model=model,
                    usage=_normalized_usage(usage),
                    tool_calls=normalized, finish_reason=finish_reason)


def _parse_anthropic_stream(response, default_model):
    calls = _StreamToolCalls()
    model = default_model
    usage = {}
    finish_reason = ""
    for event_name, raw_data in _iter_sse_events(response):
        data = _json_event(raw_data)
        kind = data.get("type") or event_name
        if kind == "message_start":
            message = data.get("message") or {}
            model = message.get("model") or model
            usage = message.get("usage") or usage
        elif kind == "content_block_start":
            block = data.get("content_block") or {}
            block["_index"] = data.get("index", len(calls.calls))
            calls.anthropic_start(block)
        elif kind == "content_block_delta":
            delta = dict(data.get("delta") or {})
            if delta.get("type") == "text_delta":
                yield Reply(text=delta.get("text", ""), model=model)
            elif delta.get("type") == "input_json_delta":
                delta["_index"] = data.get("index", len(calls.calls))
                calls.anthropic_delta(delta)
        elif kind == "message_delta":
            finish_reason = (data.get("delta") or {}).get(
                "stop_reason", "") or finish_reason
            usage.update(data.get("usage") or {})
    normalized = calls.normalized()
    if normalized or usage or finish_reason:
        yield Reply(text="", model=model,
                    usage=_normalized_usage(usage),
                    tool_calls=normalized, finish_reason=finish_reason)


def _append_path(base, path):
    """Append a provider route once, accepting either base or full endpoint."""
    base = (base or "").rstrip("/")
    path = "/" + path.lstrip("/")
    if base.lower().endswith(path.lower()):
        return base
    return base + path
