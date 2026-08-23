# OsrsLab - Architecture

This document is the design contract for everything in this workspace.
When code and this file disagree, fix the code.

## The ecosystem

| Product | Path | What it is |
|---|---|---|
| **OSRS Lab** | `osrs-llm-agent/`, `osrs-rl/`, root scripts | Original tick-based game engine (15 skills, 24x24 world), authoritative JSON-lines RSPS server on 127.0.0.1:43590, pygame client (`play_rsps.py`), PPO combat RL, LLM strategic agent |
| **Venus** | `assistant/` (own git repo) | Offline desktop companion: kernel.js event/service/command registries, plugin system, Piper TTS + Whisper STT + Ollama brain |
| **Thoth** | opencode + `~/.config/opencode/` | The development layer itself: agents, skills, permissions. Runs with full automation grants |

## Hard rules

1. **All game data lives in `game/content.py`.** Numbers, items, NPCs,
   spawns, prices, quests. `world.py` contains mechanics only and
   re-exports content names for compatibility. Never re-declare a table
   in a second place.
2. **Server is authoritative.** Clients send intents (`{"cmd": ...}`),
   receive full state. Every response carries an `error` field.
3. **Mechanic numbers come from `knowledge/digest.md` or live sources**
   (`osrs_updater.py` snapshots). Never hardcode from memory.
4. **Offline sandbox only.** Nothing connects to Jagex services; no
   Jagex assets, no copied client/server code.
5. **Save formats evolve by version bump** (`world.save()` version field)
   with load-side defaults for missing keys. Current: v4.
6. **Every behavioral change ships with a verify_system.py check.**
   The suite must reach 17/17 before anything is called done.

## Layer map (OSRS Lab)

```
play_rsps.py (pygame client, rsps_audio.py)
      |  RemoteGameSDK (JSON-lines TCP)
server/rsps_server.py  ---  server/client.py
      |
game/sdk.py          <- the ONLY surface strategies/LLM see
      |
game/world.py        <- mechanics: ticks, combat, skills, save/load
      |
game/content.py      <- ALL data tables (single source of truth)
      |
game/kernel.py       <- optional event bus / scheduler plugin host
```

## Live-data flow

```
prices.runescape.wiki + oldschool.runescape.wiki API
        |  osrs_updater.py (--watch N | Task Scheduler via
        |  register-updater-task.ps1, retries + lockfile + logging)
        v
knowledge/live/{ge_prices,game_updates,status}.json
        |
game/livewatch.LiveStream  (mtime change detection)
        |-- server/rsps_server.py: poller thread folds snapshots into
        |    a versioned cache; clients call {"cmd":"live"} /
        |    RemoteGameSDK.live(items=[...]) -> play_rsps.py GE ticker
        |-- game/market.py -> sdk.ge_price(item)  (None when stale)
        `-- assistant/plugins/ge.js  (Venus: "ge <item>")
tools/update_knowledge.py -> knowledge/raw/* -> knowledge/digest.md (/digest command)
```

Tests must never write into `knowledge/live/` - use a temp dir via
LiveStream(live_dir=...) or module-level LIVE_DIR override.

## Conventions

- Python 3.12, stdlib-first (pygame/numpy/torch only where earned).
- CommonJS + `"use strict"` inside Venus; no build step there either.
- New verbs must be added in three places together:
  `world.py` mechanic -> `sdk.py` method + `_VALID` + docs ->
  `verify_system.py` check. Client keybinds follow user demand.
- Windows-first: paths via `os.path`, PowerShell for orchestration.

## Decision log

- 2026-08-23: data tables consolidated into content.py after concurrent
  edits duplicated SHOP_STOCK; version control introduced workspace-wide.
- 2026-08-23: full-automation permissions granted to Thoth
  (`opencode.jsonc` permission = allow-all); elevated automation runs
  through Task Scheduler `-RunLevel Highest`, not UAC bypasses.
