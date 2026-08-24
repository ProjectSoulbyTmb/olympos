# Security & Grants — fail-safe by construction

## Risk classification before execution

Every agent action passes a classifier before it runs. Regex rule
tables over the rendered action (tool name + sorted args) sort into:

- DENIED — never executable; confirmation CANNOT override. Root
  deletes, filesystem formats, fork bombs, host power control,
  machine-hive registry writes.
- DESTRUCTIVE — irreversible or far-reaching (recursive deletes, force
  pushes, hard resets, destructive SQL). Always gated behind explicit
  human confirmation under every policy.
- ELEVATED — allowed but consequential: network fetches, package
  installs, remote git transfers, permission changes. Logged loudly.
- SAFE — everything else.

First matching table wins; order the checks deny → destructive →
elevated → safe.

## Confirmation that re-arms

Policies: auto (run all non-denied), confirm-risky (destructive waits),
confirm-all (elevated too). The critical invariant: one confirmed turn
executes exactly ONE privileged action, then the gate re-arms. Blanket
"yes to all this session" is how guardrails become decoration.

## Grant ladder

Map risk classes onto the house ladder so agents and humans share
language: L0 read-only runs freely; L1 needs a standing grant; L2 is
per-call elevation in an authorized session; DENY is forever. Destructive
tools stay L2 even when automation would be convenient.

## Secrets hygiene

Credentials live in environment variables with a reserved prefix;
values are collected once per run and redacted from observations,
action arguments, and model output before anything touches history or
logs. Never write secrets to disk outside secret stores. Redaction at
the boundary is cheaper than rotation after a leak.

## Path and process scoping

Agents get a workspace root; every path resolves through a checker that
refuses absolute paths, drive letters, UNC devices, `..` climbs, and
tilde expansion. Shell commands run scoped to resolved directories with
timeouts and output caps. Deletion tools are omitted on purpose — if
the work needs deletion, the shell exists, and the security layer sees it.

## Audit or it did not happen

Actions, verdicts, denials, confirmations, and observations are events
in an append-only log with hash-chaining where tamper evidence matters.
Quarantine beats delete for suspicious artifacts. Every automated
mutation carries its justification in the ledger entry.
