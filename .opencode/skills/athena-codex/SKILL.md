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

## 2. Disk truth (audited 2026-08-24)

Referenced by docs but **missing** after the §9 lineage reset:
`DESIGN.md`, `doctor.py`, `sentinel.py`, `realms/registry.json`,
CI wiring for new gates, PTAH working tree (orphaned-untracked).
Restoration must pass `verify_scope.py` first (INTEGRATION §9).

Present at root: `verify_autopilot.py`, `verify_buskit.py`,
`verify_scope.py`, `register-{zeus,thoth,ptah,hypnos,soul-tasks}.ps1`
(generic elevated-task registrar pattern), `elevate-bootstrap.ps1`,
dirs: `zeus/ gaia/ thoth-private/ vulcan/ hades/ ratatosk/ norn/
buskit/ hypnos/ knowledge/ tools/ image-toolkit/ assistant/ data/`.
Roles of `buskit/`, `hypnos/`, `tools/` are `[UNVERIFIED]` — inspect
before citing them in any design.

Ports (per INTEGRATION §2): vulcan `:43901` only. `43590/43591` are
retired; treat any listener there as a squatter finding. ZEUS `:43902`
appears in STRATEGY.md's audit table — reconcile against code before
relying on it.

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

- New durable lessons are appended to `knowledge/lessons.json` with the
  next monotonic `L###`; never renumber; deprecate, don't delete. Each
  cites its source organ/module or incident.
- When a cycle or design surfaces a repeat failure, draft the lesson
  entry and propose it to the operator — the vault is append-only by
  convention, so additions deserve a human yes.
- Update §2 disk truth whenever the audit finds drift; date every
  revision. Stale truth is worse than missing truth.

## 6. Autonomy bounds (playbook pattern 9, L013/L017)

Bounded loops, persisted cycle state, capability checks per action,
quarantine over destruction, judgment calls escalate to humans. An
unbounded autonomous process is not autonomy — it is an incident.
