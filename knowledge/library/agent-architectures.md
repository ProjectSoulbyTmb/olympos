# Agent Architectures — patterns that survived production

## The reasoning-action loop

An agent turn is: observe state → ask a model for exactly ONE next move →
classify it → execute → feed the observation back. Keep the protocol
strict: one JSON object per reply, either `{"action":{"tool","args"}}`
or `{"answer":"..."}`. Strictness beats flexibility because every
downstream system (security, logging, replay) can parse it forever.

- Corrective retry: when a model reply fails to parse, inject a short
  corrective user message ONCE and continue. Two failures = error stop.
- Iteration budget: cap turns per run (25 is plenty). Count them.
- Stuck detection: hash each action (tool+args, sorted keys); N identical
  consecutive signatures means the loop is spinning — finish with a
  distinct reason so callers can distinguish it from success.

## Event sourcing is the backbone

Append every meaningful thing to an ordered log: user message, system
prompt snapshot, action, observation, denial, confirmation request,
condensation marker, error, finish. JSONL, one line per event, flush per
append. State is ALWAYS replayable: status transitions, pending
confirmations, and metrics derive from the log. Never store mutable
state outside the log without also writing an event.

Incremental readers: `slice(after=N)` returns events after index N plus
the total — pollers resume cheaply after crashes.

## Condensers keep history bounded

Dialogue grows unboundedly; prompts must not. Deterministic condensing:
always keep the first user message (the mission), keep the newest tail
that fits the budget (~4 chars/token heuristic), replace the dropped
middle with a summary marker naming what was dropped (tool counts).
Never let an LLM summarize silently — mark the cut in-band so replays
match prompts.

## Confirmation gates that actually protect

Classify every action before execution: SAFE / ELEVATED /
DESTRUCTIVE / DENIED. Policy decides which classes pause for a human.
Critical detail: after a human confirms, execute EXACTLY ONE privileged
action, then re-arm the gate — blanket confirmations erode into rubber
stamps. DENIED patterns ignore confirmation entirely.

Map risk classes onto grant ladders (L0 read-only, L1 standing,
L2 elevated-per-call) so agents and humans share vocabulary.

## Stuck, budget, and failure taxonomy

Finish reasons are part of the contract: answered | blocked_prompt |
awaiting_confirmation | stuck | max_iterations | protocol_error | error.
Callers branch on reasons, not string vibes. Record raw model output
(agent_thought) BEFORE parsing so audits can see what the brain actually
said, with token usage attached per call.

## Sidebar ask-mode

A second entry point answers questions over the current history WITHOUT
appending events or allowing tools. Progress monitoring and debugging
stay non-intrusive. Implementation: same condensed history, one extra
user turn marked `[sidebar question]`, plain-prose system prompt.

## Forking

Fork = deep-copy the event stream into a new conversation id with fresh
status and metadata (title, tags, parent link). Source stays immutable.
Use forks for debugging bad patches, A/B testing models, and swapping
toolsets mid-investigation.

## What did NOT earn its complexity (yet)

Browser automation, docker-per-run sandboxes, streaming completions,
OAuth MCP flows, warm pools. Each is real technology; adopt only when a
workload demands it. Local-first single-box fleets rarely do early.
