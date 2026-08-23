# Changelog

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
