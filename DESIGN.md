# Olympos - Architecture

Protective and operational ecosystem for the Project Olympos fleet, converging on
one goal: a fully autonomous, open-source game and app development
platform (see `INTEGRATION.md`).

## The ecosystem

| System | Path | Role |
|---|---|---|
| **ZEUS** | `zeus/` | Workspace protection kernel: process/integrity/churn patrols, quarantine, circuit breakers |
| **Vulcan** | `vulcan/` | Offline smart-building automation sandbox with self-healing warden; proving ground for autonomous build loops |
| **Hades** | `hades/` | Provenance realm: fingerprinting, watermarking, attestation seals, lineage audit |
| **GAIA** | `gaia/` | Ecosystem health kernel: vitals collection, scoring, alerts (Node) |
| **THOTH** | `thoth-private/` | Operator-kernel modules: grants/safety, knowledge routing, scribe, stabilizer |
| **PTAH** | `ptah/` | Software-engineering agent kernel: event-sourced agent loop, audited tools, security classes, skills, REST API (43903), CLI |
| **Ratatosk** | `ratatosk/` | Filesystem communication network: atomic mailboxes (`data/post/`), correlated replies, priority lanes, topics with cursors, heartbeats, corrupt-letter quarantine. Stdlib-only; no ports, no daemons |
| **NORN** | `norn/` | Accountability machinery: Clockwork determinism seam, replay seeds, capability-rights profiles, witness journals, pulse SLOs |
| **Hypnos** | `hypnos/` | Silent task organ: letter/drop-in claim-run-retry-resume with audited actions and crash recovery |
| Toolkit | `image-toolkit/` | Shared image-processing toolkit (Node) |

Infrastructure: `doctor.py` (stabilization gate), `sentinel.py`
(continuous watchdog + incident ledger), `buskit/` + `verify_buskit.py`
(message contracts), `verify_scope.py` (retired-scope guard),
`realms/registry.json` (endpoint registry), `register-*.ps1`
(Scheduled Task installers), `.github/workflows/` (CI gates,
tag-driven releases).

## Hard rules

1. **Verify before claiming health.** Every realm ships a verify suite
   (`verify_*.py`, npm tests); doctor and sentinel run them all.
2. **Fail safe.** Protection kernels (ZEUS) never auto-run destructive
   actions; mutations go through grant classes (L0 read-only, L1
   standing grant, L2 elevated).
3. **Local-first.** Everything runs offline against local state; no
   external service dependency for core functionality.
4. **Idempotent repairs only.** Doctor/sentinel remediations are safe,
   byte-exact rollback-able operations - never improvised rewrites.

## Conventions

- Python realms are standard-library only; Node realms pin deps in
  their own package.json. Root `requirements.txt` stays empty unless a
  realm gains third-party imports (doctor checks coverage).
- Ports: Vulcan owns 43901, ZEUS 43902, PTAH 43903; realm endpoints are
  declared once in `realms/registry.json`.
- Data dirs (`zeus/data/`, `data/`, `ptah/data/`) are gitignored
  runtime state.
- CI (`ci.yml`) runs the GAIA tests, per-realm verify gates, then
  `doctor.py --ci`. Releases tag off `v*` and package the snapshot.

## Decision log

- 2026-08-23: Trademark-hygiene rebrand: public product names moved to
  the public domain and the ecosystem took the name Olympos. Public
  marks stay retired; internal naming follows the current scope policy
  below.
- 2026-08-23: Vulcan added with the house contract - all numbers in
  `content.py`, authoritative JSON-lines server with an `error` field
  on every response, one SDK surface for in-process and wire clients,
  versioned saves carrying the full ruleset, own verify gate. The
  warden auto-repairs waste, runaway duty, stuck sensors and vacant
  lights, trips rule circuit breakers, sheds load under escalation,
  and recovers corrupt saves from rotating backups.
- 2026-08-23: Ratatosk accepted as the shared filesystem bus (later
  gaining correlated replies and priority lanes) and NORN as the
  accountability layer (Clockwork seeded time+chance, replay seed
  files with named invariants, Mach-style capability profiles checked
  server-side, append-only witness journals, pulse SLO
  quarantine/revival). The realms registry became the single
  declarative home for endpoints.
- 2026-08-24: Added the PTAH realm (`ptah/`) - a software-engineering
  agent kernel in the OpenHands class, rebuilt to house rules: pure
  standard library, event-sourced conversations (JSONL replay),
  Action/Observation tools behind a risk classifier with grant-class
  mapping (SAFE/ELEVATED/DESTRUCTIVE/DENIED -> L0/L1/L2/DENY), human
  confirmation gating that re-arms after every privileged action,
  keyword-triggered knowledge cards encoding fleet conventions, a
  provider-agnostic LLM brain over urllib plus an offline ScriptedLLM
  for deterministic tests/demo, a loopback REST control plane on port
  43903, and `python -m ptah selfcheck` automation. Gate:
  `python ptah/verify_ptah.py`; wired into doctor, sentinel and CI.
- 2026-08-24: Removed the retired game-simulation realm from the
  workspace. No simulation code or third-party game naming remains
  anywhere in the fleet. Gates retargeted at exactly the surviving
  suites.
- 2026-08-24: Platform goal declared: a fully autonomous open-source
  game and app development platform; Vulcan is the proving ground.
  The workspace was rebuilt as one clean lineage with zero retired-
  scope residue; Hypnos joined as the silent task organ. Infrastructure
  (doctor, sentinel, realms registry, this document) was restored after
  a parallel-session collision, `verify_scope.py` permanently guards
  the naming boundary, and buskit envelope contracts joined the
  watchdog gates.
- 2026-08-24: Build-loop organs online: **Sindri** (`sindri/`) fences
  generated code in a sandboxed forge (taskkill tree-kill default,
  Job-Object fence opt-in via SINDRI_WIN_JOBS); **Forseti**
  (`forseti/`) arbitrates serialised lanes such as the git push lane
  via crash-tolerant stale-reclaiming locks; `buskit.llmlog` journals
  every LLM call as digest evidence (sealable by Hades); new gates
  `verify_secrets.py` and `verify_coverage.py` enforce credential
  hygiene and a buskit coverage floor; `templates/godot-game` plus
  `templates/design-card.json` give codegen its first sanctioned
  target and design-artifact shape; root `VERSION` becomes the single
  version source. All fourteen component suites green under
  `doctor.py --ci`.


- 2026-08-24: System seam proven: root gate `verify_system.py` wires the integration guarantees into one suite - norn.replay records/replays a seeded provisioning session to an identical digest (A4), norn.witness journals every mutating verb incl. refusals (A5), ratatosk broadcast->since() delivers exactly-once with monotonic seqs under catalogue-legal kinds, and the sentinel incidents ledger lints under the buskit envelope contract (A8) with the writer migrated to strict v2 envelopes (legacy v1 lines tolerated forever). Wired into doctor, sentinel and CI.

- 2026-08-24: ATHENA gained a learning-agent subfleet and advanced
  autonomy surface. New agents: metis (lesson miner), argus (drift
  auditor), logia (pattern synthesizer) - each bounded, evidence-
  citing, proposal-only. Shared engine `learning/` gated by
  `verify_learning.py` and registered as a tier-0 knowledge realm.
  Athena's permissions expanded to read-side tooling; her cycles now
  consume the proposal queue, promotion still human-gated. Automation:
  weekly staggered learner tasks via `register-learning-tasks.ps1`,
  full sweep via `learning-cycle.ps1`.


- 2026-08-24: POSEIDON tide kernel landed (`poseidon/`): fully
  autonomous commit-and-push - throwaway-index snapshots of root
  drift carried through `auto/poseidon` (push -> PR -> squash
  merge) under FORSETI's lock, mirror settled only after origin
  holds the content; quarantine breaker after three consecutive
  failures, JSONL tide ledger, Ratatosk announcements. Also repairs
  the dangling Hypnos build gate that referenced this suite before
  the realm existed. Gate: `python poseidon/verify_poseidon.py`.

- 2026-08-24: HEBE completed as the Legal & Document Scribe
  (`hebe/`): full dictation privileges over the workspace (refusing
  only `.git`/`.worktrees` and credential carriers via filename +
  content secret scanners), a codified legal corpus (license catalog
  with canonical MIT/BSD/ISC/Apache/proprietary texts,
  copyright/trade-secret/NDA/trademark/DMCA playbooks), append-only
  oath and IP-register ledgers tracked in `hebe/records/`, LICENSE
  seeding on first boot, inbox drop-in dictation, and her own scoped
  auto-commit/push lane under FORSETI's lock. Standing L2 grant, no
  confirmation gate; quarantine breaker after three failures. Gate:
  `python hebe/verify_hebe.py`; wired into Hypnos build gates, the
  Olympos task bootstrap, and the realms registry.

- 2026-08-24: **Relay** (`relay/`) online: stable DAEDELUS<->VENUS bridges over the ratatosk bus - workshop build outcomes forwarded exactly-once to the venus mailbox + new `updates` topic (fleet.tick/fleet.build/fleet.repair in the buskit catalogue; persistent seq cursors survive restarts and rotation), Venus intents claimed from `assistant/data/relay/to-fleet/` (build -> daedalus CLI commission, repair -> doctor check+fix sweep with published proof, status -> immediate tick), and the constant fleet update stream with per-cycle heartbeat. Deployed as scheduled task 'Olympos RELAY Bridge' via register-relay-task.ps1 + bootstrap wiring; autopilot contract now enforces the daemon, its installer and the task-name sync. Gate: `python relay/verify_relay.py`.


- 2026-08-24: First autonomous build artifact shipped: the godot-game
  blueprint in DAEDALUS weaves a deterministic orb-collector (Godot 4.x,
  Compatibility renderer) whose world is baked at weave time from a
  seeded RNG, so the pure-Python twin is an exact oracle - the self-test
  gate proves determinism, victory, and headless operation. Root gate
  `verify_godot_blueprint.py` wired into doctor and CI auto-discovery.

- 2026-08-24: DESKMATE blueprint added to DAEDALUS for VENUS project
  design assist: weaves a loopback HTTP desk (health, card template,
  strict card validation, deterministic scaffold) callable from any
  Venus panel or PTAH tool; every response carries error. Faults
  no_validation/lost_template exercise gate bite and retry convergence;
  fault injection exposed a stale port.txt race in re-gate passes -
  fixed via pre-boot removal in the woven gate. Root gate
  `verify_deskmate.py` wired into doctor; auto-discovered by CI.
  1964f36 (daedalus: deskmate blueprint - local design-desk service for VENUS (card template/validate/scaffold) + stale-port gate fix)


