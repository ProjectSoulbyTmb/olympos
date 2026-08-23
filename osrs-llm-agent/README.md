# osrs-llm-agent

An LLM strategic agent that plays a simplified Old School RuneScape-style
skilling MMO by writing and executing its own strategy code, benchmarked on
XP/gold tasks. Grounded in live OSRS ground-truth data (GE prices + Wiki
articles) via an ingestion pipeline you can re-run on a schedule.

Local simulation only - it never touches the real game or any Jagex service.

## Architecture (runebench-style)

Core engine: **MIND kernel** (game/kernel.py) - the central event bus, tick-accurate scheduler, and strategy-session lifecycle that every other component plugs into.

```
bench.py                 CLI: tasks, manual mode, LLM mode, scoring
game/world.py            headless tick-based world: skills, nodes, bank, shop
game/sdk.py              the `game` object strategy code calls
agent/llm.py             OpenAI-compatible chat client (Ollama works out of the box)
agent/loop.py            orient -> prompt LLM -> exec snippet -> score loop
agent/runner.py          restricted executor: snippets define run(game), no imports
wiki/*.md                hand-written KB for the sim mechanics
knowledge/               OSRS ground truth fetched from official APIs
tools/update_knowledge.py   knowledge ingestion pipeline
strategies/              example bots (also usable as manual-mode baselines)
runs/                    best-run results per task
```

## Quick start

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

# baseline: run a strategy file directly, no LLM
& $py bench.py --task wc_xp --code-file strategies\example_bot.py

# refresh ground-truth knowledge (GE prices + wiki articles incl. UIM guides)
& $py tools\update_knowledge.py

# LLM mode: agent iterates, self-debugs, keeps its best run
& $py bench.py --task uim_total_xp --rounds 8 `
    --base-url http://localhost:11434/v1 --model llama3.1:8b
```

LLM config falls back to env vars: `LLM_BASE_URL` (default
`http://localhost:11434/v1`, i.e. local Ollama), `LLM_MODEL`,
`LLM_API_KEY`. Any OpenAI-compatible endpoint works.

## Tasks

| Task | Goal |
|---|---|
| `wc_xp` | max Woodcutting XP |
| `gold` | max net coins |
| `total_xp` | max total XP across skills |
| `cook_xp` | max Cooking XP (fish -> cook chain) |
| `uim_total_xp` | **Ultimate Ironman**: bank permanently locked; manage 28 slots with drop/sell strategies |

Scoring reports total XP, per-skill breakdown, net coins, peak XP rate over a
sliding window, and final levels.

## Knowledge pipeline ("continual" updates)

`tools/update_knowledge.py` pulls only authoritative sources and writes
`knowledge/digest.md` + `knowledge/ground_truth.json`:

- Grand Exchange real-time prices API (`prices.runescape.wiki/api/v1/osrs/latest`)
- GE item mapping (ids, buy limits)
- OSRS Wiki plain-text extracts for 14 topics: core skills, **Ultimate
  Ironman + UIM Guide**, all four skill training guides, money making.
  Every section records its source URL and fetch timestamp.

The digest is injected into every agent prompt (`ground_truth` doc), so the
planner reasons over real prices and authentic training-method guidance.

### Schedule hourly refreshes (Windows Task Scheduler)

```powershell
schtasks /Create /TN "OSRS Knowledge Refresh" `
  /TR "\"$env:LOCALAPPDATA\Programs\Python\Python312\python.exe\" \"C:\Users\Earth949\OneDrive\Documents\Default Project\osrs-llm-agent\tools\update_knowledge.py\"" `
  /SC HOURLY
```

Politeness: requests are spaced 0.6 s apart with a descriptive User-Agent,
per the APIs' terms. Hourly is more than enough - prices update frequently,
wiki articles rarely.

## Pause & resume anything

Every activity is checkpointable - stop mid-run whenever you need the machine,
pick up exactly where it stopped later:

```powershell
# start an activity with periodic autosave (runs\<task>\session.json)
& $py bench.py --task uim_total_xp --code-file strategies\uim_fisher.py `
    --ticks 3000 --save-every 100

# interrupt freely; later, continue from the last checkpoint
& $py bench.py --task uim_total_xp --code-file strategies\uim_fisher.py `
    --resume runs\uim_total_xp\session.json
```

Snapshots preserve tick counter, position, inventory, bank, XP, node respawn
timers and RNG state, so resumed sessions are statistically seamless.
LLM-mode loop state (`history`, best-so-far) persists per task in
`runs/<task>/loop_state.json` and resumes automatically on re-run.

## Notes

- The snippet sandbox blocks imports/file/network in the executed code. This
  is accident-proofing for your own machine, not a security boundary.
- Sim XP values mirror real OSRS rates (tree 25xp, oak 37.5xp, iron ore 35xp,
  shrimps 10/30xp, burn-stop at Cooking 34); shop prices are sim-balanced.
