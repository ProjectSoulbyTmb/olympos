import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mind import engineer, moderator, releaser  # noqa: E402
from mind.state import MindState  # noqa: E402


class TestState(unittest.TestCase):
    def test_roundtrip_and_log(self):
        with tempfile.TemporaryDirectory() as td:
            st = MindState(td)
            st.save(content_hash="abc123")
            self.assertEqual(st.load()["content_hash"], "abc123")
            self.assertIn("checked", st.load())
            st.log("moderator", "test-event", "detail here")
            recent = st.recent()
            self.assertEqual(recent[-1]["event"], "test-event")
            self.assertTrue(Path(td, "runs", "mind_log.jsonl").exists())

    def test_corrupt_state_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, ".mind_state.json").write_text("{broken", encoding="utf-8")
            self.assertEqual(MindState(td).load(), {})


class TestModerator(unittest.TestCase):
    def test_world_integrity_on_real_constants(self):
        findings = moderator.check_world_integrity(str(ROOT))
        critical = [f for f in findings if f.severity == "critical"]
        self.assertEqual(critical, [])

    def test_quarantine_of_corrupt_session(self):
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td, "runs", "wc_xp")
            runs.mkdir(parents=True)
            (runs / "session.json").write_text("{not json", encoding="utf-8")
            findings = moderator.sweep_sessions(td, quarantine=True)
            fixed = [f for f in findings if f.action == "auto-fixed"]
            self.assertEqual(len(fixed), 1)
            qdir = Path(td, "runs", "_quarantine")
            quarantined = list(qdir.glob("*.corrupt-*"))
            self.assertEqual(len(quarantined), 1)

    def test_freshness_missing_data(self):
        with tempfile.TemporaryDirectory() as td:
            findings = moderator.check_data_freshness(td, max_age_hours=1)
            areas = [f.area for f in findings]
            self.assertIn("data", areas)


class TestEngineer(unittest.TestCase):
    def test_run_tests_on_mini_suite(self):
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td, "tests")
            tdir.mkdir()
            (tdir / "test_ok.py").write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_pass(self):\n"
                "        self.assertTrue(True)\n", encoding="utf-8")
            result = engineer.run_tests(td, timeout=60)
            self.assertTrue(result["ok"], result["output"][-300:])
            self.assertEqual(result["ran"], 1)

    def test_diagnose_missing_module(self):
        fake = {"ok": False, "ran": 5,
                "output": "ModuleNotFoundError: No module named 'torch'"}
        advice = engineer.diagnose(fake)
        self.assertTrue(any("torch" in a["fix"] for a in advice))
        kinds = {a["kind"] for a in advice}
        self.assertIn("auto-fixable", kinds)

    def test_auto_heal_creates_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            actions = engineer.auto_heal(td)
            self.assertTrue((Path(td, "knowledge", "live")).is_dir())
            self.assertTrue(any("recreated" in a for a in actions))


class TestReleaser(unittest.TestCase):
    def test_bump_levels(self):
        self.assertEqual(releaser.bump("1.2.3", "patch"), "1.2.4")
        self.assertEqual(releaser.bump("1.2.3", "minor"), "1.3.0")
        self.assertEqual(releaser.bump("1.2", "major"), "2.0.0")

    def test_read_version_matches_pyproject(self):
        v = releaser.read_version(str(ROOT))
        parts = v.split(".")
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertTrue(p.isdigit(), p)

    def test_dry_run_touches_nothing(self):
        before = releaser.read_version(str(ROOT))
        plan = releaser.release(str(ROOT), level="patch", dry_run=True,
                                do_build=False)
        self.assertEqual(plan["target"], releaser.bump(before, "patch"))
        self.assertTrue(plan["dry_run"])
        self.assertEqual(releaser.read_version(str(ROOT)), before)


if __name__ == "__main__":
    unittest.main()
