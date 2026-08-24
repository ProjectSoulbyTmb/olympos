import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mind import daemon, engineer, sentinel  # noqa: E402
from mind.state import MindState  # noqa: E402


class TestNetDispatch(unittest.TestCase):
    def test_net_subcommands_reach_their_runners(self):
        with tempfile.TemporaryDirectory() as td:
            for sub, target in (
                    ("serve", "cmd_net_serve"),
                    ("gym", "cmd_net_gym"),
                    ("policy", "cmd_net_policy"),
                    ("sources", "cmd_net_sources")):
                with mock.patch.object(daemon, target,
                                       return_value=0) as m:
                    rc = daemon.main(["--root", td, "net", sub,
                                      "--port", "5000"])
                    self.assertEqual((rc, m.called), (0, True), sub)

    def test_bare_net_still_sweeps(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(daemon, "cmd_net",
                                   return_value=0) as m:
                daemon.main(["--root", td, "net"])
                self.assertTrue(m.called)


class TestSchedulerRunners(unittest.TestCase):
    def test_every_default_job_has_a_runner(self):
        from mind.scheduler import DEFAULT_JOBS
        for job in DEFAULT_JOBS:
            self.assertIn(job["name"], daemon.JOB_RUNNERS)

    def test_unknown_due_job_is_reported_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            st = MindState(td)
            st.save(scheduler_jobs=[
                {"name": "patrol", "every_minutes": 60},
                {"name": "mystery-job", "every_minutes": 1}])
            with mock.patch.object(daemon, "JOB_RUNNERS", {}):
                daemon.cmd_schedule(td, st, ["tick"])
            events = [e["event"] for e in st.recent(5)]
        self.assertIn("no-runner", events)

    def test_venus_job_drains(self):
        with tempfile.TemporaryDirectory() as td:
            st = MindState(td)
            with mock.patch.object(daemon, "cmd_venus",
                                   return_value=0) as m:
                daemon.JOB_RUNNERS["venus-drain"](td, st)
                self.assertTrue(m.called)


class TestSentinelMultiTask(unittest.TestCase):
    def test_watches_every_best_file(self):
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td, "runs")
            runs.mkdir(parents=True)
            marker = runs / "sentinel_marks.json"
            marker.write_text(json.dumps({"gold": 1000}),
                              encoding="utf-8")
            with open(runs / "gold_best.json", "w") as f:
                json.dump({"score": 10}, f)
            s = sentinel.Sentinel(td, MindState(td))
            alerts = s.sweep()
            self.assertTrue(any("gold best collapsed" in a
                                for a in alerts))
            marks = json.loads(marker.read_text())
            self.assertEqual(marks.get("gold"), 1000)


class TestProposalPipeline(unittest.TestCase):
    PROPOSAL = """# MIND engineering proposal

```diff
--- a/notes.md
+++ b/notes.md
@@ -0,0 +1 @@
+hello from a proposal
```
"""

    def test_parse_patch_extracts_diff(self):
        patch = engineer.parse_patch(self.PROPOSAL)
        self.assertIsNotNone(patch)
        self.assertIn("+hello from a proposal", patch)
        self.assertTrue(patch.lstrip().startswith("---"))

    def test_parse_patch_rejects_prose(self):
        self.assertIsNone(engineer.parse_patch(
            "just some text, no diff here"))

    def test_apply_dry_run_touches_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess_git_init(td)
            Path(td, "notes.md").write_text("", encoding="utf-8")
            _git(td, "add", "-A")
            _git(td, "commit", "-m", "init")
            p = Path(td, "mind", "proposals", "p.md")
            p.parent.mkdir(parents=True)
            p.write_text(self.PROPOSAL, encoding="utf-8")
            result = engineer.apply_proposal(td, str(p), dry_run=True)
            self.assertTrue(result.get("ok"))
            self.assertTrue(result.get("dry_run"))
            self.assertEqual(Path(td, "notes.md").read_text(), "")

    def test_apply_then_verify_revert_on_red_tests(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess_git_init(td)
            Path(td, "notes.md").write_text("", encoding="utf-8")
            tests = Path(td, "tests")
            tests.mkdir()
            (tests / "test_always_fails.py").write_text(
                "def test_x():\n    assert False\n", encoding="utf-8")
            _git(td, "add", "-A")
            _git(td, "commit", "-m", "init")
            p = Path(td, "mind", "proposals", "p.md")
            p.parent.mkdir(parents=True)
            p.write_text(self.PROPOSAL, encoding="utf-8")
            result = engineer.apply_proposal(td, str(p), verify=True)
            self.assertFalse(result.get("ok"))
            self.assertTrue(result.get("reverted"))
            self.assertEqual(Path(td, "notes.md").read_text(), "")


def _git(cwd, *args):
    import subprocess
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, env=env)


def subprocess_git_init(td):
    _git(td, "init", "-q")
    _git(td, "config", "user.email", "t@t")
    _git(td, "config", "user.name", "t")


if __name__ == "__main__":
    unittest.main()
