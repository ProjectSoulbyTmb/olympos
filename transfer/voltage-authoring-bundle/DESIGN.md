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

- 2026-08-24: **RILEY work stream** (`relay/riley_stream.py`): the third RELAY crossing - workshop-to-studio. Every 'nymph-hunter' verdict DAEDELUS publishes is consumed under its own seq cursor ('riley') and streamed into RILEY's loopback job queue as a seeded img.art proof card: one card per gate-green nymph, a witness pair when she ships blind, one signature style per nymph, seeds sha256-derived from the workshop job id so duplicate delivery renders identically (idempotent). Crash-tolerant via a pending/sent/rejected spool under assistant/data/relay/riley/ - a dark studio parks orders silently and retries each cycle; permanent refusals file without retry storms. New `fleet.render` kind registered in the buskit catalogue + INTEGRATION.md row; outcomes broadcast on `updates` + venus mailbox. PERSEPHONE respect: loopback HTTP POSTs to RILEY's public API only - its SPA surface - never touching D:\riley files or %LOCALAPPDATA%\RILEY state. CLI: `python -m relay riley [--status]`; wired into Relay.run_cycle so the existing 'Olympos RELAY Bridge' daemon streams automatically. Gate: `python relay/verify_relay.py` (11 checks incl. stub-studio seams R6-R8).


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

- 2026-08-25: **ADR-0002 accepted — DAEDELUS sovereign workshop.** Operator
  confirmed single-intake architecture (all building plans enter as journaled
  `fleet.plan` letters, classified E1/E2/E3/reject before bounded autonomous
  execution) and both constraint points: the core-ladder `grant` meta-right
  stays out of DAEDELUS's reach, and E3 realm promotion keeps operator
  sign-off. Formalized standing tier: registry profile admin +
  `DAEDALUS_PROFILES["admin"]` (declarative marker; full surface unchanged).
  W1 isolation hardening landed (fail-loud port bind, caller `who` in
  witness attestation). Survival mechanisms per roadmap W5 pending.

- 2026-08-25: **ADR-0003 accepted — VOLTAGE is the Studio Creative
  Control OS.** First artifact shipped via muster: blueprint
  `apollo-os` (command plane: grammar/rights-law/sessions/dispatch/
  witness/seals), registered as `apollo-os`, gate green plus all four
  injected breakers proven to bite (`tools/muster_launch.py`).
  Contract: `docs/contracts/voltage-command-spec-v1.md`; roadmap V6-V9
  appended. Test launches stay inside throwaway weave dirs — no
  registry/bus/doctor wiring until ADR-0002 V2 commissions at
  `D:\VOLTAGE`. Lesson encoded in the blueprint: woven gates carry a
  bounded readline watchdog and runners a tree-kill fallback so a
  silenced banner can never hang or orphan a build lane.

- 2026-08-25: **Batch V7 studio tier authored and proven.** Five new
  blueprints registered (`kinema-host`, `riley-bridge`, `media-lane`,
  `ent-composer`, `game-domain`); full muster matrix green — six clean
  gates, five breakers confirmed. APOLLO gained the drop-in extension
  protocol (`apollo_ext_<domain>.py`): adapters override builtin
  doubles at dispatch while the rights ladder, witness line and seal
  law apply unchanged — proven by the apollo-os gate driving an
  extension mutation through the witness path and refusing an L0 leak.
  Two lessons encoded in the blueprints: (1) jail functions must test
  absoluteness BEFORE stripping leading slashes, else `/abs` becomes
  `abs`;   (2) containment gates assert NAMED refusal reasons — when one
  guard dies, defense-in-depth must not mask it from the proof
  (caught live: the hidden-entry guard silently covered for a gutted
  traversal guard until refusals were required to name themselves).

- 2026-08-25: **Batch V8 mind tier authored and proven.** Four new
  blueprints registered (`know-gateway`, `learn-gateway`,
  `muse-curriculum`, `voltage-tasks`); muster matrix green — four
  clean gates, four breakers confirmed. The promotion valve is now
  executable law: an L2 session without an operator sign-off file
  refuses by name, and the `auto_promote` breaker proves the gate
  dies if that check is gutted. Muse ships in the knowledge organ's
  auto-discovery shape so commissioning is a file drop, not a wiring
  job; its loader refuses to serve a corpus that fails convention
  validation. Task installers carry boundary hygiene IN TEXT
  (`voltage-*` names only; OneDrive/Olympos references are lint
  refusals before installation). Blueprint-authoring lesson bank
  grew twice: nested template strings need per-layer escape
  accounting (outer `\n` weaves a real newline; outer `\s` warns),
  and semantic anchors (expected top-hit ids on tie queries) make
  ranking drift observable where structural equality checks cannot.

- 2026-08-25: **Batch V9 authored and proven — blueprint stack
  complete.** Four hardening blueprints registered (`ops-domain`,
  `session-seal`, `sla-pulse`, `voltage-packager`); muster matrix
  green, four breakers confirmed. Executable law added: privileged
  ops verbs run on single-use ConfirmTokens — a spent token refuses
  by name ("one acknowledgment, one action") and the sticky_confirm
  breaker dies if re-arm is gutted; seal chains link each entry to
  its predecessor so deleting a middle entry fails verification AT
  THE GAP even with forged length/tip metadata (weaken_link breaker);
  SLO quarantine/revival runs on injected clocks only (slo_blind
  breaker); release packaging refuses version drift BY NAME showing
  both numbers (version_blind breaker). Fourteen blueprints now span
  command, studio, mind, and hardening tiers; every B1–B10 criterion
  has an executable proof or an explicitly commissioning-bound gate.
  VOLTAGE authoring is COMPLETE on the Olympos side; what remains is
  ADR-0002 W0/V2 commissioning at D:\VOLTAGE.

- 2026-08-25 (evening): **Commissioning assist — sovereign pipeline
  driven green through C1 choke.** Disk truth check found D:\VOLTAGE
  already commissioned by a parallel lane (Daedalus promoted to
  Upgrade Coordinator per ROLE.md; ops/coordinator.py manifest pump).
  Exporter stood down — overwrite refused by design. Resumed the
  stuck pump instead and drove every executable order GREEN
  (smoke-0, A1-A3, B1-B6; C1 choke-holds for operator --allow-c).
  Four sovereign-side repairs landed in VOLTAGE's own files, each
  evidence-backed: (1) norn gate gained the Skip state — vulcan-
  integration checks sanction-skip where vulcan is deliberately
  unseeded; (2) gate ceilings became per-blueprint law
  (gate_timeout_s; default 120s, echo starvation proofs 45s,
  voltage-ops matrix 480s) ending the 60s-vs-minutes war that made
  coordinator red while orphaned gates wrote green evidence;
  (3) boundary jail gained its designed temp-sandbox exemption at
  the single arming point (coordinator exports VOLTAGE_JAIL_EXEMPT)
  plus GIT_CONFIG_GLOBAL=bootstrap/gitconfig so scrubbed-env git
  stops refusing freshly minted scratch repos as dubious ownership;
  (4) gaia test invocation fixed to address the real test file and
  sentinel's infra-gate list trimmed to actual seeded membership.
  Lesson of the session: nested timeout ceilings must be declared
  per workload, never shared; and an armed jail without its
  sanctioned-lane exemptions turns every test suite's scratch space
  into foreign soil.

- 2026-08-25 (night): **Creative Control OS promoted into VOLTAGE —
  V6 commissioned.** Operator granted full authorization; the
  blueprint stack crossed via organ/incoming + two new pump orders
  (P1 promote-with-digest-proof, P2 commission-apollo with live
  :44120 bind probe). APOLLO's gate is green AT THE SOVEREIGN ROOT;
  registry carries apollo/kinema-host/riley-engine rows; ratatosk
  gained the command-plane catalogue block; muse ships conforming to
  the knowledge organ's REAL law (7 mandatory entry keys, MUSE-###
  ids, https sources, titled prose doc) — the organ itself was
  seeded alongside, verify 7/7. Sentinel: 13/13 gates green at root.
  Blueprint-authoring lesson bank, final entries: (a) never anchor
  an edit on a def line without re-emitting that line — three
  separate swallows tonight; (b) triple-quote sequences inside a
  woven template terminate the outer string — build nested text via
  "\n".join lists; (c) gates must be cwd-self-locating or sentinel
  derivation strangles them. Remaining for full V6-V9: studio
  engine backends behind their proven seams (binaries/weights),
  doctor SUITES apollo entry (optional beyond sentinel), V5 soak.


