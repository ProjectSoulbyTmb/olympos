# Observability — event sourcing, ledgers, and honest metrics

## Event sourcing for agents

Every conversation is an append-only JSONL log of typed events: user
message, system prompt, agent thought (raw model output + token usage),
action, observation, denial, confirmation request, condensation, error,
finish. Crash-safe by construction; replay reconstructs state exactly;
incremental consumers poll `after=<index>`.

## What to record

- Raw brain output before parsing (audits see what the model said).
- Token usage per call (input/output) — cost tables change, tokens do not.
- Risk verdicts with reasons on every action.
- Denials AND near-misses: what the security layer refused teaches policy.
- Finish reasons as an enum: answered | awaiting_confirmation | stuck |
  max_iterations | protocol_error | error | blocked_prompt.

## Ledgers

Incident ledger: JSONL entries {ts, kind, name, detail} appended by
watchdogs; stable ids persist across sweeps; auto-close only after a
clean sweep; MTTR banked on close turns reliability into a metric.
Mirror critical ledger lines onto the message bus so other organs can
react without polling files.

## Health reports

Doctor-style summaries: one row per check with pass/fail/fixed/warn,
elapsed time, and a machine-readable report file. Verdicts are words
(STABLE / N UNRESOLVED), never exit codes alone. Reports land in
gitignored data dirs.

## Rollups

Per conversation: llm_calls, tokens in/out, actions, answers.
Per fleet: gate pass rates over time, MTTR medians, incident counts by
signature. Dashboards are optional; JSONL plus jq is a dashboard.

## Tracing hooks

Lifecycle hooks double as trace points: PostToolUse logging to files,
Stop hooks enforcing summary artifacts, UserPromptSubmit injecting git
context. Hook stdout may carry additionalContext that enriches the next
prompt — observability feeding cognition.

## Honesty rules

Never claim health without a green gate in the same breath. Never
average away a red suite. Fixed = verified fixed, not "probably fine
now". Warnings are counted, surfaced, and reviewed — they are tomorrow's
failures.
