# Yggdrasil - Architecture

Protective and operational ecosystem for the Soul fleet, converging on
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
  the public domain and the ecosystem took the name Yggdrasil. Public
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
