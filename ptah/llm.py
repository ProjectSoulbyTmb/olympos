"""PTAH llm - provider-agnostic language model access.

Two real transports over the standard library only:

  openai     POST {base_url|https://api.openai.com/v1}/chat/completions
             (works with any OpenAI-compatible server: Ollama, vLLM,
              LM Studio, LiteLLM proxies - local-first friendly)
  anthropic  POST https://api.anthropic.com/v1/messages

plus `scripted`: a deterministic reply queue used by tests, the demo
mode and CI - the kernel is fully exercisable offline.

Reliability: transient failures (network errors, timeouts, HTTP 429 and
5xx) retry with exponential backoff honoring Retry-After; hard client
errors fail fast with a classified LLMError.
"""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ptah import content


class LLMError(Exception):
    """Classified LLM failure."""

    def __init__(self, kind, message, status=None):
        super().__init__(f"[{kind}] {message}")
        self.kind = kind
        self.status = status


RETRYABLE_STATUSES = {429, 500, 502, 503, 504, 529}


@dataclass
class LLMConfig:
    provider: str = "openai"            # openai | anthropic | scripted
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
        env = os.environ.get
        provider = env(f"{prefix}_LLM_PROVIDER", "openai")
        default_key = (env("ANTHROPIC_API_KEY") if provider == "anthropic"
                       else env("OPENAI_API_KEY")) or ""
        key = env(f"{prefix}_API_KEY") or default_key
        return cls(provider=provider,
                   model=env(f"{prefix}_LLM_MODEL",
                             "gpt-4o-mini" if provider == "openai"
                             else "claude-sonnet-4-5"),
                   api_key=key,
                   base_url=env(f"{prefix}_BASE_URL", ""))


@dataclass
class Reply:
    text: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0


# ------------------------------------------------------------- scripted
class ScriptedLLM:
    """Deterministic offline brain: pops one reply per call."""

    provider = "scripted"

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def complete(self, system, messages):
        self.calls.append({"system": system, "messages": list(messages)})
        if not self._replies:
            raise LLMError("bad_response", "scripted brain exhausted")
        return Reply(text=self._replies.pop(0), model="scripted")

    # keep parity with LLM API used by callers/tests
    @property
    def config(self):
        return LLMConfig(provider="scripted")


# ----------------------------------------------------------------- real
class LLM:
    def __init__(self, config=None):
        self.config = config or LLMConfig()
        if self.config.provider not in ("openai", "anthropic"):
            raise LLMError("config",
                           f"unknown provider {self.config.provider!r}")

    # ---- public ----
    def complete(self, system, messages):
        t0 = time.time()
        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                reply = self._once(system, messages)
                reply.latency_s = round(time.time() - t0, 3)
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

    # ---- internals ----
    def _endpoint(self):
        if self.config.provider == "anthropic":
            base = self.config.base_url or "https://api.anthropic.com/v1"
            return base.rstrip("/") + "/messages"
        base = self.config.base_url or "https://api.openai.com/v1"
        return base.rstrip("/") + "/chat/completions"

    def _headers(self):
        if self.config.provider == "anthropic":
            return {
                "content-type": "application/json",
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "user-agent": content.USER_AGENT,
            }
        if not self.config.api_key:
            raise LLMError("auth", "missing API key (set PTAH_API_KEY)")
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {self.config.api_key}",
            "user-agent": content.USER_AGENT,
        }

    def _payload(self, system, messages):
        if self.config.provider == "anthropic":
            return json.dumps({
                "model": self.config.model,
                "system": system,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "messages": [{"role": m["role"], "content": m["content"]}
                             for m in messages],
            }).encode("utf-8")
        chat = [{"role": "system", "content": system}]
        chat += [{"role": m["role"], "content": m["content"]}
                 for m in messages]
        return json.dumps({
            "model": self.config.model,
            "messages": chat,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }).encode("utf-8")

    def _parse(self, raw):
        data = json.loads(raw.decode("utf-8"))
        if self.config.provider == "anthropic":
            text = "".join(block.get("text", "")
                           for block in data.get("content", [])
                           if block.get("type") == "text")
            usage_in = data.get("usage", {}).get("input_tokens", 0)
            usage_out = data.get("usage", {}).get("output_tokens", 0)
        else:
            choices = data.get("choices") or []
            if not choices:
                raise LLMError("bad_response", "no choices in response")
            text = choices[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            usage_in = usage.get("prompt_tokens", 0)
            usage_out = usage.get("completion_tokens", 0)
        return Reply(text=text or "", model=data.get("model", ""),
                     usage={"input": usage_in, "output": usage_out})

    def _once(self, system, messages):
        req = urllib.request.Request(
            self._endpoint(), data=self._payload(system, messages),
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
            kind = ("rate_limit" if exc.code == 429 else
                    "auth" if exc.code in (401, 403) else
                    "server" if exc.code >= 500 else
                    "bad_request")
            retry_after = None
            try:
                retry_after = float(exc.headers.get("Retry-After") or 0) \
                    or None
            except (TypeError, ValueError):
                retry_after = None
            if exc.code in RETRYABLE_STATUSES:
                raise _Transient(kind, f"HTTP {exc.code}: {body!r}",
                                 status=exc.code, retry_after=retry_after)
            raise LLMError(kind, f"HTTP {exc.code}: {body!r}",
                           status=exc.code)
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                OSError) as exc:
            raise _Transient("network", str(exc))


class _Transient(Exception):
    def __init__(self, kind, message, status=None, retry_after=None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
