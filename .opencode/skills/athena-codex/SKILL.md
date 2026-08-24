---
name: athena-codex
description: Knowledge codex for ATHENA planning and design work in the Yggdrasil/soul-platform workspace. Supplies the model-of-record reading order, verified disk-truth state, wire contracts, rights ladder, build-loop stages, and knowledge-vault feeding rules. Trigger when architecting, planning, designing, writing ADRs or roadmaps, or auditing fleet drift in this repository.
---

# ATHENA Codex — fleet knowledge, distilled and verified

This is the map. The territories are the source documents listed below;
read them for depth whenever a design touches their subject matter.
Never trust this codex over the disk — re-verify before acting (rule 1
of the ATHENA doctrine).

## 1. Reading order (model-of-record hierarchy)

1. `INTEGRATION.md` — **model of record**: runtime topology, letter
   envelope, registry v2 schema, rights ladder, build loop,
   acceptance criteria A1–A8, migration order M0–M6. Supersedes the
   proposed `fleet.json`.
2. `STRATEGY.md` — direction of travel: tier model, gaps, phased
   roadmap Phase 0–4, risk register, non-goals.
3. `knowledge/engineering-rules.md` — 16 binding rules, each citing a
   lesson id. These are law, not advice.
4. `knowledge/architecture-playbook.md` — 10 proven patterns with
   lesson ids; use as default shapes for new designs.
5. `knowledge/lessons.json` — append-only lesson database (`id` L###,
   `title`, `category`, `source`, `lesson`, `tags`). Query with any
   JSON tooling; cite ids in designs.
6. `DESIGN.md` — referenced by both model docs but **absent from disk**
   (see §2). If found, it defines what the architecture IS.

## 2. Disk truth (audited 2026-08-24, post-restoration)

Restored and live on main: `doctor.py` (compile/port-squatter/baseline
checks, `--ci` mode), `sentinel.py` (watchdog: remediate -> gates ->
incidents ledger, `--watch N`; **realm gates derive from the registry**),
`realms/registry.json` schema v2 with full membership incl. tier/lang/
verify/profile, comprehensive `.github/workflows/ci.yml`, PTAH working
tree, forseti organ. Safeguards pre-commit gate activates via
`git config core.hooksPath safeguards/githooks` (committed shim).
Shipping protocol: FLOW.md - private worktrees + auto/* branches +
squash PRs; direct pushes to main are hook-blocked.

Still missing: `DESIGN.md`. Roles of `buskit/`, `hypnos/`, `tools/`
were verified via their verify suites; anything new gets inspected
before being cited in a design.

Ports (registry = single source): vulcan `:43901`, zeus `:43902`,
ptah `:43903`. `43590/43591` are retired; any listener there is a
squatter finding.

## 3. The five guarantees (each has an owner and a test)

1. Deterministic replay — same seed => byte-identical session (norn.replay)
2. Every mutation attested — witness line + seed re-runs it (norn.witness -> Hades)
3. Least privilege by default — sessions hold capabilities, not tools (norn.rights / THOTH L0–L2)
4. No partial reads — bus delivery is atomic `os.replace`; corrupt letters quarantine (ratatosk.bus)
5. Health claims require gates — nothing says "healthy" without its verify suite passing

Any design that weakens a guarantee is invalid by default; changing one
requires an explicit ADR with migration + rollback.

## 4. Contract digest

- **Letter envelope v1**: `{v, id, ts, from, to?, topic?, kind, rights,
  payload, error}` — EVERY response carries `error`. New cross-organ
  topics need a catalogue row (INTEGRATION §6) plus a kind constant in
  `bus.py`; ad-hoc inbox spam fails review.
- **Rights ladder**: watcher/L0 observe < agent_rw/L1 act < admin/L2
  administer; build = agent escalated to agent_rw, escalation logged
  both in norn.rights and THOTH grants.
- **Build loop** (the product): describe -> design -> code -> verify ->
  prove -> seal -> ship; each stage bus-gated; failures emit
  `build.stage{iterate}` up to an L2-bounded policy cap.
- **Time model**: no organ invents its own timer — periodic work
  registers with norn.pulse (`every_beats`, SLOs, quarantine, revive);
  Node-side organs follow Venus heart.js.

## 5. Feeding protocol (growing the codex)

- The learning SUBFLEET (metis/argus/logia) sweeps the evidence
  streams on a schedule and stages candidate lessons in
  `knowledge/proposals/*.proposal.json` - schema and promotion
  workflow live in the `fleet-learning` skill. Athena validates and
  ranks the queue every cycle (`python -m learning report`).
- New durable lessons are appended to `knowledge/lessons.json` with the
  next monotonic `L###`; never renumber; deprecate, don't delete. Each
  cites its source organ/module or incident - and nothing lands
  without operator sign-off.
- When a cycle or design surfaces a repeat failure, draft the lesson
  entry and propose it to the operator - the vault is append-only by
  convention, so additions deserve a human yes.
- Update A2 disk truth whenever the audit finds drift; date every
  revision. Stale truth is worse than missing truth.

## 6. Autonomy bounds (playbook pattern 9, L013/L017)

Bounded loops, persisted cycle state, capability checks per action,
quarantine over destruction, judgment calls escalate to humans. An
unbounded autonomous process is not autonomy — it is an incident.

## 7. Learning subfleet & proposal pipeline

| Agent | Diet | Output |
|---|---|---|
| @metis | incidents.jsonl, audit.jsonl, health_report FAILs, gate failures | <=5 lesson proposals/cycle |
| @argus | doc-vs-disk claims: file tables, registry, ports, codex truth | <=5 drift corrections/cycle |
| @logia | cycle logs, playbook, rules, proposals queue | <=3 pattern/rule amendments (>=3 corroborations) |

Consumption: start each planning cycle with `python -m learning report`,
grade the queue (validate evidence, dedupe vs L###), fold winners into
SPECIFY, reject losers with a recorded reason, and stage final wording
for operator sign-off. Focused runs: `/metis-cycle`, `/argus-cycle`,
`/logia-cycle`; unattended sweeps: `learning-cycle.ps1`.
