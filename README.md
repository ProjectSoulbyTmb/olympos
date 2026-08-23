# OSRS Lab

A complete, offline, local research sandbox for Old School RuneScape-style
game AI: a tick-based skilling world, a self-play reinforcement-learning
combat agent, an LLM strategic player grounded in live OSRS market data,
and a desktop control hub.

**Scope:** everything runs locally against our own simulation or private
servers you host. It never connects to Jagex services, and it contains no
live-game input automation of any kind.

## Quick start

**Easiest:** run `python runner.py` - an interactive menu that walks you
through every capability with sensible defaults (press Enter to accept):

```
1) Run an activity (sim or RSPS)      5) Host your RSPS server
2) Train combat agent (RL)            6) Refresh OSRS knowledge base
3) Evaluate a trained combat agent    7) Launch desktop dashboard
4) Run the LLM strategic agent        0) Quit
```

Or double-click **`OsrsLab.exe`** (keep it next to the `osrs-llm-agent`
folder) for the GUI hub. From source:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py dashboard.py            # GUI: run activities, watch training curves
```

## Components

| Path | What it is |
|---|---|
| `dashboard.py` / `OsrsLab.exe` | Desktop hub: pick an activity, run it, watch sessions + RL curves live |
| `play_rsps.py` | **Playable game client**: graphical tile world with click/WASD movement, combat, skilling, XP drops - auto-hosts the server if none is running (`python play_rsps.py`) |
| `osrs_updater.py` | Continuous live-data refresher: GE prices (4.5k items), item mapping, wiki update-feed watcher -> `knowledge/live/`. Run `python osrs_updater.py --watch 30` to stay current |
| `MIND kernel /` | Tick-based 6-skill world (woodcutting, mining, fishing, cooking, firemaking, smithing), bank/shop/furnace/quests, Ultimate Ironman mode, pause/resume sessions, LLM strategic loop, GE-price + Wiki knowledge pipeline |
| `osrs-llm-agent/server/` | **Your own RSPS engine**: authoritative JSON-lines game server with per-character instanced worlds + `RemoteGameSDK` client so any strategy runs over the wire unchanged. Original protocol/engine modeled on OSRS mechanics - not interoperable with the official client |
| `osrs-rl/` | Self-play PPO combat agent (200-iteration trained model: 60% win / 7.5% loss vs opponent pool, undefeated vs heuristic & random baselines), resume support |
| `osrs-rl/rsps_adapter/` | Client env + Java relay plugin to train against your own Elvarg private server |

## Feature parity with similar tools

- vs LLM-game-agent benchmarks (runebench-style): same orient-decide-act loop,
  SDK-constrained codegen, error-feedback self-debugging, XP/gold scoring -
  plus persistent session resume and real-market grounding.
- vs RL game environments: standard PPO+GAE+self-play opponent pool,
  action masking, checkpoint/resume, evaluation harness.
- vs MMORPG bot frameworks (OSBot/DreamBot/etc.): those automate Jagex's live
  client, which violates ToS; this project deliberately implements the same
 *classes* of technology (tick engine, pathing, state machines, RL policies,
  human-legible scripting API) inside a legal sandbox instead.

## Rebuilding the exe

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -m pip install -r requirements.txt
& $py -m PyInstaller --onefile --windowed --name OsrsLab `
    --paths "osrs-llm-agent" --hidden-import bench --hidden-import game.world `
    --hidden-import game.sdk --hidden-import agent.llm --hidden-import agent.loop `
    --hidden-import agent.runner --distpath dist `
    --workpath "$env:TEMP\opencode\pyi_build" --specpath "$env:TEMP\opencode\pyi_build" `
    dashboard.py
```

RL training stays CLI-driven (`python osrs-rl/train.py`) because bundling
PyTorch would balloon the exe from ~11 MB to ~1 GB.
