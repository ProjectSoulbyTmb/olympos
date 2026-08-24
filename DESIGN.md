# OsrsLab - Architecture

This document is the design contract for everything in this workspace.
When code and this file disagree, fix the code.

## The ecosystem

| Product | Path | What it is |
|---|---|---|
| **OSRS Lab** | `osrs-llm-agent/`, `osrs-rl/`, root scripts | Original tick-based game engine (15 skills, 24x24 world), authoritative JSON-lines RSPS server on 127.0.0.1:43590, pygame client (`play_rsps.py`), PPO combat RL, LLM strategic agent |
| **Venus** | `assistant/` (own git repo) | Offline desktop companion: kernel.js event/service/command registries, plugin system, Piper TTS + Whisper STT + Ollama brain |
| **Thoth** | opencode + `~/.config/opencode/` | The development layer itself: agents, skills, permissions. Runs with full automation grants |
| **Vulcan** | `vulcan/` | Smart-building automation sandbox: content.py data tables, devices.py + world.py thermal/tick mechanics, rules.py automation engine (condition/schedule/event rules), sdk.py in-process + wire faces, server.py authoritative JSON-lines on 127.0.0.1:43901, verify_vulcan.py suite (17 checks) |

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

- 2026-08-23: Vulcan added (`vulcan/`). Same contract as OSRS Lab: all
  numbers in `content.py`, authoritative JSON-lines server with an
  `error` field on every response, one SDK surface for in-process and
  wire clients, versioned saves (v1) that also carry the full ruleset
  under an `automation` key (load-side default: built-ins only), and
  its own verify gate (`python vulcan/verify_vulcan.py`, currently
  18/18). Rules are plain JSON; actuator writes are idempotent no-ops
  so tick rules can run freely, and alert actions are rate-limited
  per rule.
- 2026-08-23: Vulcan enhanced automation + self-healing. Rules gained
  motion events, `sequence` (deferred multi-step actions),
  `device_group`, `power`/`zone_count`/`trend` conditions, `priority`
  ordering, `max_fires` one-shots and `run_in_modes` scoping. New
  warden.py patrols every tick and auto-repairs: HVAC-vs-open-contact
  waste, runaway duty (forced cooldown), stuck/out-of-bounds sensors
  (neighbor-average substitution), vacant lights in away/vacation,
  escalated shedding when plugs are exhausted. Rule failures trip a
  circuit breaker (auto-disable + timed revival, Venus-heart style).
  Saves rotate `.bak1..N`; corrupt saves auto-recover from the newest
  readable backup with a warning alert. Verify gate now 29/29; new
  SDK verbs: repairs/diagnose/warden.
- 2026-08-23: RSPS client brought to full playability (verify gate
  19 -> 26). Engine: ground-item layer + pickup, prayer book with
  drain/regen and combat multipliers, branching dialogue trees
  (talk_to/dialogue_choose) with two new quests, catacombs region
  with ladder teleports, skeleton/hobgoblin spawns and the Vulcan
  Guardian boss, water/earth strike spells, snapshot v7 (additive,
  v1-v6 still load). Server: named channels give shared chat +
  presence (state.players) without breaking per-player instancing;
  snapshots persist to server/saves/ and resume by name on re-login.
  Client: right-click context menus everywhere, clickable minimap,
  procedural sprites/animations/hit-splats, panel tabs (stats/inv/
  quests/magic/prayer/bank/shop), dialogue window, chat box, area
  ambience with catacombs drone.
- 2026-08-23: social + VTuber pass (verify gate 26 -> 29). Server:
  player-to-player trading (invite -> staged offers -> double
  confirm -> atomic swap validated under the lock; disconnect-safe)
  and a status/discovery command. Client: VTuber-style procedural
  avatar rig learned from VUP/VTube Studio/VSeeFace - blink cycle,
  breathing, idle sway, mouth flap while chatting, expression states
  (level-up celebration sparkles, hit flinch) and chat emotes
  (/wave /dance /bow...) broadcast through the channel. Venus widget
  gains Luppet-style mouse head-tracking (head+spine bones follow the
  cursor) and VUP-style emote hotkeys (1-5 moods, Z/X/C gestures);
  her existing VRM stack already covers visemes/emotions/overlay
  transparency. Packaging: build_client.ps1 builds standalone
  OsrsPlay.exe; runner menu grows "Play now".

- 2026-08-23: Heart gained autonomic energy states (awake/drowsy/asleep
  driven by command activity, sleepBpm slowdown) and pluggable critical
  alerters; plugin `tasks:` now auto-route to heart organs when the
  period fits one beat, else stay on addTask.
- 2026-08-23: Venus kernel gained a Heart (`assistant/lib/heart.js`) -
  beat-paced organ cadences with quarantine/auto-revival and vitals
  telemetry. New cadenced Venus work should use `heart.addOrgan` over raw
  `addTask`; the OSRS verify suite gates it via `node assistant/test-heart.js`.
- 2026-08-23: data tables consolidated into content.py after concurrent
  edits duplicated SHOP_STOCK; version control introduced workspace-wide.
- 2026-08-23: full-automation permissions granted to Thoth
  (`opencode.jsonc` permission = allow-all); elevated automation runs
  through Task Scheduler `-RunLevel Highest`, not UAC bypasses.
