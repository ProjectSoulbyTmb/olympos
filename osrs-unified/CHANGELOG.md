# Changelog

## Unreleased

- Skilling world reaches 23 skills: Construction (workshop sawmill -> planks -> furniture, wiki-grounded XP) and Hunter (bird snares at the hunting ground, crimson swift / copper longtail). Save format v6, loads v1-v5 sessions.
- PvP env gains ranged (5 tiles, ammo) and magic (full range, runes) combat styles: 8 actions, 16-dim observations; old checkpoints resume via stored obs_dim/n_actions.
- MIND: fixed unreachable `net serve|gym|send|policy|sources` dispatch (duplicate `net` handler); bare `osrs mind net` still sweeps (`sweep` alias added).
- MIND scheduler now executes every registered job (JOB_RUNNERS incl. new venus-drain default); unwired jobs log `no-runner` instead of silently doing nothing.
- MIND engineer proposal pipeline: `osrs mind propose list|show|apply [--dry-run]`; applies unified diffs from LLM proposals with a clean-tree guard and a test gate that auto-reverts red patches.
- Sentinel watches regression in every runs/*_best.json task file (was wc_xp only); moderator audit broadened to match.
- Releaser pushes commit+tag to origin and publishes a GitHub release with the zip via gh CLI (best-effort, offline-aware).
- Patrol loop is watchdogged (crash streak logging, resident-safe) and drains Venus companion requests each cycle; autonomic includes a venus step.
- Game kernel keeps a bounded recent-event ring (recent_events/export_events), version 1.1.
- MIND gains a Network engineering engine (mind/network.py, osrs mind net): endpoint registry with per-install overrides, DNS + HTTPS reachability probes with retry/backoff, rolling latency baselines with healthy/slow/spike/degraded/down classification, proxy-aware egress detection, offline-mode detection that defers releases in the autonomic loop, heal suggestions, and mind.net.status / mind.net.alert events onto the Thoth bus. Scheduled automatically every 15 minutes.

- osrs-unified: document MIND engineering engines in README
- chore(osrs-unified): stop tracking live mind-daemon runtime state
- osrs-unified: sync live mind-daemon runtime state
- add osrs-unified suite source and v1.0.1/v1.1.0 Windows release zips
- docs: heart autonomic energy + alerting decision log
- DESIGN: Venus heart decision + organ-over-task convention
- tests: sandbox-aware live updater assertions
- market: live_dir param for sandboxed consumers
- gitignore runtime run-state
- Live update stream: livewatch change detection, server live cache + wire cmd, client GE ticker, Venus ge plugin


## 1.1.0 (2026-08-23)

- update README.md
- update osrs_cli.py
- add mind/ 
- add runs/ mind_status.json
- add tests/ test_mind.py


## 1.0.1 (2026-08-23)

- Added native Windows GUI: `OSRS-Suite.exe` (PyInstaller onefile, 10.6 MB),
  `Launch OSRS Suite.bat`, and `osrs_app.py` source
- Tabs for Skilling Bench, PvP RL train/evaluate, Knowledge refresh;
  streaming console, stop-job (process-tree kill), runs-folder shortcuts
- GUI root auto-detection (exe dir / module dir / parent walk / OSRS_ROOT)

## 1.0.0 (2026-08-23)

First unified release of osrs-unified, merging two projects:

- **Skilling LLM agent** (`osrs bench`): MIND-kernel tick sim, manual/LLM modes,
  5 tasks incl. Ultimate Ironman, GE+Wiki knowledge pipeline, checkpoint/resume.
- **PvP RL** (`osrs train` / `osrs eval`): self-play PPO with action masking,
  real OSRS combat formulas, opponent pool, full resume support.

Packaging:
- Installable wheel/sdist; `osrs` console command dispatching to all entry points.
- `OSRS_ROOT` env var redirects wiki/knowledge/runs locations when installed.
- Smoke test suite (`tests/`, unittest-compatible).
