# LLM Agent Field Survey — 2026 state of the art (condensed)

## What OpenHands taught the field

- Event-sourced conversations with typed events make agents auditable
  and replayable — the log is the product.
- Strict single-action protocols (one JSON object per turn) beat free
 form "reasoning traces" for reliability and security integration.
- Security analyzers + confirmation policies belong INSIDE the loop,
  not outside it; DENIED must outrank confirmation.
- Condensers: deterministic budget compression beats lossy LLM summaries.
- Microagents/skills: keyword-triggered markdown knowledge cards scale
  domain expertise without fine-tuning.
- MCP became the interop standard for external tools; config-file
  driven servers, namespaced tools, per-call risk analysis still apply.
- Agent servers expose REST+WebSocket with OpenAI-compatible gateways
  so existing chat UIs become agent frontends.
- Benchmarks (SWE-bench-style) drove real progress but scenario gates
  catch what benchmarks miss.

## Patterns worth stealing (implemented here)

Fallback chains (transient-only), remediated retries, delta-based
assertions, sidebar ask-mode, conversation forks, secret redaction at
boundaries, registry-derived gate lists, worktree-per-writer flows.

## Patterns deliberately deferred

Browser-use agents (heavy, headless-hostile). Docker-per-run
sandboxes (needs daemon; local-first fleets use process scoping +
risk classes until multi-tenant demand exists). Streaming completions
(nice UX, zero correctness value). OAuth-MCP transports (browser
flows break automation; prefer API-key servers). Warm pools (only
under real concurrent load).

## Evaluation doctrine

Benchmarks measure capability on curated tasks; gates measure health
on YOUR system. Both matter. Scenario fixtures with scripted brains
give deterministic regression signal; optional live-model runs measure
capability drift across model versions. Record tokens per task — cost
is a first-class metric.

## Prompting craft that survives

System prompts state identity once, then protocol, then tools with
schemas, then workspace facts, then triggered skills. Keep protocol
instructions SHORT and mechanical ("reply with exactly one JSON
object"). Corrective feedback quotes the failure mode. Context
injection via hooks lands as [context] blocks, never silent mutation.

## The meta-lesson

Every platform converges on: event log + typed tools + risk gating +
deterministic tests + provider abstraction + knowledge retrieval.
Differences are packaging. Build the six well and the rest is UI.
