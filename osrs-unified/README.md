# osrs-unified

Merged workspace combining two OSRS research projects. Local simulation only —
nothing here touches the real game or any Jagex service.

| Sub-project | What it is | Entry points |
|---|---|---|
| **Skilling LLM agent** | LLM strategic agent that plays a simplified OSRS-style skilling MMO by writing and executing its own strategy code, grounded in live GE prices + Wiki data | `bench.py`, `tools/update_knowledge.py` |
| **PvP RL** | Self-play PPO agent for tick-based OSRS-style melee PvP, trained in a local simulator with real OSRS combat formulas | `train.py`, `evaluate.py` |

Original per-project docs live in `docs/`.

## Layout

```
bench.py                 [skilling] CLI: tasks, manual mode, LLM mode, scoring
agent/                   [skilling] LLM client, orient->prompt->exec->score loop, sandboxed runner
game/                    [skilling] MIND kernel (event bus + tick scheduler), world, SDK, market, knowledge
server/                  [skilling] socket server exposing the sim (RSPS-style), supervisor
strategies/              [skilling] example bots / manual-mode baselines
wiki/                    [skilling] hand-written KB for sim mechanics
knowledge/               [skilling] OSRS ground truth fetched from official APIs
tools/update_knowledge.py [skilling] knowledge ingestion pipeline

train.py                 [pvp-rl] self-play loop: learner vs opponent pool + RandomBot
evaluate.py              [pvp-rl] W/D/L report vs heuristic / random / past checkpoints
algo/                    [pvp-rl] MLP actor-critic with action masking; PPO buffer + update
envs/osrs_sim.py         [pvp-rl] simultaneous-turn 1v1 melee environment
rsps_adapter/            [pvp-rl] gym-over-socket adapter for real private-server training

runs/                    shared results dir: skilling sessions/loop state + pvp checkpoints/logs
docs/                    original READMEs of both projects
```

The two halves share no packages (`agent/game/server` vs `algo/envs/rsps_adapter`),
so they coexist without collisions.

## MIND - autonomous moderator & software engineer

`mind/` turns the MIND kernel concept into a standing automation layer:

| Role | What it does |
|---|---|
| **Moderator** | patrols world integrity (XP table, prices), quarantines corrupt sessions to `runs/_quarantine/`, watches knowledge freshness, audits best-scores |
| **Engineer** | runs the test suite, classifies failures via heuristics, applies safe self-healing, optional `--llm` AI diagnosis saved to `mind/proposals/` |
| **Releaser** | bumps version, writes changelog from git history, commits + tags, builds wheel/sdist + `OSRS-Suite.exe`, produces the release zip |

```powershell
osrs mind status                      # full report -> runs/mind_status.json
osrs mind patrol                      # moderator sweep + engineer tests/heal
osrs mind patrol --loop 60            # stay resident, patrol hourly
osrs mind patrol --llm                # + local LLM diagnosis on odd failures
osrs mind update-data                 # refresh GE/wiki ground truth
osrs mind release --level minor       # automated version bump + build + zip
osrs mind release --dry-run           # preview only
osrs mind install-tasks               # register Windows scheduled tasks
```

Every action is logged to `runs/mind_log.jsonl`; latest state in
`.mind_state.json` and `runs/mind_status.json`.

## MIND engineering engines

| Engine | Module | Role |
|---|---|---|
| Moderator | `mind/moderator.py` | world integrity, session quarantine, data freshness |
| Engineer | `mind/engineer.py` | test runs, failure diagnosis, AI proposals |
| Releaser | `mind/releaser.py` | semver bump, changelog, commit/tag, artifacts |
| Builder | `mind/builder.py` | compile sweep, wheel/sdist, exe build + selftest |
| Knowledge | `mind/knowledge_engine.py` | GE/wiki refresh, **OSRS revision parity** (XP table vs canonical, upstream update detection) |
| Healer | `mind/healer.py` | playbook self-repair (corrupt state/dirs/tmp/sessions) with post-fix test verification |
| Scheduler | `mind/scheduler.py` | interval job table (`schedule add/tick`) |
| Metrics | `mind/metrics.py` | snapshots + score trends (`runs/metrics.jsonl`) |
| Sentinel | `mind/sentinel.py` | anomaly alerts (score collapse, stale exe) onto bus |

One command runs the whole loop:

```powershell
osrs mind autonomic            # patrol -> heal -> parity -> tests ->
                               # sentinel -> release-if-green
osrs mind autonomic --dry-run  # plan only
```

## MIND <-> Thoth relay

Durable event bus (`runs/osrs_bus/`, spool+archive) connecting this repo's
automation kernel with the external **Thoth** JS kernel:

- every LLM session auto-publishes `mind.briefing` (prompt-injected) and
  `thoth.result.run` (score/errors); AI patch proposals emit `thoth.proposal`
- patrols broadcast `mind.status`; jobs (`mind.job.*`) are pumped by
  `osrs mind relay pump --execute`, which runs bench LLM sessions or
  test+diagnose cycles and archives outcomes
- Thoth-side adapter: `bridge/thoth-relay.js` (mirrors `thoth:event`
  emissions onto the bus; see `bridge/README.md` for the full catalog)

## Windows application

`OSRS-Suite.exe` (project root) is a native Tkinter GUI wrapping everything:

- **Skilling Bench** tab — pick task, tick budget, manual strategy file or
  LLM mode (Ollama/OpenAI-compatible settings), run with live console output
- **PvP RL** tab — start/stop self-play training (`--fast`, resume) and
  evaluate checkpoints
- **Knowledge** tab — one-click GE+Wiki refresh with data-age status

Jobs stream into a shared console; **Stop job** kills the whole process tree.
The exe delegates heavy work to an installed Python (auto-detected), so keep
it in the project folder next to `bench.py`. Alternatives:
double-click `Launch OSRS Suite.bat`, or `pythonw osrs_app.py`.
Rebuild the exe: `pyinstaller --onefile --noconsole --name OSRS-Suite osrs_app.py`.

## Quick start

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

# --- skilling agent ---
& $py bench.py --task wc_xp --code-file strategies\example_bot.py   # baseline, no LLM
& $py tools\update_knowledge.py                                     # refresh GE prices + wiki KB
& $py bench.py --task uim_total_xp --rounds 8 `
    --base-url http://localhost:11434/v1 --model llama3.1:8b        # LLM mode via Ollama

# --- pvp rl ---
& $py train.py --name v3 --iters 200 --episodes 40                  # train from scratch
& $py train.py --name v2 --iters 200 --episodes 40 --resume         # continue runs\v2
& $py evaluate.py runs\v2\ckpt_latest.pt                            # W/D/L report
```

LLM config falls back to env vars: `LLM_BASE_URL` (default local Ollama),
`LLM_MODEL`, `LLM_API_KEY`. Any OpenAI-compatible endpoint works.

## Tasks & scoring

Skilling: `wc_xp`, `gold`, `total_xp`, `cook_xp`, `uim_total_xp`
(Ultimate Ironman — bank locked, manage 28 slots). Scoring reports total XP,
per-skill breakdown, net coins, peak XP rate, final levels.
See `docs/README-skilling-agent.md`.

PvP: PPO (clip 0.2, GAE, opponent pool snapshots every 10 iters) over real
OSRS hit/defence roll formulas, food/prayer/movement on a 1D tile line.
See `docs/README-pvp-rl.md`.

## Notes

- Skilling sessions are checkpointable: `--save-every N` then `--resume runs\<task>\session.json`.
- PvP training resumes fully (model+optimizer+pool): `--resume` on the same `--name`.
- The snippet sandbox blocks imports/file/network in executed strategy code —
  accident-proofing, not a security boundary.
