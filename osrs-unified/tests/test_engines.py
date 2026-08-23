import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mind import builder, healer, knowledge_engine, metrics  # noqa: E402
from mind import scheduler, sentinel  # noqa: E402
from mind.state import MindState  # noqa: E402


class TestSchedulerEngine(unittest.TestCase):
    def test_defaults_add_remove_due_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            st = MindState(td)
            jobs = scheduler.list_jobs(st)
            self.assertIn("patrol", [j["name"] for j in jobs])
            scheduler.add_job(st, "custom", 5)
            due = scheduler.due_jobs(st)
            self.assertIn("custom", due)
            scheduler.tick(st)
            self.assertEqual(scheduler.due_jobs(st), [])
            scheduler.remove_job(st, "custom")
            names = [j["name"] for j in scheduler.list_jobs(st)]
            self.assertNotIn("custom", names)

    def test_interval_respected(self):
        with tempfile.TemporaryDirectory() as td:
            st = MindState(td)
            scheduler.add_job(st, "tiny", 10)
            scheduler.tick(st)
            self.assertEqual(scheduler.due_jobs(st), [])


class TestMetricsEngine(unittest.TestCase):
    def test_snapshot_and_summary_trend(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "runs").mkdir()
            for score in (100, 250):
                with open(Path(td, "runs", "wc_xp_best.json"), "w") as f:
                    json.dump({"score": score}, f)
                metrics.snapshot(td)
            s = metrics.summary(td)
            self.assertGreaterEqual(s["samples"], 2)
            trend = s["task_trends"]["wc_xp"]
            self.assertEqual(trend["delta"], 150)


class TestKnowledgeEngine(unittest.TestCase):
    def test_sim_parity_passes_on_repo(self):
        status = knowledge_engine.revision_status(str(ROOT), fetch=False)
        parity_findings = [f for f in status["findings"]
                           if f["area"] == "parity"]
        self.assertEqual(parity_findings, [],
                         json.dumps(status["findings"], indent=1))
        self.assertTrue(status["xp_parity_ok"])

    def test_detects_drifted_table(self):
        with tempfile.TemporaryDirectory() as td:
            game = Path(td, "game")
            game.mkdir()
            (game / "__init__.py").write_text("", encoding="utf-8")
            (game / "world.py").write_text(
                "XP_TABLE = [0, 83, 999]\n"
                "SHOP_PRICES = {}\n", encoding="utf-8")
            status = knowledge_engine.revision_status(str(td), fetch=False)
            self.assertFalse(status["xp_parity_ok"])

    def test_offline_fetch_is_graceful(self):
        status = knowledge_engine.revision_status(str(ROOT), fetch=False)
        self.assertIsInstance(status, dict)
        self.assertIn("findings", status)


class TestHealerEngine(unittest.TestCase):
    def test_corrupt_state_backed_up_and_reset(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, ".mind_state.json").write_text("{oops", encoding="utf-8")
            result = healer.heal(td)
            self.assertTrue(any("reset corrupt" in a
                                for a in result["actions"]))
            self.assertEqual(MindState(td).load(), {})

    def test_stale_tmp_removed_fresh_kept(self):
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td, "runs")
            runs.mkdir(exist_ok=True)
            stale = runs / "old.tmp"
            stale.write_text("x", encoding="utf-8")
            old = time.time() - 7200
            os.utime(stale, (old, old))
            fresh = runs / "new.tmp"
            fresh.write_text("x", encoding="utf-8")
            result = healer.heal(td)
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(any("stale tmp" in a for a in result["actions"]))

    def test_dry_run_touches_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td, ".mind_state.json")
            bad.write_text("{oops", encoding="utf-8")
            healer.heal(td, dry_run=True)
            self.assertTrue(bad.exists())


class TestBuilderEngine(unittest.TestCase):
    def test_compile_all_clean(self):
        result = builder.compile_all(str(ROOT))
        self.assertTrue(result["ok"], result["output"][-400:])


class TestSentinel(unittest.TestCase):
    def test_score_regression_alert(self):
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td, "runs")
            runs.mkdir(parents=True)
            marker = runs / "sentinel_marks.json"
            marker.write_text('{"wc_xp_best": 500}', encoding="utf-8")
            with open(runs / "wc_xp_best.json", "w") as f:
                json.dump({"score": 40}, f)
            s = sentinel.Sentinel(td, MindState(td))
            alerts = s.sweep()
            self.assertTrue(any("collapsed" in a for a in alerts))


if __name__ == "__main__":
    unittest.main()
