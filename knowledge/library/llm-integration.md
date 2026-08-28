# LLM Integration — provider-agnostic patterns (stdlib edition)

## One client, three transports

OpenAI-compatible `/chat/completions` covers OpenAI plus every local
server worth having (Ollama, vLLM, LM Studio, LiteLLM proxies).
Anthropic `/v1/messages` differs in shape: `system` is top-level,
`max_tokens` required, content is a list of blocks, usage splits
input/output. Keep payload builders and parsers per provider behind one
`.complete(system, messages) -> Reply{text,usage,model}` surface, with
`.stream(system, messages)` yielding incremental `Reply` values when the
provider supports server-sent events.

urllib.request is enough. POST JSON, read JSON, honor timeouts.

Normalize provider tool output at the transport boundary to
`{id, name, arguments}`. OpenAI `tool_calls` (and legacy `function_call`) and
Anthropic `tool_use` can then share the same audited agent execution path;
provider-specific tool schemas remain pass-through payload data.

## Retries that respect providers

Retry ONLY transient failures: network errors, timeouts, HTTP 429 and
5xx. Back off exponentially from a small base (0.5s), cap the sleep
(8s), and honor Retry-After when present. Auth (401/403) and other 4xx
fail FAST — retrying a bad key just burns quota. After N attempts
raise a classified error carrying kind + status so callers can branch.

## Fallback chains

Wrap the primary with ordered fallbacks. Semantics that survive review:
per-call (every request starts at primary), transient-only advancement
(rate_limit/server/network/timeouts), first success wins, final failure
re-raises the original primary error. Record which brain served each
reply — cost attribution dies without it. Nestable: a fallback can be
another chain for multi-level redundancy.

## Redaction at the boundary

Environment variables named `<PREFIX>_SECRET_*` are credentials by
definition. Collect their values once per run; replace occurrences in
observations, action arguments, and raw model output with a fixed marker
BEFORE anything touches history or logs. Redaction is cheaper than
rotation.

## Token accounting

Parse usage from every reply (prompt/completion or input/output),
attach it to the event that triggered the call, and roll up per
conversation: calls, tokens in/out, actions taken, answers given.
Cost tables change monthly; token counts do not — store tokens, derive
costs at display time.

## Gateways: become the backend

Expose your agent as an OpenAI-compatible endpoint (`/v1/models`,
`/v1/chat/completions`; streaming gateway support is a separate concern).
Continuity via a response
header carrying your conversation id that clients echo back — the
OpenAI protocol sends full history every request precisely because it
assumes stateless backends; you are not one. Accept Bearer auth on the
same token as your native API. Return clean JSON errors with correct
status codes even when internal code throws.

## Local models

The same OpenAI-compatible client should reach `http://127.0.0.1:11434`
(Ollama-style) by base_url swap alone. Local-first means the demo mode,
the tests, and the offline fallback never need a remote key.
