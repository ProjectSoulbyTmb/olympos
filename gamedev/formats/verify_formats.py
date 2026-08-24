import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formats.schemas import (  # noqa: E402
    MAP_FORMAT,
    REPLAY_FORMAT,
    make_map,
    save_map,
    load_map,
    validate_map,
    validate_replay,
)


def border_map(width=10, height=8):
    tiles = []
    for y in range(height):
        for x in range(width):
            edge = x in (0, width - 1) or y in (0, height - 1)
            tiles.append(1 if edge else 0)
    return make_map(width, height, tiles, spawn=(1, 1))


class TestMapValidation(unittest.TestCase):
    def test_valid_border_map(self):
        m = border_map()
        self.assertEqual(validate_map(m), [])

    def test_bad_format_tag(self):
        m = border_map()
        m["format"] = "nope"
        self.assertTrue(any("format" in e for e in validate_map(m)))

    def test_tile_count_mismatch(self):
        m = border_map()
        m["layers"][0]["tiles"] = m["layers"][0]["tiles"][:-1]
        errs = validate_map(m)
        self.assertTrue(any("length" in e for e in errs))

    def test_negative_tile_rejected(self):
        m = border_map()
        m["layers"][0]["tiles"][5] = -2
        self.assertTrue(any("invalid tile" in e for e in validate_map(m)))

    def test_spawn_out_of_bounds(self):
        m = border_map()
        m["spawn"] = [99, 99]
        self.assertTrue(any("spawn" in e for e in validate_map(m)))

    def test_duplicate_layer_names(self):
        m = border_map()
        m["layers"].append({"name": "ground", "tiles": m["layers"][0]["tiles"]})
        self.assertTrue(any("duplicate" in e for e in validate_map(m)))

    def test_non_dict_rejected(self):
        self.assertEqual(len(validate_map([1, 2])), 1)

    def test_save_refuses_invalid(self):
        import tempfile

        m = border_map()
        m["width"] = -1
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                save_map(m, str(Path(td) / "bad.json"))

    def test_save_load_roundtrip(self):
        import os
        import tempfile

        m = border_map()
        with tempfile.TemporaryDirectory() as td:
            p = str(Path(td) / "m.json")
            save_map(m, p)
            self.assertEqual(load_map(p), m)


class TestReplayValidation(unittest.TestCase):
    def valid_replay(self):
        return {
            "format": REPLAY_FORMAT,
            "seed": 7,
            "game": "snake",
            "ticks": [
                {"t": 0, "inputs": ["up"]},
                {"t": 1, "inputs": []},
                {"t": 2, "inputs": ["left", "left"]},
            ],
        }

    def test_valid_replay(self):
        self.assertEqual(validate_replay(self.valid_replay()), [])

    def test_tick_gap_rejected(self):
        r = self.valid_replay()
        r["ticks"][2]["t"] = 5
        self.assertTrue(any("previous+1" in e for e in validate_replay(r)))

    def test_nonstring_input_rejected(self):
        r = self.valid_replay()
        r["ticks"][0]["inputs"] = [3]
        self.assertTrue(any("inputs" in e for e in validate_replay(r)))

    def test_bad_seed(self):
        r = self.valid_replay()
        r["seed"] = -1
        self.assertTrue(any("seed" in e for e in validate_replay(r)))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    )
    sys.exit(0 if result.wasSuccessful() else 1)
