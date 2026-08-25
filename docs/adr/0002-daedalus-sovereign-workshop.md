# ADR 0002 — DAEDELUS Sovereign Workshop: fleet authority, universal intake, isolation

**Status:** Proposed — awaiting operator confirmation on two labeled
constraint points; implementation gated on Phase W0 (fleet green).
Mechanics live in `docs/plans/sovereign-workshop-roadmap.md`.

**Date:** 2026-08-25 · **Author:** ATHENA · **Companions:**
`docs/plans/expansion-stability-roadmap.md` (DAEDALUS = executor of record),
`INTEGRATION.md` §6 (topic catalogue), ADR 0001.

## 1. Context

Operator orders (2026-08-25), paraphrased without softening:

1. Give DAEDELUS highest tier access + skills + full automation capability
   for him and the entire fleet.
2. Keep his workshop clean from outside interference.
3. All building plans are initially delivered to his workshop; he categorizes
   blueprints and automates all repairs — system repairs, code fixes, building.
4. Create advanced mechanisms for this arrangement's survival.

### Disk truth this rests on (verified 2026-08-25)

| Fact | Evidence |
|---|---|
| DAEDELUS already holds the top realm-scoped tier: `operator = None` = every verb on his surface | `norn/rights.py:41-46`; enforcement `daedalus/server.py:153-158` |
| Inbound connections arrive anonymous, default to operator | `daedalus/server.py:100-103`; witness records cmd+args only |
| Loopback bind + session/line caps | `daedalus/content.py:10-13` (`127.0.0.1:43905`, 8 sessions, 1 MiB) |
| GAP: silent port-increment fallback drifts him off the registered address | `daedalus/server.py:68-84` (`port += 1`, up to 10×) |
| Audit chain + sealed artifacts + repair stats persist | `content.py:19-33`; hash-chained `.lock` writes `kernel.py:457-477` |
| GAP: build queue / lane state is in-memory — any intake backlog dies with the process | no queue persistence found in `kernel.py` |
| Bus carries `fleet.build`/`fleet.repair` kinds; unknown kinds/profiles rejected at envelope | `buskit/envelope.py:54-55,121-124` |
| External intake precedent: relay claims intents → CLI commissions; repair sweeps publish proof | `relay/bridge.py:272`; DESIGN.md relay row 2026-08-24 |
| Repair convergence proven: both fault classes repaired 23/23 | `python -m daedalus status`, repair_stats |
| Registry `profile` field has NO enforcing consumer; enforcement lives in `norn/rights.py` tables | grep across root `*.py` |
| Fleet CI red at infra layer (billing-dead runner; self-hosted retarget #81 merged, unstable); main ahead 1 / behind 2 | `gh run list`; `git log main..origin/main` |

## 2. Options considered

| | A. Federated execution | B. Sovereign hub, bare | C. **Sovereign workshop, journaled (chosen)** |
|---|---|---|---|
| Shape | Organs plan locally; DAEDELUS only executes commissions | All plans enter raw; execute immediately | Plans enter as bus letters; journaled; classified E1/E2/E3/reject before bounded execution |
| Fits "ALL plans delivered to his workshop" | No | Yes | Yes |
| Survival | n/a | Poor (in-memory queue) | Strong (WAL journal + pulse SLO + revive + backpressure) |
| Blast radius | Small | Large — poison plan hits live builder | Large but contained — quarantine + ceilings pre-execution |
| Reversibility | n/a | Poor | Good — per-phase reverts + one-flag kill switch |

**Decision: Option C.** Single-intake is explicit operator intent; C differs
from B by survival, which the operator also ordered. A stays available;
rollback is trivial because C is additive.

## 3. Decision

### 3.1 Authority (the elevation, stated precisely)

1. **Operational tier:** formalized as the fleet's top operational tier —
   full surface on his own realm (`operator = None`, already true), full
   operator surface on ATLAS guests he weaves, executor-of-record for E1/E2
   expansion. Registry row `"profile": "admin"` lands **in the same PR** as
   `DAEDALUS_PROFILES["admin"]` in `norn/rights.py` + DESIGN.md ecosystem/
   decision-log rows — one coherent truth-set; no cosmetic-only flips.
2. **CONSTRAINT POINT #1 — meta-right `grant` stays out of reach.**
   Grant/escalation management (core ladder, `norn/rights.py:20-22`) remains
   human/THOTH-side. A build daemon able to rewrite its own permissions is
   exactly what L013/L017 forbid (unbounded autonomy = incident). Granting it
   requires explicit amendment of this ADR — it will not slip in via code.
3. **Skills:** blueprint corpus (`blueprints.py`, `blueprint_*.py`), rules
   engine (`rules.py`), warden self-healing, knowledge organ auto-indexing;
   R3 learning proposals remain the skill-growth loop.

### 3.2 Universal intake (all plans enter through the workshop)

- New kind **`fleet.plan`** added to the `updates` topic set
  (`buskit/envelope.py` TOPICS) per INTEGRATION §6: catalogue row + kind
  constant; envelope validation comes free (unknown-kind rejection exists).
- Any organ or the operator submits plan letters; DAEDELUS claims them,
  journals write-ahead, classifies:
  - **E1 commissionable** — blueprint match → immediate bounded build;
  - **E2 candidate** — near/no match → queued for a blueprint-authoring
    session (template + self-test gate + named faults);
  - **E3 realm-shaped** → promotion proposal staged for operator sign-off
    (retained human gate — CONSTRAINT POINT #2);
  - **reject** → published back with non-empty `error`, letter quarantined.
- Outcomes ride existing `fleet.build`/`fleet.repair` kinds with `plan_id`
  correlation — no new response protocol.

### 3.3 Automated repair authority (system repairs + code fixes)

- Sentinel remediation hands jobs to the workshop as `fleet.plan` letters
  (kind reuse keeps one pipeline).
- Repairs run where they already converge: ATLAS-jailed builds with
  verify-fix-retry culprit isolation (proven 23/23) and doctor check+fix
  sweeps with published proof (relay precedent).
- Guarantee #5 enforced: gate-green proof before any "fixed" claim; failures
  land in the incidents ledger, never in a health claim.

### 3.4 Isolation ("clean from outside interference")

1. **Fail loud on port capture:** remove the `port += 1` fallback in
   `_bind()`; a :43905 squatter becomes a doctor/sentinel finding, not drift.
2. **Caller identity:** handshake gains optional `who`; witness lines record
   caller + cmd + args (guarantee #2 quality upgrade).
3. **Writer discipline:** `fleet.plan` producers documented in INTEGRATION §6;
   corrupt letters quarantine (ratatosk atomicity already guarantees no
   partial reads — guarantee #4).
4. **Loopback + caps unchanged:** `127.0.0.1`, 8 sessions, 1 MiB lines.

### 3.5 Survival mechanisms

| Mechanism | Source organ (existing, not new tech) |
|---|---|
| Write-ahead plan journal (`data/plans/inbox.jsonl`) replayed on boot | audit-chain write pattern |
| Backpressure ceiling on backlog — reject with error, never silent drop | letter `error` contract |
| Quarantine over destruction for poison input | ratatosk + warden posture |
| Pulse heartbeat with SLO, quarantine, revive | norn.pulse registration |
| Process death → sentinel watch revives workshop | `sentinel.py --watch N` |
| Port capture → loud failure + remediation, address stays registered | registry-as-truth + doctor squatter sweep |
| Sealed artifacts survive anything short of disk loss | SHA-256 artifact seals (`ARTIFACTS_DIR`) |
| Hash-chained audit detects tampering, rotation at size cap | existing audit chain |

## 4. Consequences

- **Guarantee #3 is deliberately refined, not silently weakened:** privilege
  concentrates in ONE watched realm under ceilings, ledgers, and quarantine —
  replacing diffuse ad-hoc grants (relay already commissions and repairs).
  Labeled as a constraint refinement per doctrine; reversible via this ADR.
- E3 promotions still cost a human yes. Automation covers building, fixing,
  categorizing; it does not self-promote realms or hold `grant`.
- Single-brain risk accepted: workshop outage pauses fleet construction.
  Mitigated by survival §3.5; sentinel revives; journaled plans resume.
- Blueprint taxonomy must track the corpus or the categorizer misroutes;
  R3 quarterly prune applies to categories too.

## 5. Rollback path

Each roadmap phase reverts independently (`git revert` of its squash commit);
intake has a kill-switch constant (`content.INTAKE_ENABLED = False`) that
stops claiming without touching the bus; the elevation PR reverts to
`operator` profile everywhere; journaled-but-unbuilt plans remain readable in
the inbox journal for manual replay.

## 6. Operator confirmations requested

1. Confirm Option C (single intake + bounded autonomous execution).
2. Confirm retention of constraint points: no `grant` right for DAEDELUS;
   E3 promotion keeps operator sign-off.

