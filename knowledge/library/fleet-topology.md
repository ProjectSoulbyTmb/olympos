# Fleet Topology — organs, ports, and ownership

## The organs

| Organ | Role | Notes |
|---|---|---|
| zeus | protection kernel: process sentinel, churn oracle, integrity baseline (aegis), quarantine, bolts, circuit breakers | JSON-lines server |
| vulcan | automation sandbox: thermal sim, rules engine with schema gates, warden self-healing | authoritative server; proving ground for build-and-verify loops |
| hades | provenance: SHA-256 seals + HMAC manifests + anchor files, hash-chained audit, ghost detection, watermarks | CRLF-aware sealing on Windows |
| ratatosk | filesystem message bus: mailboxes under data/post, per-sender seq counters, topics with consumer cursors, heartbeats, correlated replies, priority lanes | no ports, no daemons; registry.json under the post root |
| norn | shared machinery: capability rights profiles, pulse organs with SLO quarantine, witness journals, clockwork determinism seam | rights gate dispatch on other organs |
| hypnos | silent task organ: letter/dropin claim-run-retry-resume, audited actions, backoff, crash resume, build-gate reports | scheduled-task installer |
| ptah | software-engineering agent kernel: reasoning-action loop, audited tools, risk classes, skills, memory, MCP client, REST + OpenAI-compatible endpoints | port 43903 |
| gaia | ops kernel: git sync state, CI verdicts, patrol loops | node |
| thoth-private | operator doctrines: knowledge entries, wisdom/facts, scribe, stabilize, federation, autonomic loop | node, sanctioned-seam merge |

## Port ownership

43901 vulcan · 43902 zeus · 43903 ptah. Unknown listeners elsewhere are
informational; strangers ON owned ports are incidents. Tests bind port 0
and never production ports.

## Registry-driven gates

Realm gates are derived from a registry (realms/registry.json v2):
adding an organ with a verify suite and a registry row wires it into
sentinel sweeps and CI without editing gate lists by hand. Gates stay
declarative; code stays honest.

## The flow contract

Root checkout = integration mirror (pull-only). Writers live in
.worktrees/<name> on auto/<name> branches. main updates only via PR.
hooks/pre-push (installed via flow.ps1) enforces client-side;
safeguards/install.ps1 wires the pre-commit contract.

## Doctrine anchors

knowledge/lessons.json (append-only lessons), architecture-playbook.md,
engineering-rules.md, AGENTS/AGENTS-style contracts where present.
Design guidance lives in docs; judgment calls cite them.

## Cadence

doctor.py --ci in every CI run; sentinel sweeps continuously with
remediated retries; nightly selfchecks prune conversation stores and
append ledger entries; scheduled tasks keep kernels alive across
reboots with battery-friendly flags.
