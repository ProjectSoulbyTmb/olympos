# Yggdrasil - Architecture

Protective and operational ecosystem for the Soul fleet.

## The ecosystem

| System | Path | Role |
|---|---|---|
| **ZEUS** | `zeus/` | Workspace protection kernel: process/integrity/churn patrols, quarantine, circuit breakers |
| **Vulcan** | `vulcan/` | Offline smart-building automation sandbox with self-healing warden |
| **Hades** | `hades/` | Provenance realm: fingerprinting, watermarking, lineage audit |
| **GAIA** | `gaia/` | Ecosystem health kernel: vitals collection, scoring, alerts (Node) |
| **THOTH** | `thoth-private/` | Operator-kernel modules: grants/safety, knowledge routing, scribe, stabilizer |
| **PTAH** | `ptah/` | Software-engineering agent kernel: event-sourced agent loop, audited tools, security classes, skills, REST API (43903), CLI |
| Toolkit | `image-toolkit/` | Shared image-processing toolkit (Node) |

Infrastructure: `doctor.py` (stabilization gate), `sentinel.py`
(continuous watchdog + incident ledger), `register-*.ps1` (Scheduled
Task installers), `.github/workflows/` (CI gates, tag-driven releases).

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
- Ports: Vulcan owns 43901, ZEUS 43902, PTAH 43903 (see `zeus/content.py`).
- Data dirs (`zeus/data/`, `data/`) are gitignored runtime state.
- CI (`ci.yml`) runs GAIA tests, Vulcan/ZEUS/Hades verify gates, then
  `doctor.py --ci`. Releases tag off `v*` and package the snapshot.

## Decision log

- 2026-08-24: Added the PTAH realm (`ptah/`) - a software-engineering
  agent kernel in the OpenHands class, rebuilt to house rules: pure
  standard library, event-sourced conversations (JSONL replay),
  Action/Observation tools behind a risk classifier with grant-class
  mapping (SAFE/ELEVATED/DESTRUCTIVE/DENIED -> L0/L1/L2/DENY), human
  confirmation gating that re-arms after every privileged action,
  keyword-triggered knowledge cards encoding fleet conventions, a
  provider-agnostic LLM brain over urllib (OpenAI-compatible +
  Anthropic) plus an offline ScriptedLLM for deterministic tests/demo,
  a loopback REST control plane on port 43903, and `python -m ptah
  selfcheck` automation (nightly via register-ptah-task.ps1). Gate:
  `python ptah/verify_ptah.py` (15 scenario checks + full unit suite);
  wired into doctor, sentinel and CI.
- 2026-08-24: Removed the retired game-simulation realm (tick-based
  world sim, self-play RL combat agent, authoritative game server,
  live-market data updater and its clients) from the workspace. The
  product identity had already moved to Yggdrasil; now no
  game-simulation code or third-party game naming remains anywhere in
  the fleet. Remaining realms (ZEUS, Vulcan, Hades, GAIA, THOTH) are
  unaffected; sentinel/doctor gates updated to cover exactly the
  surviving suites.
