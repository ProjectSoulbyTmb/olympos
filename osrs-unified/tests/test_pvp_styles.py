import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from envs.osrs_sim import (ACTIONS, MAGIC_RANGE, MAX_DIST, MAX_TICKS,
                           MELEE_RANGE, N_ACTIONS, OBS_DIM, RANGED_RANGE,
                           Fighter, HeuristicBot, OsrsPvpEnv)  # noqa: E402


class TestPvpStyles(unittest.TestCase):
    def test_action_space_grew(self):
        self.assertEqual(ACTIONS[6], "shoot")
        self.assertEqual(ACTIONS[7], "cast")
        self.assertEqual(N_ACTIONS, 8)
        self.assertEqual(OBS_DIM, 16)

    def test_obs_shape(self):
        env = OsrsPvpEnv(seed=1)
        obs = env.reset()
        self.assertEqual(obs[0].shape, (OBS_DIM,))
        self.assertEqual(obs[1].shape, (OBS_DIM,))

    def test_mask_ranges(self):
        env = OsrsPvpEnv(seed=1)
        env.reset()
        mask_a, _mask_b = env.legal_mask()
        dist = abs(env.b.pos - env.a.pos)
        self.assertEqual(bool(mask_a[0]), dist <= MELEE_RANGE)
        self.assertEqual(bool(mask_a[6]),
                         dist <= RANGED_RANGE and env.a.ammo > 0)
        self.assertEqual(bool(mask_a[7]),
                         dist <= MAGIC_RANGE and env.a.runes > 0)

    def test_shoot_consumes_ammo_and_hits_range(self):
        env = OsrsPvpEnv(seed=2)
        env.reset()
        # park B far away so only ranged/magic can reach
        env.b.pos = min(MAX_DIST, env.a.pos + RANGED_RANGE)
        ammo_before = env.a.ammo
        out = env.step(6, 5)
        self.assertEqual(env.a.ammo, ammo_before - 1)
        self.assertFalse(out[5])            # fight continues

    def test_melee_illegal_at_distance_is_noop(self):
        env = OsrsPvpEnv(seed=3)
        env.reset()
        env.b.pos = MAX_DIST
        hp_before = env.b.hp
        cd_before = env.a.cooldown
        env.step(0, 5)                      # A tries melee from afar
        self.assertEqual(env.b.hp, hp_before)
        self.assertEqual(env.a.cooldown, cd_before)

    def test_full_random_episode(self):
        env = OsrsPvpEnv(seed=4)
        env.reset()
        rng = np.random.default_rng(9)
        for _ in range(MAX_TICKS):
            ma, mb = env.legal_mask()
            a = int(rng.choice(np.flatnonzero(ma)))
            b = int(rng.choice(np.flatnonzero(mb)))
            *_rest, done = env.step(a, b)
            if done:
                break
        self.assertTrue(done)

    def test_heuristic_bot_unpacks(self):
        env = OsrsPvpEnv(seed=5)
        obs = env.reset()
        mask = env.legal_mask()[0]
        action = HeuristicBot().act(obs[0], mask)
        self.assertTrue(0 <= action < N_ACTIONS)

    def test_fighter_style_formulas_differ(self):
        f = Fighter(np.random.default_rng(0), 3)
        self.assertGreaterEqual(f.max_hit_ranged(), 2)
        self.assertGreaterEqual(f.max_hit_magic(), 3)
        acc_m = f.accuracy_vs(f, "melee")
        acc_r = f.accuracy_vs(f, "ranged")
        self.assertAlmostEqual(acc_m + acc_r, 1.0, delta=0.35)


if __name__ == "__main__":
    unittest.main()
