---
name: athena-codex
description: Knowledge codex for ATHENA planning and design work in the Olympos/olympos workspace. Supplies the model-of-record reading order, verified disk-truth state, wire contracts, rights ladder, build-loop stages, and knowledge-vault feeding rules. Trigger when architecting, planning, designing, writing ADRs or roadmaps, or auditing fleet drift in this repository.
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
3. `knowledge/engineering-rules.md` — 21 binding rules, each citing a
   lesson id. These are law, not advice.
4. `knowledge/architecture-playbook.md` — 10 proven patterns with
   lesson ids; use as default shapes for new designs.
5. `knowledge/lessons.json` — append-only lesson database (`id` L###,
   `title`, `category`, `source`, `lesson`, `tags`). Query with any
   JSON tooling; cite ids in designs.
6. `DESIGN.md` — present at root (re-verified 2026-08-24): ecosystem
   table, hard rules, decision log. Defines what the architecture IS.

## 2. Disk truth (audited 2026-08-24, post-restoration)

Restored and live on main: `doctor.py` (compile/port-squatter/baseline
checks, `--ci` mode), `sentinel.py` (watchdog: remediate -> gates ->
incidents ledger, `--watch N`; **realm gates derive from the registry**),
`realms/registry.json` schema v2 with full membership incl. tier/lang/
verify/profile, comprehensive `.github/workflows/ci.yml`, PTAH working
tree, forseti organ. Safeguards pre-commit gate activates via
`git config core.hooksPath safeguards/githooks` (committed shim);
a `post-commit` shim runs `mirror_sync.py --hook` so every commit
converges the `D:\Default Project` execution mirror automatically
(`--audit --strict` is the CI-able drift check).
Shipping protocol: FLOW.md - private worktrees + auto/* branches +
squash PRs; direct pushes to main are hook-blocked.

`DESIGN.md` present at root (re-verified 2026-08-24). Roles of
`buskit/`, `hypnos/`, `tools/` verified via their verify suites;
anything new gets inspected before being cited in a design.

Disk watchlist (re-audited 2026-08-25, argus muster): `heart/` tree is
ABSENT in both roots (empty dir, zero tracked files) - the 2026-08-24
"v0.2.0 desk companion on port 4767" entry was stale; restoration from
heart's own remote or retirement of the pending row is an OPEN operator
decision, :4767 remains proposed-only/unbound. `hebe/` claimed by its
lane (registry row exists). New since last audit: `haven/` (:43910,
sqlite-fts5 search organ) and `ares/` (vault cipher, T1) are gated on
disk with registry rows but were undocumented until the 2026-08-25
muster added them to DESIGN.md - keep/retire adjudication open.
`docs/` founded 2026-08-24 (`adr/`, `plans/cycles/`, `contracts/`)
holds the ATHENA artifact suite.

Knowledge organ (audited 2026-08-24, post auto-wire):
`knowledge/engine.py` TF-IDF search indexes library docs, lessons.json,
and product DBs **discovered by convention** - any
`knowledge/<name>/<name>.json` with an `entries` list (optional
top-level `prefix` for compact ids) self-registers; the index
self-invalidates via engine-versioned corpus signature, so drop-ins
are searchable with no rebuild. Registry row `knowledge`
(kind knowledge, verify -> `knowledge/verify_knowledge.py`, 21 realm
members) puts the organ under sentinel gate derivation.
`knowledge/verify_knowledge.py` runs 7 generic gates; doctor discovers
every `knowledge/verify_*.py` automatically. First product DB:
webstudio/ (25 WS-### entries + 7 topic files).

Wiring pass (2026-08-24 late; membership re-counted 2026-08-25):
registry v2 carries 32 members (argus muster found the artemis row
duplicated verbatim -> 33 raw rows; duplicate deleted and L036 minted
requiring loader-level dedupe) -
satellites riley `:43907` (`D:/riley`, gated via portable wrapper
`verify_riley_satellite.py`: skip-green when undeployed/dark, deep mode
runs the satellite's own suite) and aphrodite `:43904`
(`D:/Aphrodite`) declared without in-repo gates; harmonia re-based to
`:43908` after colliding with the live RILEY studio. The in-repo
`riley-studio/` is a DISTINCT product (Electron+ComfyUI desktop tier,
registry row present) - not a copy of `D:/riley`. Kind constants
(`TOPIC_*`/`KIND_*`) live in `ratatosk/bus.py`. Live wires: Hades
broadcasts `provenance.seal` on every seal (`artifacts.sealed`), GAIA
publishes per-member samples on `vitals`, relay announces
`fleet.render-done` for studio jobs finished outside its order stream.
INTEGRATION §6 documents as-built pre-catalogue lanes (gates, witness,
rights, hades-alerts, zeus-events, vulcan, daedalus, hypnos, poseidon).

Ports (registry = single source, re-audited 2026-08-25): zeus `:43902`,
vulcan `:43901`, ptah `:43903`, daedalus `:43905`, haven `:43910`,
aphrodite `:43904` (only live fleet listener at audit time); harmonia
re-based to `:43908` after colliding with the live RILEY studio; riley
satellite `:43907`. heart `:4767` proposed via ADR-0001 but UNBOUND -
tree absent from disk. `43590/43591` are retired; any listener there is
a squatter finding.

Repo homes (policy 2026-08-24, operator-set, in force until revoked):
`D:\` is the ONLY localside repository home. Mint-point enforcement:
`safeguards/repo_home_profile.ps1` shell shim refuses clone/init/
worktree-add/submodule-add outside `D:\`; canonical authority is
`safeguards/repo_home_guard.py` (`check`/`policy`/`audit` CLI — audit
is an operator tool, deliberately not a CI gate); `verify_repo_home.py`
gates the logic. Known legacy violation: an older full checkout of
this repo lives at OneDrive `Documents\Default Project` — treat it as
frozen; never commit or clone from it.

Tree repair (2026-08-25): `safeguards/tree_repair.py --fix` mechanically
repairs stale locks / missing tracked files / generated dirt /
patch-duplicate auto/* branches (per-root hash-chained ledger in
data/); interrupted merge-rebase states and split-brain repos are
report-only. Gate: `verify_tree_repair.py`. Completed-stranded-work
record: hades operator authority (13/13), artemis organ (16/16),
relay mind-mirror (12/12), mind organ (GREEN) all shipped 2026-08-25
via PRs #73-#77.

Operator directive (2026-08-25, binding on every session): ALL
BUILDING IS DELEGATED TO THE MUSTER FLEET - construction runs through
the Daedalus workshop lane (@epeios/@icarus/@talos/@perdix/@kourai/
@kerux/@trophonios under @daedalus) and knowledge cycles through the
learning subfleet; primary sessions plan, dispatch, verify, integrate,
commit - never build organ code inline. No fitting agent = escalate to
operator. Recorded as DESIGN.md hard rule 5 + root `AGENTS.md`.
First muster under this doctrine: 2026-08-25 (L036-L045 minted,
artemis dedupe, drift fixes; log:
`docs/plans/learning/2026-08-25-muster-decisions.md`).

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
