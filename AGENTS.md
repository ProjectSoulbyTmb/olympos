# AGENTS.md - standing orders for every session in this repo

## Operator directive 2026-08-25: ALL BUILDING IS DELEGATED TO THE MUSTER FLEET

Construction is executed by subagents, never inline by the primary
session. The primary plans, dispatches, verifies, integrates, commits;
the fleet builds.

- **Build work** (design -> code -> verify -> prove -> seal -> ship):
  dispatch to the Daedalus workshop lane - @daedalus (plan/build
  orchestration), @epeios (standard construction), @icarus
  (fault-injection flight tests), @talos (gates + health patrols),
  @perdix (new blueprints), @kourai (lane tending), @kerux (update
  stream), @trophonios (provenance certification).
- **Knowledge cycles**: dispatch to the learning subfleet - @metis,
  @argus, @logia - under `fleet-learning` budgets, or run
  `/muster-fleet` for the full coordinated sweep.
- If no fleet agent fits the task, ESCALATE TO THE OPERATOR instead of
  building inline. Do not silently absorb build work into the primary.
- Reading, drift checks, gate runs, commit/bookkeeping stay with the
  primary; anything that constructs or modifies organ code does not.

Doctrine of record: `INTEGRATION.md`, `DESIGN.md`,
`knowledge/engineering-rules.md`, `.opencode/skills/athena-codex/SKILL.md`.
Shipping: `FLOW.md`. Repo homes: one localside home on `D:\` (L033);
this OneDrive checkout stays uncommitted-except-by-operator-order.
