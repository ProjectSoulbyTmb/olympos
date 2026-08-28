# PTAH local LLM backends

PTAH intentionally keeps a small, provider-agnostic capability surface:

```python
reply = brain.complete(system_prompt, messages)
# reply.text, reply.model, reply.usage["input"/"output"], reply.latency_s
```

`LLMConfig.base_url` is a server base URL, normally ending at `/v1`;
PTAH appends the provider route (`/chat/completions` for OpenAI-compatible
backends or `/messages` for Anthropic). For compatibility, a configured URL
that already ends in that route is used as-is rather than getting a duplicate
path.

## Providers

* `openai` uses the OpenAI chat-completions dialect.
* `ollama`, `vllm`, `lmstudio`, `llama.cpp` (also `llamacpp`), and
  `litellm` are names for the same OpenAI-compatible transport. They are
  adapters, not separate protocol implementations.
* `anthropic` keeps the native `/v1/messages` request and authentication.
* `scripted` remains the deterministic offline queue used by tests and
  `--demo`.

Local aliases have loopback defaults:

| Alias | Default endpoint | Default model |
|---|---|---|
| `ollama` | `http://127.0.0.1:11434/v1` | `llama3.2` |
| `vllm` | `http://127.0.0.1:8000/v1` | `local-model` |
| `lmstudio` | `http://127.0.0.1:1234/v1` | `local-model` |
| `llama.cpp` | `http://127.0.0.1:8080/v1` | `local-model` |
| `litellm` | `http://127.0.0.1:4000/v1` | `local-model` |

No endpoint is contacted while reading configuration or constructing a
brain. API keys are optional for local aliases using their loopback
defaults and for loopback OpenAI-compatible endpoints; an explicitly
remote endpoint still requires `PTAH_API_KEY` (or `OPENAI_API_KEY`).

## Configuration precedence

For the selected provider, each setting resolves as:

1. `PTAH_BASE_URL` (or `PTAH_LLM_ENDPOINT`) /
   `PTAH_LLM_MODEL` / `PTAH_API_KEY`
2. backend alias keys, such as `PTAH_OLLAMA_URL`,
   `PTAH_OLLAMA_MODEL`, and `PTAH_OLLAMA_API_KEY`
3. the provider default

The original `PTAH_LMSTUDIO_URL` and `PTAH_LMSTUDIO_MODEL` keys continue
to work when the provider is left as `openai`. CLI flags override values
read from the environment.

## Streaming and tool calls

The provider adapters expose:

```python
reply = brain.complete(system, messages, tools=tools)
for part in brain.stream(system, messages, tools=tools):
   print(part.text, end="", flush=True)
```

`stream()` yields incremental `Reply` values. `part.text` is a delta, while
the final value can carry `usage`, `finish_reason`, and normalized
`tool_calls`. A tool call is a JSON-serializable mapping with `id`, `name`,
and an `arguments` object. OpenAI-compatible `tool_calls` (including legacy
`function_call`) and Anthropic `tool_use` blocks are normalized to this same
shape. Tool definitions and `tool_choice` are passed through unchanged.

The `Agent` accepts these native tool calls and sends them through the same
security classification, confirmation, and event audit path as the legacy
`{"action": ...}` JSON protocol. Existing scripted brains and non-streaming
callers remain compatible; `ScriptedLLM.stream()` is an atomic one-item
stream. Each `AgentThought` preserves `tool_calls`, `usage`, `latency_s`, and
`model`; `ptah metrics` reports total and average LLM latency alongside token
totals.

## Health-aware routing and failover

`ptah.backend.BackendRouter` accepts named brains and preserves both
`complete(system, messages, tools=...)` and incremental `stream(...)`
interfaces. It skips circuits opened by repeated transient failures and fails
over only before the first stream event. Authentication, bad-request, and
malformed-protocol errors remain fail-fast. Provider work runs outside the
router lock, so concurrent requests do not serialize one another.

`metrics()` returns availability, calls, successes, failures, in-flight
requests, and latency counters. `readiness()` is a lock-consistent,
no-network check. The server publishes readiness at `/readyz` and JSON
metrics at `/metrics` (also `/api/v1/backends/metrics`); metrics follow the
server bearer-token policy.

No health request runs at import, configuration, router construction, or
server startup. Call `check_backend()` explicitly, or opt in to the daemon
monitor with `start_health_monitor()` / `ptah serve --health-interval`. The
monitor uses the conservative local `llm_probe` path and is not a load test or
a claim of exact Copilot parity.

For a repeatable comparison of several configured aliases, use
`python -m ptah benchmark --runs 3 --json`; add repeatable `--backend
provider[=model][@base_url]` flags to override environment configuration.
Unavailable or failing backends are retained as explicit report rows, while
reachable rows include aggregate latency, byte throughput, stream support, and
observed tool-call support. The benchmark has no import or boot-time network
activity.

Before binding the REST server beyond loopback, run `python -m ptah
deploy-check --host ... --token ...`. Non-local binds require authentication
and an external TLS termination declaration. PTAH intentionally serves HTTP
only; the check reports that limitation rather than creating or pretending to
provide TLS.

For operational continuity, `BackendRouter` accepts optional `metrics_path` and
supports atomic `save_metrics()` / `load_metrics()` (`export_metrics` /
`import_metrics` aliases). `ptah serve --metrics-path` wires this on startup
without adding network boot-time probes.

PTAH server responses include a structured `request_id` plus `X-Request-ID`.
Incoming safe `X-Request-ID` values are preserved; unsafe values are replaced.
The active request id is propagated to backend LLM HTTP headers as
`x-request-id`.
