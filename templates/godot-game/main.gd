extends Node

# Fixed-timestep simulation, decoupled rendering (house rule).
# Simulation state advances ONLY inside _tick(); _process() never
# touches game state. Seeded RNG by default -> replayable sessions
# pair with norn-style seed files when this template grows up.

const TICK_RATE := 60
const MAX_TICKS_PER_FRAME := 5

var rng := RandomNumberGenerator.new()
var tick := 0
var _accumulator := 0.0


func _ready() -> void:
	# Deterministic by default; override via OS.get_environment seed.
	var seed_text := OS.get_environment("GAME_SEED")
	rng.seed = int(seed_text) if seed_text != "" else 0x666F646F74


func _process(delta: float) -> void:
	_accumulator += delta
	var spent := 0
	while _accumulator >= 1.0 / TICK_RATE and spent < MAX_TICKS_PER_FRAME:
		_tick(1.0 / TICK_RATE)
		tick += 1
		spent += 1
		_accumulator -= 1.0 / TICK_RATE
	if spent == MAX_TICKS_PER_FRAME and _accumulator > 0.25:
		_accumulator = 0.0  # shed backlog instead of death-spiral


func _tick(_dt: float) -> void:
	pass  # generated game logic replaces this body
