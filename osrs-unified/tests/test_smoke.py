"""Release smoke tests for osrs-unified (stdlib unittest, no pytest needed).

Run:  python -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import contextlib
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestImports(unittest.TestCase):
    def test_all_packages_import(self):
        import agent, algo, envs, game, rsps_adapter, server, tools  # noqa

    def test_entry_modules_import(self):
        import bench, evaluate, train, osrs_cli  # noqa


class TestSkillingBench(unittest.TestCase):
    def test_manual_mode_runs_and_scores(self):
        import importlib
        import bench
        with tempfile.TemporaryDirectory() as td:
            os.environ["OSRS_ROOT"] = td
            try:
                importlib.reload(bench)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    bench.manual_mode("wc_xp", str(ROOT / "strategies" /
                                                    "example_bot.py"),
                                      tick_budget=300)
                out = buf.getvalue()
                self.assertIn("session saved", out)
                self.assertTrue((Path(td) / "runs" / "wc_xp" /
                                 "session.json").exists())
            finally:
                os.environ.pop("OSRS_ROOT", None)
                importlib.reload(bench)

    def test_tick_budget_enforced(self):
        from game.world import BudgetExceeded, World
        w = World(seed=1, tick_budget=50)
        w.spend(50)
        self.assertEqual(w.ticks_left, 0)
        with self.assertRaises(BudgetExceeded):
            w.spend(1)


class TestPvpRl(unittest.TestCase):
    def test_env_step_shapes_and_legal_mask(self):
        import numpy as np
        from envs.osrs_sim import OsrsPvpEnv, N_ACTIONS, OBS_DIM, RandomBot
        env = OsrsPvpEnv(seed=3)
        obs_a, obs_b = env.reset()
        self.assertEqual(obs_a.shape, (OBS_DIM,))
        bot = RandomBot(0)
        for _ in range(30):
            mask_a, mask_b = env.legal_mask()
            self.assertEqual(mask_a.shape, (N_ACTIONS,))
            self.assertGreaterEqual(mask_a.sum(), 1)  # always >=1 legal action
            _, _, _, _, _, done = env.step(
                int(mask_a.argmax()), int(bot.act(obs_b, mask_b)))
            if done:
                break

    def test_actor_critic_forward(self):
        import torch
        from algo.networks import ActorCritic
        from envs.osrs_sim import N_ACTIONS, OBS_DIM
        net = ActorCritic(OBS_DIM, N_ACTIONS)
        obs = torch.zeros(OBS_DIM)
        mask = torch.ones(N_ACTIONS, dtype=torch.bool)
        out = net.act(obs, mask)
        self.assertTrue(len(out) in (2, 3))
        acts = net.act_batch(torch.zeros(4, OBS_DIM),
                             torch.ones(4, N_ACTIONS, dtype=torch.bool))
        self.assertEqual(acts[0].shape[0], 4)


class TestCli(unittest.TestCase):
    def test_version_command(self):
        import osrs_cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = osrs_cli.main(["version"])
        self.assertEqual(rc, 0)
        self.assertIn("osrs-unified", buf.getvalue())

    def test_cli_help_lists_commands(self):
        import osrs_cli
        ap_out = io.StringIO()
        with contextlib.redirect_stdout(ap_out), \
             unittest.mock.patch("sys.argv", ["osrs"]):
            try:
                osrs_cli.main([])
            except SystemExit:
                pass
        help_text = ap_out.getvalue()
        for cmd in ("bench", "train", "eval", "knowledge", "version"):
            self.assertIn(cmd, help_text)


if __name__ == "__main__":
    unittest.main()
