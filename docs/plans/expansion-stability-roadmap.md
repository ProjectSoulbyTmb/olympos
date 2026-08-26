# Olympos - Continual Expansion, Stability & Full Operation

**Authored:** 2026-08-24 · **Executor of record:** DAEDALUS (workshop, :43905)
**Companion docs:** `STRATEGY.md` (direction), `INTEGRATION.md` (model of
record), `DESIGN.md` (what the architecture is)

## 1. Goal

The ecosystem becomes - and stays - an expanding, stable, fully
operational system/database:

| Property | Engine | Proof |
|---|---|---|
| Expanding | DAEDALUS blueprint pipeline + registry intake | new members land gate-green, sealed, registered |
| Stable | verify suites -> doctor -> sentinel -> CI | no health claim without its gate passing |
| Fully operational | fluid workshop (pump/lanes) + norn.pulse + ratatosk bus | builds drain unattended; every organ answers on its port |

Baseline proven 2026-08-24: audit chain ok (242 entries), warden 0
findings, 4 lanes idle, and two fresh commissions sealed green on first
attempt -

- `expansion-pulse-13fcce` (beat-worker) sha256 `047a0563...b0a65f26`
- `expansion-db-607dba` (kv-store)   sha256 `3224979c...1486fef16`

## 2. Standing principles (inherited, binding)

1. The five guarantees hold for every new member (deterministic replay,
   attested mutation, least privilege, atomic bus delivery, gated health
   claims). A design that weakens one is invalid by default.
2. Autonomy is bounded (playbook pattern 9, L013/L017): bounded loops,
   persisted state, capability checks, quarantine over destruction,
   judgment calls escalate to the operator.
3. Growth never bypasses shipping protocol (FLOW.md): private worktree
   -> auto/* branch -> squash PR; direct pushes to main are hook-blocked.

## 3. The expansion engine (DAEDALUS)

Every act of growth takes one of three shapes, in increasing ambition:

### E1 - Commission an instance (minutes)
`python -m daedalus build --blueprint <name> --name <slug>` weaves in an
ATLAS guest, gates it, repairs by culprit isolation if faults are
present, seals the artifact with SHA-256. Use for workers, oracle
servers, KV stores - anything a blueprint already covers.

### E2 - Add a blueprint (a session)
New reusable design = template files + self-test gate + optional named
faults (`daedalus/blueprints.py`, optional `blueprint_*.py` module).
Acceptance: `build` green with zero faults, green again after injecting
each declared fault (proves repair convergence), artifact seals.

### E3 - Register a realm (operator sign-off required)
Promotion into the tracked fleet requires ALL of:
1. verify suite discoverable by convention (`<realm>/verify_<realm>.py`)
2. `realms/registry.json` row: tier, lang, verify, profile, publishes/
   consumes annotated
3. port allocation recorded (registry AND DESIGN.md; squatter check
   generalizes)
4. DESIGN.md ecosystem-table entry + decision-log row
5. cross-organ topics get catalogue rows + kind constants (INTEGRATION §6)

Adding a member must cost exactly these declarations - no edits to
doctor/sentinel/GAIA loops (they derive from the registry).

## 4. The stability engine

Layered, each layer cheap and always-on:

| Layer | Mechanism | Failure posture |
|---|---|---|
| Build gate | blueprint self-test in ATLAS guest | fix pass -> retry ceiling -> quarantine |
| Suite gate | `verify_*.py` per realm, auto-discovered | FAIL lands in incidents ledger |
| Watchdog | `sentinel.py --watch N`: remediate -> gates -> ledger | lane cooldown, subsystem revive ticks |
| Baseline | `doctor.py` (compile/port-squatter/baseline, `--ci`) | red CI blocks merge |
| Pre-commit | safeguards hook path | bad commits never enter main |
| Fleet health | GAIA vitals -> score 0-100 -> alerts | scoring reads the ledger, not re-probes |

Rule: **stability work precedes expansion work.** A red gate freezes new
commissions until remediated or quarantined - expansion on a sick base
compounds defects.

## 5. The operations engine

- Workshop pump keeps lanes saturated (`pump_start`) so queued builds
  drain without hand-cranking; lane cooldowns absorb flaky guests.
- Periodic work registers with norn.pulse (never invents its own timer):
  SLOs, quarantine, revive. Node-side organs follow Venus heart.js.
- Every organ speaks the letter envelope v1 over its registered port;
  every response carries `error`; delivery is atomic `os.replace`.
- Audit trails stay hash-chained (rule 16); rotation at size cap.

## 6. Roadmap (continues STRATEGY Phases 0-1, now landed)

Registry v2 supersedes the proposed `fleet.json`; Phases 0-1 are
effectively complete (registry-derived gates live). Next:

### Phase R1 - Coverage completion (near-term)
- [ ] Optional informational gates for remaining T3 satellites wired
      through the registry (skip-green when dark, contract check when
      live) - pattern already proven by `verify_riley_satellite.py`.
- [ ] Doctor squatter sweep generalized across every registered port.

### Phase R2 - Provenance loop (Hades earns its keep)
- [ ] Hades fingerprints DAEDALUS-sealed artifacts into a machine-
      readable manifest shipped with each release tag.
- [ ] SBOM checklist promoted to all T2+ products.

### Phase R3 - Self-expanding backlog (the flywheel)
- [ ] Learning subfleet proposals (metis drift finds, logia patterns)
      graduate into E2 blueprint candidates; each accepted candidate
      becomes a commissionable design.
- [ ] `knowledge/engine.py` indexes new product DBs automatically by
      convention (`knowledge/<name>/<name>.json`) - drop-ins searchable,
      no rebuild. Grow the database by dropping well-formed JSON.
- [ ] Quarterly: prune blueprints whose gates rot (warden findings > 0
      twice consecutively) - deprecate, don't delete.

### Phase R4 - Release engineering (from STRATEGY Phase 4)
- [ ] Tag-driven releases: fingerprint step + doctor `--ci` green +
      changelog/version consistency lint.

## 7. Cadence

| Loop | Trigger | Output |
|---|---|---|
| Commission (E1) | on demand | sealed artifact + audit entry |
| Learning cycle | scheduled / `learning-cycle.ps1` | <=N proposals per subfleet agent |
| ATHENA planning cycle | operator request / drift report | this document's successor + ADRs |
| Sentinel watch | continuous | incidents ledger, remediations |

Operator sign-off points: realm promotions (E3), lessons.json appends,
any guarantee-weakening change (ADR required).

## 8. Risks & non-goals

Inherit `STRATEGY.md` §5-§6 wholesale (no simulation revival, local-first
core, stdlib-only Python realms). Addition:

| Risk | Mitigation |
|---|---|
| Blueprint sprawl outpaces gate maintenance | R3 quarterly prune; warden findings feed the queue |
| Expansion during red fleet health | stability-freeze rule (§4) |
| Unbounded autonomous growth | autonomy bounds (§2.2); every loop has a ceiling and a ledger |
