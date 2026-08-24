"""DAEDALUS blueprint: godot-game - deterministic orb-collector.

The first codegen target that proves cross-language determinism by
construction: gem positions are computed ONCE here (weave time, seeded)
and BAKED as literals into both the GDScript project and the pure-
Python twin. Twin and game can therefore never disagree about the
world - any divergence is a real bug, and the twin's journal is the
replay evidence (norn pattern, INTEGRATION.md A4/A5).

Files woven per instance:
    project.godot        Godot 4.x, Compatibility renderer
    main.tscn            root scene wired to main.gd
    main.gd              fixed-tick collector game (baked world)
    game_spec.json       shared constants (single source for both)
    twin.py              deterministic Python oracle -> journal.jsonl
    verify_game_twin.py  self-test gate: twin x2 identical + WIN
"""

import json
import random

GRID = 8
TARGET = 5
SEED = 20260824
TICKS_PER_MOVE = 30

# Weave-time world generation: first TARGET free cells from the seeded
# RNG, skipping start (0,0) and duplicates.
_rng = random.Random(SEED)
_cells = set()
while len(_cells) < TARGET:
    c = (_rng.randrange(GRID), _rng.randrange(GRID))
    if c != (0, 0):
        _cells.add(c)

# Greedy sweep path from (0,0) through every gem (x-first, then y).
_gems_sorted = sorted(_cells)
_pos = (0, 0)
_moves = []
for gx, gy in _gems_sorted:
    dx = gx - _pos[0]
    dy = gy - _pos[1]
    _moves.extend("R" if dx > 0 else "L" for _ in range(abs(dx)))
    _moves.extend("D" if dy > 0 else "U" for _ in range(abs(dy)))
    _pos = (gx, gy)

SPEC = {
    "grid": GRID,
    "gems": [list(c) for c in sorted(_cells)],
    "target": TARGET,
    "moves": _moves,
    "ticks_per_move": TICKS_PER_MOVE,
}

SPEC_JSON = json.dumps(SPEC, indent=2, sort_keys=True)

PROJECT_GODOT = """\
config_version=5

[application]

config/name="Orb Collector"
run/main_scene="res://main.tscn"

[rendering]

renderer/rendering_method="gl_compatibility"
"""

MAIN_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node"]
script = ExtResource("1")
"""

def _repr_vecs():
    return "[" + ", ".join(f"Vector2i({x}, {y})" for x, y in SPEC["gems"]) + "]"

def _repr_moves():
    return "[" + ", ".join(f'"{m}"' for m in SPEC["moves"]) + "]"



MAIN_GD = """\
extends Node

# DAEDALUS-woven orb collector. World is BAKED at weave time from
# seed {seed} - no runtime RNG, so the Python twin is an exact oracle.
# Tick discipline: simulation advances only in _tick().

const GRID := {grid}
const TARGET := {target}
const TICKS_PER_MOVE := {tpm}
const GEMS := {gems}
const MOVES := {moves}

var tick := 0
var move_idx := 0
var pos := Vector2i(0, 0)
var score := 0
var collected: Array[Vector2i] = []
var done := false


func _ready() -> void:
    var f := FileAccess.open("user://state.json", FileAccess.WRITE)
    f.store_string(JSON.stringify({{"tick": 0}}))
    f.close()


func _process(_delta: float) -> void:
    if done or move_idx >= MOVES.size():
        return
    # one queued move per TICKS_PER_MOVE ticks
    if tick % TICKS_PER_MOVE == 0:
        _step(MOVES[move_idx])
        move_idx += 1
    tick += 1


func _step(dir: String) -> void:
    var d := Vector2i.ZERO
    if dir == "R": d = Vector2i(1, 0)
    elif dir == "L": d = Vector2i(-1, 0)
    elif dir == "D": d = Vector2i(0, 1)
    elif dir == "U": d = Vector2i(0, -1)
    else: return  # unknown move: hold position (house rule)
    var nxt := pos + d
    if nxt.x < 0 or nxt.y < 0 or nxt.x >= GRID or nxt.y >= GRID:
        return  # walls: stay
    pos = nxt
    if pos in GEMS and not collected.has(pos):
        collected.append(pos)
        score += 1
    if score >= TARGET:
        done = true
""".format(grid=GRID, target=TARGET, tpm=TICKS_PER_MOVE,
           seed=SEED, gems=_repr_vecs(), moves=_repr_moves())


TWIN = """\
\"\"\"Deterministic Python twin of the woven orb-collector.

Replays the baked move list against game_spec.json and writes
journal.jsonl ({tick, pos, score, collected, digest}) plus a final
verdict line. Exits 0 only when the run WINS.
\"\"\"

import hashlib
import json
import sys

spec = json.load(open("game_spec.json", encoding="utf-8"))
gems = {tuple(g) for g in spec["gems"]}
target = spec["target"]
moves = spec["moves"]
tpm = spec["ticks_per_move"]
pos = (0, 0)
score = 0
collected = set()
journal = []


def digest(tick):
    payload = "{{}}{{}}{{}}".format(
        tick, ",".join(map(str, pos)),
        "|".join(sorted(",".join(map(str, c)) for c in collected)))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


for i, mv in enumerate(moves):
    d = {"R": (1, 0), "L": (-1, 0), "D": (0, 1), "U": (0, -1)}.get(mv)
    if d is None:
        continue
    nx, ny = pos[0] + d[0], pos[1] + d[1]
    if 0 <= nx < spec["grid"] and 0 <= ny < spec["grid"]:
        pos = (nx, ny)
    if pos in gems:
        collected.add(pos)
        score = len(collected)
    tick = (i + 1) * tpm
    journal.append({"tick": tick, "pos": list(pos),
                    "score": score, "digest": digest(tick)})
    if score >= target:
        break

win = score >= target
with open("journal.jsonl", "w", encoding="utf-8") as fh:
    for e in journal:
        fh.write(json.dumps(e) + "\\n")
    verdict = {"verdict": "WIN" if win else "LOSE",
               "score": score, "target": target,
               "final_digest": digest((len(journal)) * tpm)}
    fh.write(json.dumps(verdict) + "\\n")
if not win:
    sys.exit(1)
"""


GATE = '''"""Self-test gate: twin determinism + victory (exit 0 = pass)."""

import json
import subprocess
import sys

runs = []
for i in (1, 2):
    r = subprocess.run([sys.executable, "twin.py"],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"twin run {i} lost: {r.stderr}"
    runs.append(open("journal.jsonl", encoding="utf-8").read())
assert runs[0] == runs[1], "twin is nondeterministic between runs"
last = json.loads(runs[0].strip().splitlines()[-1])
assert last["verdict"] == "WIN", last
print("godot-game gate green:", last["final_digest"])
sys.exit(0)
'''


def files():
    """Weave file map (fresh dicts per call - Workshop owns copies)."""
    return {
        "project.godot": PROJECT_GODOT,
        "main.tscn": MAIN_TSCN,
        "main.gd": MAIN_GD,
        "game_spec.json": SPEC_JSON,
        "twin.py": TWIN,
        "verify_game_twin.py": GATE,
    }


FILES = files()
FAULTS = {
    # target raised past the baked move list -> twin LOSES -> retry
    "unwinnable": ("game_spec.json",
                   '"target": {}'.format(TARGET),
                   '"target": {}'.format(TARGET + 94)),
}
