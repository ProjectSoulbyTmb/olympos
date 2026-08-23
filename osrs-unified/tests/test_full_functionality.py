import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.sdk import GameSDK  # noqa: E402
from game.world import GameError, World  # noqa: E402


def make_game(ticks=600):
    w = World(seed=7, tick_budget=ticks)
    return w, GameSDK(w)


class TestSdkExtensions(unittest.TestCase):
    def test_skills_single_and_invalid(self):
        _w, g = make_game()
        self.assertIsInstance(g.skills("woodcutting"), int)
        self.assertEqual(g.skills("woodcutting"), 1)
        with self.assertRaises(GameError):
            g.skills("nope")

    def test_get_location_shape(self):
        _w, g = make_game()
        loc = g.get_location()
        self.assertEqual(set(loc), {"pos", "nearest", "distance"})
        self.assertEqual(len(loc["pos"]), 2)

    def test_tools_categorises_starting_kit(self):
        _w, g = make_game()
        t = g.tools()
        self.assertIn("bronze_axe", t["axes"])
        self.assertIn("bronze_pickaxe", t["pickaxes"])

    def test_bank_reflects_deposits(self):
        w, g = make_game(2000)
        w.inventory["logs"] = 3
        g.walk("bank")
        g.deposit_all()
        self.assertEqual(g.bank().get("logs"), 3)

    def test_quest_lookup(self):
        _w, g = make_game()
        self.assertIn("logs_fetch", g.quest())
        self.assertEqual(g.quest("shrimp_fetch"), "not_started")
        with self.assertRaises(GameError):
            g.quest("monkey_madness")

    def test_aliases_delegate(self):
        w, g = make_game(4000)
        g.walk("tree_1")
        got = [a for a in (g.cut_log(),) if a is True]
        w2, g2 = make_game(4000)
        g2.walk("tree_1")
        got2 = [a for a in (g2.chop(),) if a is True]
        self.assertEqual(bool(got), bool(got2))

    def test_set_energy_regen_clamps(self):
        _w, g = make_game()
        self.assertEqual(g.set_energy_regen(9.9), 2.0)
        self.assertEqual(g.set_energy_regen(-5), 0.5)
        with self.assertRaises(GameError):
            g.set_energy_regen("fast")

    def test_get_score_live(self):
        w, g = make_game()
        result = g.get_score("wc_xp")
        self.assertIn("score", result)
        self.assertIn("total_xp", result)


class TestStrongholdChest(unittest.TestCase):
    def test_once_only_with_reward(self):
        w, g = make_game(2000)
        g.walk("stronghold_of_security")
        before = g.coins()
        self.assertTrue(g.search_chest())
        self.assertEqual(g.coins(), before + 500)
        self.assertFalse(g.search_chest())
        self.assertEqual(g.coins(), before + 500)

    def test_requires_proximity(self):
        _w, g = make_game()
        with self.assertRaises(GameError):
            g.search_chest()

    def test_claim_survives_snapshot_roundtrip(self):
        w, g = make_game(2000)
        g.walk("stronghold_of_security")
        g.search_chest()
        snap = w.save()
        self.assertEqual(snap["version"], 5)
        w2 = World(seed=11)
        w2.load_snapshot(snap)
        self.assertEqual(GameSDK(w2).claims(), ["stronghold_chest"])

    def test_version4_snapshots_still_load(self):
        w, _g = make_game()
        snap = w.save()
        legacy = {k: v for k, v in snap.items()
                  if k not in ("claims", "energy_regen_mult")}
        legacy["version"] = 4
        w2 = World(seed=13)
        w2.load_snapshot(legacy)
        self.assertEqual(w2.energy_regen_mult, 1.0)


class TestFullProgressionStrategy(unittest.TestCase):
    def _run(self, task, ticks, uim):
        import bench
        with tempfile.TemporaryDirectory() as td:
            os.environ["OSRS_ROOT"] = td
            try:
                import importlib
                importlib.reload(bench)
                bench.manual_mode(
                    task, str(ROOT / "strategies" / "full_progression.py"),
                    tick_budget=ticks, uim=uim)
            finally:
                os.environ.pop("OSRS_ROOT", None)
                importlib.reload(bench)

    def test_runs_clean_on_wc_task(self):
        self._run("wc_xp", 900, uim=False)

    def test_runs_clean_on_uim(self):
        self._run("uim_total_xp", 700, uim=True)


if __name__ == "__main__":
    unittest.main()
