import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.content import BIRDS, CONSTRUCTION, PLANKS  # noqa: E402
from game.sdk import GameSDK  # noqa: E402
from game.world import GameError, World, xp_for_level  # noqa: E402


def make_game(ticks=4000):
    w = World(seed=11, tick_budget=ticks)
    return w, GameSDK(w)


class TestConstruction(unittest.TestCase):
    def test_skills_registered(self):
        _w, g = make_game()
        self.assertIn("construction", g.skills())
        self.assertIn("hunter", g.skills())

    def test_planking_needs_workshop_and_logs(self):
        w, g = make_game()
        with self.assertRaises(GameError):
            g.cut_planks()
        g.walk("workshop")
        with self.assertRaises(GameError):
            g.cut_planks()
        w.inventory["logs"] = 2
        w.coins = 0
        with self.assertRaises(GameError):
            g.cut_planks()

    def test_plank_loop(self):
        w, g = make_game()
        w.inventory["logs"] = 3
        g.walk("workshop")
        start_coins = w.coins
        self.assertEqual(g.cut_planks(), "plank")
        self.assertEqual(w.inventory.get("plank"), 1)
        self.assertEqual(w.inventory.get("logs"), 2)
        self.assertLess(w.coins, start_coins)

    def test_build_requires_tools_and_mats(self):
        w, g = make_game()
        g.walk("workshop")
        spec = CONSTRUCTION["crude_wooden_chair"]
        with self.assertRaises(GameError):
            g.build("crude_wooden_chair")          # no saw
        w.tools.append("saw")
        with self.assertRaises(GameError):
            g.build("crude_wooden_chair")          # no hammer
        w.tools.append("hammer")
        for mat in ("plank", "steel_nails"):
            w.inventory[mat] = 10
        out = g.build("crude_wooden_chair")
        self.assertEqual(out, "crude_wooden_chair")
        self.assertIn("crude_wooden_chair", w.inventory)
        self.assertGreater(w.xp["construction"], 0)

    def test_build_gates_level(self):
        w, g = make_game()
        g.walk("workshop")
        w.tools += ["saw", "hammer"]
        for mat in ("plank", "steel_nails"):
            w.inventory[mat] = 4
        with self.assertRaises(GameError):
            g.build("wooden_chair")                # needs level 8
        w.xp["construction"] = float(xp_for_level(9))
        self.assertEqual(g.build("wooden_chair"), "wooden_chair")

    def test_furniture_sellable(self):
        from game.world import SHOP_PRICES
        for name in CONSTRUCTION:
            self.assertIn(name, SHOP_PRICES)


class TestHunter(unittest.TestCase):
    def test_trap_requires_snare_and_ground(self):
        w, g = make_game()
        with self.assertRaises(GameError):
            g.lay_trap()
        g.walk("hunting_ground")
        with self.assertRaises(GameError):
            g.lay_trap()                            # no snare
        w.inventory["bird_snare"] = 2
        self.assertTrue(g.lay_trap())
        self.assertEqual(w.inventory.get("bird_snare"), 1)
        self.assertEqual(len(w.traps), 1)

    def test_check_trap_resolves(self):
        w, g = make_game()
        w.inventory["bird_snare"] = 1
        g.walk("hunting_ground")
        g.lay_trap()
        with self.assertRaises(GameError):
            g.check_trap()                          # still arming
        key = next(iter(w.traps))
        w.traps[key]["ready_at"] = w.tick
        got_bird = g.check_trap()
        self.assertIsInstance(got_bird, bool)
        self.assertNotIn(key, w.traps)

    def test_success_yields_loot_and_xp(self):
        w, g = make_game()
        w.xp["hunter"] = float(xp_for_level(30))    # near-guaranteed catch
        w.inventory["bird_snare"] = 1
        g.walk("hunting_ground")
        g.lay_trap()
        key = next(iter(w.traps))
        w.traps[key]["ready_at"] = w.tick
        caught = False
        for _ in range(40):
            if g.check_trap():
                caught = True
                break
            w.inventory["bird_snare"] = max(
                1, w.inventory.get("bird_snare", 0))
            g.lay_trap()
            key = next(iter(w.traps))
            w.traps[key]["ready_at"] = w.tick
        self.assertTrue(caught)
        self.assertGreater(w.xp["hunter"], 0)
        has_bird_bits = any(i in w.inventory for i in
                            ("raw_bird_meat", "bones", "red_feather",
                             "orange_feather"))
        self.assertTrue(has_bird_bits)

    def test_max_traps_enforced(self):
        w, g = make_game()
        w.inventory["bird_snare"] = 5
        g.walk("hunting_ground")
        for _ in range(2):
            g.lay_trap()
        with self.assertRaises(GameError):
            g.lay_trap()

    def test_bird_tiers_grounded(self):
        self.assertEqual(BIRDS["crimson_swift"]["req"], 1)
        self.assertEqual(BIRDS["copper_longtail"]["req"], 9)
        self.assertIn("raw_bird_meat",
                      __import__("game.content", fromlist=["COOKABLES"])
                      .COOKABLES)


class TestSaveCompat(unittest.TestCase):
    def test_v6_save_roundtrips_traps(self):
        w, _g = make_game()
        w.inventory["bird_snare"] = 1
        w.pos = (3, 20)
        w.lay_trap()
        data = w.save()
        self.assertEqual(data["version"], 6)
        w2 = World(seed=3, tick_budget=100)
        w2.load_snapshot(data)
        self.assertEqual(len(w2.traps), len(w.traps))

    def test_v5_snapshot_still_loads(self):
        import copy
        w, _g = make_game()
        snap = copy.deepcopy(w.save())
        snap["version"] = 5
        snap.pop("traps", None)
        w2 = World(seed=3, tick_budget=100)
        w2.load_snapshot(snap)
        self.assertEqual(w2.traps, {})

    def test_kernel_event_ring(self):
        from game.kernel import MIND
        k = MIND(World(seed=1))
        k.emit("test_event", a=1)
        events = k.recent_events()
        self.assertEqual(events[-1][1], "test_event")
        self.assertEqual(events[-1][2], {"a": 1})


if __name__ == "__main__":
    unittest.main()
