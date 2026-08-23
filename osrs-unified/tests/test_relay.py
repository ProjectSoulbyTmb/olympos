import io
import json
import os
import sys
import tempfile
import contextlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mind.bus import EventBus  # noqa: E402


class TestBusCore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bus = EventBus(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_publish_and_pending_roundtrip(self):
        eid = self.bus.publish("mind.status", {"findings": 0})
        pending = self.bus.pending(type_="mind.status")
        self.assertEqual(len(pending), 1)
        evt = pending[0]
        self.assertEqual(evt["id"], eid)
        self.assertEqual(evt["from"], "mind")
        self.assertEqual(evt["payload"]["findings"], 0)
        self.assertIn("at", evt)

    def test_take_marks_taken_not_queued(self):
        eid = self.bus.publish("mind.job.diagnose", {})
        self.bus.take(eid)
        self.assertEqual(self.bus.pending(), [])
        taken = json.load(open(Path(self.bus.spool, f"{eid}.json")))
        self.assertEqual(taken["status"], "taken")

    def test_complete_archives_with_result(self):
        eid = self.bus.publish("thoth.result.run", {"task": "wc_xp"},
                               source="thoth")
        self.bus.take(eid)
        self.bus.complete(eid, {"best_score": 123}, ok=True)
        self.assertEqual(self.bus.pending(), [])
        archived = self.bus.recent(5)
        self.assertTrue(any(a["id"] == eid and a["status"] == "done"
                            and a["result"]["best_score"] == 123
                            for a in archived))

    def test_fail_records_error_status(self):
        eid = self.bus.publish("mind.job.improve_strategy", {"task": "gold"})
        self.bus.fail(eid, "llm unreachable")
        recent = self.bus.recent(5)
        self.assertTrue(any(a["status"] == "failed" for a in recent))

    def test_source_filtering(self):
        self.bus.publish("x", {}, source="thoth")
        self.bus.publish("x", {}, source="mind")
        thoth_only = self.bus.pending(source="thoth")
        self.assertEqual(len(thoth_only), 1)
        self.assertEqual(thoth_only[0]["from"], "thoth")

    def test_missing_event_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.bus.take("nope_123")


class TestAgentRelayWiring(unittest.TestCase):
    def test_run_loop_publishes_result_and_injects_briefing(self):
        from agent.loop import KnowledgeBase, run_loop

        class FakeLLM:
            def __init__(self):
                self.user_prompts = []

            def chat(self, system, user):
                self.user_prompts.append(user)
                return ("```python\n"
                        "def run(game):\n"
                        "    game.walk('tree_1')\n"
                        "    while game.ticks_left() > 40:\n"
                        "        try:\n"
                        "            game.chop()\n"
                        "        except Exception:\n"
                        "            game.walk('tree_2')\n"
                        "```\n")

        with tempfile.TemporaryDirectory() as td:
            wiki = Path(td, "wiki")
            wiki.mkdir()
            (wiki / "sdk.md").write_text("# sdk\n", encoding="utf-8")
            bus = EventBus(td)
            llm = FakeLLM()
            kb = KnowledgeBase(str(wiki))
            result = run_loop(
                llm, kb,
                lambda budget: __import__("game.world", fromlist=["World"])
                .World(seed=3, tick_budget=300),
                "wc_xp", "Maximize Woodcutting experience.",
                rounds=1, tick_budget=300,
                briefing="TEST-BRIEFING-XYZ")
            self.assertFalse(result["aborted"])
            self.assertIn("TEST-BRIEFING-XYZ", llm.user_prompts[0])
            results = bus.pending(type_="thoth.result.run")
            self.assertEqual(len(results), 0)  # bench publishes, not run_loop
            self.assertGreaterEqual(result["history"][0]["score"], 25)


if __name__ == "__main__":
    unittest.main()
