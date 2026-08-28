# PTAH LLM probe

ptah includes a conservative, explicit probe utility for local LLM provider instances that are intentionally OpenAI-compatible. The probe documents and validates only explicitly selected and configured local providers; it does not perform any discovery or fall back to a default OpenAI dial.

Key principles

- Explicit invocation only: the probe runs only when invoked with a concrete --base-url (or when called via the ptah CLI with a configured provider). It never attempts to infer or dial a provider by default.
- Local-only providers: the probe is restricted to loopback/local host addresses and configured local backends. Remote endpoints are refused.
- No implicit OpenAI default: PTAH does not assume an OpenAI endpoint or credential set; users must provide the base URL and any credentials explicitly.

What the probe reports

- reachability: whether the configured base URL responded to the probe request.
- models inventory: when available the probe issues a GET /models request to enumerate the server's model inventory and includes the returned JSON under "models". If that call fails the probe records a textual failure message under "models_error" (a string) describing the error.
- reported model: the model string returned by the primary inference/response call (model_reported) and the model the client requested (model_requested) when applicable.
- streaming support (can_stream): the probe records true when it observed an SSE/text-event-stream response. It records false when the server explicitly returned a stream-rejection (HTTP 400/404/405) and the probe successfully fell back to a non-streaming request, or when the probe observed a non-SSE JSON payload returned in response to the streaming request and parsed that JSON directly as the benchmark response (in this latter case the probe does not issue a second request). If the probe cannot reach a definitive conclusion it records "unknown".
- tool/function-call support (supports_tool_calls): the probe records true only when the returned payload explicitly includes observed tool/function-call fields (for example function_call or tool_calls). When such fields are not observed the probe records the field as null/unknown — the implementation does not emit false for absence of tool metadata.
- stream rejection fallback: the probe first attempts a streaming request (stream=true). If that streaming request receives an explicit rejection (HTTP 400, 404, or 405) the probe sends a second request with stream=false as a fallback. If the streaming request instead returns a valid non-SSE JSON payload, that JSON is parsed directly as the benchmark response and no fallback request is made.
- single tiny measurement: the probe performs a very small, single inference request (not a multi-request benchmark) and reports latency in seconds (latency_s), a simple throughput estimate reported as bytes per second (throughput_bytes_per_s) based on the response size and measured latency, and the raw response_size in bytes. This is intentionally lightweight and not a load test.
- models_error as text: failures or errors related to the models inventory call are recorded as a plain string in models_error rather than a structured object.

CLI usage

- python -m ptah.llm_probe --base-url http://127.0.0.1:8000/v1 --json
  Run a probe against the supplied base URL and print a JSON summary. When used via the ptah CLI, pass a configured provider identifier or a --base-url; the CLI will not probe unspecified providers.

Integration with the ptah CLI

The ptah CLI exposes a probe subcommand that calls into this module and prints a concise JSON summary; prefer the CLI when working interactively with the rest of the PTAH tooling. The CLI requires either a configured provider name or an explicit --base-url; it will not attempt a default OpenAI dial.

Implementation notes

- The probe attempts an initial streaming call with stream=true. If the response is a text/event-stream or SSE-like payload the probe sets can_stream=true and parses available events. If the server responds with an explicit stream-rejection (HTTP 400/404/405) the probe sets can_stream=false and retries a non-streaming request to obtain the canonical response. If the streaming request instead returns a valid non-SSE JSON payload, that JSON is parsed directly as the benchmark response and can_stream=false; no fallback request is issued in that case.
- Tri-state fields (can_stream and supports_tool_calls) can be true, false, or "unknown" when the probe cannot reach a definitive conclusion, except that supports_tool_calls is only set to true when tool/function-call metadata is observed and otherwise is recorded as null/unknown (the code does not emit false to indicate tool absence).
- Tool/function-call support is detected conservatively: the probe inspects the returned JSON for fields such as function_call, tool_calls, or other structured function-call metadata. Detection is intentionally conservative; only observed presence is recorded as true.
- The probe issues a GET /models (if the base URL appears to advertise discovery) to collect a models inventory. Failures of that call are recorded under models_error as a string description of the failure.
- The probe performs a single small inference request and reports latency and a simple byte-rate throughput estimate; it does not run multi-request benchmarks and is not designed for load testing.
- The probe returns structured JSON suitable for machine parsing. Nonzero or partial failures are represented clearly; note that models_error is a string, not a structured object.
- This utility is not intended to provide or guarantee parity with any commercial product (for example, GitHub Copilot) — it is a simple, pragmatic, conservative probe for local provider compatibility and diagnostics.

See ptah/llm_probe.py for the implementation and ptah/tests/test_probe.py for unit tests that exercise reachable, streaming, models inventory, stream-rejection fallback, and malformed responses.

## Multi-backend benchmark

Use the repeatable benchmark command when comparing local servers:

```powershell
python -m ptah benchmark --backend "ollama=llama3.2@http://127.0.0.1:11434/v1" `
  --backend "vllm=local-model@http://127.0.0.1:8000/v1" `
  --runs 3 --json
```

Without `--backend`, the report uses the configured primary provider and
`PTAH_LLM_FALLBACKS`. Each row includes the alias, endpoint, requested runs,
successful/failed runs, aggregate latency and byte throughput, model inventory,
stream/tool capability, and per-backend errors. A backend with no endpoint, or
one whose local endpoint cannot be contacted (including connection refusal), is
reported as `unavailable`; `summary.errors` is reserved for reachable backends
that return malformed or rejected responses (including model-not-found HTTP
404 and unsupported-method HTTP 501). One unavailable server does not prevent
other rows from being measured.
The function API is `llm_probe.benchmark_backends(...)` (also exposed as
`benchmark` and `compatibility_report`). It performs no network I/O until called.

## Deployment readiness

Before exposing the REST server beyond loopback, run:

```powershell
python -m ptah deploy-check --host 0.0.0.0 --token "$env:PTAH_SERVER_TOKEN" `
  --tls-terminated --json
```

`deploy-check` requires bearer authentication and an explicitly declared
external TLS terminator for non-loopback binds. PTAH's stdlib HTTP server does
not implement TLS; `--tls-terminated` records an upstream proxy/terminator, it
does not create one. `--allow-insecure` is an explicit, auditable override for
trusted networks. The check is configuration-only and never dials a server.