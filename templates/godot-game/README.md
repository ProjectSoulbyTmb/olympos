# Olympos game output template (Godot 4.x)

The first sanctioned **codegen target** for the autonomous build loop.
A generator copies this directory and replaces the marked bodies; the
shape stays fixed so verification stays uniform.

## Codegen contract

1. `project.godot` - Compatibility renderer, fixed feature set.
2. `main.tscn` - single root node wired to `main.gd`.
3. `main.gd` - keep the tick discipline:
   - simulation advances ONLY in `_tick()` at a fixed rate;
   - `_process()` never mutates game state;
   - RNG is seeded from `$GAME_SEED` (deterministic by default);
   - backlog shedding after 5 catch-up ticks.

## Verification ladder for generated games

| Level | Check | Tool |
|---|---|---|
| L0 structural | files present, project.godot parses as INI, main scene referenced | `python templates/verify_template.py` (this repo) |
| L1 import | `godot --headless --import` exits 0 | requires Godot binary |
| L2 smoke | `godot --headless` + auto-quit timer script runs N seconds without error | requires Godot binary |
| L3 replay | seeded run digest == golden digest | norn replay pattern |

Godot binary is NOT bundled; L1+ run where an editor install exists
(`GODOT_BIN` environment variable names the executable).
