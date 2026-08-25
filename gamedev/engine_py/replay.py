import json

from formats.schemas import REPLAY_FORMAT, validate_replay


class Recorder:
    def __init__(self, seed, game_name):
        self.seed = seed
        self.game_name = game_name
        self._ticks = []

    def push(self, inputs):
        tick = {"t": len(self._ticks), "inputs": list(inputs)}
        self._ticks.append(tick)
        return tick["t"]

    def build(self):
        replay = {
            "format": REPLAY_FORMAT,
            "seed": self.seed,
            "game": self.game_name,
            "ticks": list(self._ticks),
        }
        errors = validate_replay(replay)
        if errors:
            raise ValueError(f"invalid replay: {errors}")
        return replay


class ReplayRunner:
    def __init__(self, replay, factory):
        self.replay = replay
        errors = validate_replay(replay)
        if errors:
            raise ValueError(f"invalid replay: {errors}")
        self._apply_tick, self._snapshot = factory()

    def run(self, collect=False):
        snapshots = []
        for tick in self.replay["ticks"]:
            self._apply_tick(tick["inputs"])
            if collect:
                snapshots.append(self._snapshot())
        return snapshots if collect else self._snapshot()


def save_replay_file(replay, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(replay, f)


def load_replay_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_deterministic(run_once, runs=2):
    results = [run_once() for _ in range(runs)]
    return all(r == results[0] for r in results), results[0]
