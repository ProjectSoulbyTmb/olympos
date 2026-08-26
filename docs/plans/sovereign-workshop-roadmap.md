# Sovereign Workshop Roadmap — DAEDELUS intake, categorization, repair automation, survival

**Authored:** 2026-08-25 (ATHENA cycle `2026-08-25-0052`) · **Decision
record:** `docs/adr/0002-daedalus-sovereign-workshop.md` · **Executor of
record:** DAEDELUS lane; mechanics via @hermes; critique via @reviewer for W2/W4.

Sequencing law inherited from `expansion-stability-roadmap.md` §4:
**stability work precedes expansion work.** No W-phase starts while fleet CI
is red or main is diverged.

## Interface contract — plan letter (`fleet.plan` on topic `updates`)

Field/type/required per letter envelope v1 `{v, id, ts, from, to?, topic?,
kind, rights, payload, error}`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `v` | 1 | yes | envelope version |
| `id` | string | yes | unique letter id |
| `ts` | number | yes | epoch seconds |
| `from` | string | yes | producer organ or `"operator"` |
| `to` | `"daedalus"` | yes | sovereign routing |
| `topic` | `"updates"` | yes | existing topic set |
| `kind` | `"fleet.plan"` | yes | NEW catalogue row + kind constant |
| `rights` | profile name | yes | validated by buskit (unknown → rejected) |
| `payload.plan_id` | string | yes | correlation id for outcomes |
| `payload.title` | string | yes | human-readable |
| `payload.spec.blueprint` | string? | no | exact blueprint name for E1 |
| `payload.spec.name` | string | yes | artifact slug |
| `payload.spec.faults` | string[] | no | named fault injection |
| `payload.priority` | `"now"\|"queued"` | no | default `queued` |

Example — valid E1 commission:

```json
{"v":1,"id":"pl-0007","ts":1771998000,"from":"operator","to":"daedalus",
 "topic":"updates","kind":"fleet.plan","rights":"watcher",
 "payload":{"plan_id":"P-2026-0031","title":"kv mirror worker",
            "spec":{"blueprint":"kv-store","name":"kvmirror-01"},
            "priority":"queued"},"error":null}
```

Example — error path (unknown blueprint ⇒ classified reject, outcome letter
carries non-empty `error`, original quarantined to `data/plans/quarantine/`):

```json
{"error":"plan P-2026-0032 rejected: no blueprint matches 'warp-drive'; staged as E2 candidate",
 "result":{"plan_id":"P-2026-0032","disposition":"e2-candidate"}}
```

## Phases

### Phase W0 — Fleet green precondition (owner: hermes + operator)
- Goal: restore the stability base so expansion is lawful.
- Files: none in daedalus.
- Steps: resolve divergence (land local `23128e2` sentinel H0a over upstream
  `05b5723`,`4d024b6`; rebase, push via auto/* PR); dispose dirty poseidon
  lane (`poseidon/heal.py` untracked vs upstream L034 tree-repair — dedupe or
  quarantine); confirm self-hosted runner `earth949-d` completes a full green
  ecosystem job; `python doctor.py --ci` green locally post-merge.
- Acceptance: one full green push-run on main; clean tree; 0 ahead/behind.
- Rollback: n/a (no product change).
- Risk: Medium — runner is a single box.

### Phase W1 — Identity + port discipline (owner: daedalus lane)
- Goal: isolation hardening; attestation quality.
- Files: `daedalus/server.py` (drop `port += 1` fallback → raise;
  optional `who` handshake field), `daedalus/verify_daedalus.py`
  (new checks: bind-fail raises; witness line contains caller).
- Verification: `python daedalus/verify_daedalus.py`.
- Acceptance: occupying :43905 makes startup FAIL loudly; witness records
  `who` when present; all prior gates stay green.
- Rollback: revert commit. Risk: Low.

### Phase W2 — Intake + journal + kill switch (owner: daedalus lane; reviewer critique first)
- Goal: all plans enter as `fleet.plan` letters; journaled before execution.
- Files: `buskit/envelope.py` (+1 kind), `INTEGRATION.md` §6 row,
  `daedalus/content.py` (`INTAKE_ENABLED`, paths), new `daedalus/intake.py`
  (claim loop, WAL journal `data/plans/inbox.jsonl`, backpressure ceiling,
  quarantine dir), `daedalus/kernel.py` (boot replay of unbuilt plans),
  `relay/bridge.py` (forward plan letters), verify suites both lanes.
- Verification: `python verify_buskit.py`; `python relay/verify_relay.py`;
  `python daedalus/verify_daedalus.py`.
- Acceptance: kill-switch off = zero behavioral change; on = letters claimed,
  journaled pre-execution, replay after forced restart, backlog ceiling
  rejects with error, malformed letters quarantined.
- Rollback: flag off + revert. Risk: Medium (bus contract) → reviewer gate.

### Phase W3 — Blueprint taxonomy + categorizer v0 (owner: daedalus lane)
- Goal: every incoming plan lands E1 / E2 / E3 / reject deterministically.
- Files: `daedalus/blueprints.py` (category/tags metadata),
  `daedalus/intake.py` (rule-based classifier), `daedalus/rules.py`
  (category rules as data), knowledge drop-in
  `knowledge/daedalus/daedalus.json` (searchable catalog).
- Verification: suite + `python knowledge/verify_knowledge.py`.
- Acceptance: classifier table-driven; every blueprint categorized; unknown
  spec shapes never crash the pump (reject path only); catalog searchable.
- Rollback: revert. Risk: Low-Medium.

### Phase W4 — Automated repair pipeline (owner: daedalus lane; reviewer critique first)
- Goal: sentinel remediation and doctor fix sweeps flow through the workshop;
  proof published on every fix claim.
- Files: sentinel remediation hook (emit `fleet.plan` repair letters),
  `daedalus/intake.py` (repair disposition), outcome publisher
  (`fleet.repair` letters with proof hash), relay forwarding unchanged.
- Verification: full ecosystem suite; incidents ledger shows repair entries
  with proofs.
- Acceptance: no "fixed" claim without attached gate-green proof; repair
  storms hit warden quarantine + retry ceilings (bounded, L013/L017).
- Rollback: revert. Risk: Medium-High blast radius → reviewer + operator sign-off.

### Phase W5 — Survival drill (owner: daedalus lane)
- Goal: prove the arrangement survives process death, port capture, poison input.
- Drill script (added to verify suite): kill workshop mid-backlog → restart →
  replay completes; occupy :43905 → loud failure + doctor finding; inject
  malformed plan → quarantine, pump unaffected; pulse heartbeat gap → revive tick.
- Acceptance: all four drills pass; `python -m learning report` mines any
  incident into proposals.
- Rollback: n/a (tests). Risk: Low.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Privilege concentration invites silent scope creep | Medium | ADR constraint points; reviewer on W2/W4; ledger audits |
| Self-hosted runner single point of failure | Medium | W0 acceptance requires green run; keep hosted-runner fallback config commented in ci.yml |
| Categorizer misroutes real work | Medium | table-driven rules + reject-not-crash + quarterly prune |
| Repair storm loops | Low-Medium | warden quarantine, retry ceilings, incidents ledger |
| Journal corruption | Low | same append+lock pattern as audit chain; replay skips bad tail loudly |

## Operator decisions outstanding

1. Confirm Option C and both ADR constraint points (§6 of ADR 0002).
2. Poseidon `heal.py`: dedupe against upstream L034 tree-repair or park it?
3. Redundancy plan for runner `earth949-d` (survival of W0 itself).
