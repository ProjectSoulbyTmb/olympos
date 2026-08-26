import os
import queue
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mind.bus import Bus
from mind.flows import parse_flows, plan
from mind.journal import Journal
from mind.snapshot import (RECORDING_STARTED, RECORDING_STOPPED,
                           SCENE_CHANGED, Snapshot, STREAM_STARTED,
                           translate_obs_event)


class TestSnapshot(unittest.TestCase):
    def test_seed_and_dict_shape(self):
        snap = Snapshot()
        snap.seed(scenes=["Live"], program="Live", preview="Live",
                  streaming=False, recording=False, obs_version="m")
        d = snap.to_dict()
        for key in ("connected", "programScene", "scenes", "streaming",
                    "recording", "updatedAt"):
            self.assertIn(key, d)

    def test_transitions_report_change_once(self):
        snap = Snapshot()
        self.assertTrue(snap.apply(STREAM_STARTED, {}))
        self.assertFalse(snap.apply(STREAM_STARTED, {}))
        self.assertTrue(snap.apply(RECORDING_STARTED, {}))

    def test_preview_scope_kept_separate(self):
        snap = Snapshot()
        snap.seed(scenes=["A", "B"], program="A", preview="B")
        snap.apply(SCENE_CHANGED, {"scope": "preview",
                                   "sceneName": "A"})
        d = snap.to_dict()
        self.assertEqual(d["programScene"], "A")
        self.assertEqual(d["previewScene"], "A")

    def test_obs_event_translation(self):
        kind, data = translate_obs_event("RecordStateChanged",
                                         {"outputActive": False})
        self.assertEqual(kind, RECORDING_STOPPED)
        self.assertIsNone(translate_obs_event("Unknown", {}))


class TestBus(unittest.TestCase):
    def test_publish_reaches_all_subscribers(self):
        bus = Bus()
        qa = bus.subscribe("a")
        qb = bus.subscribe("b")
        bus.publish("tick", {"n": 1})
        self.assertEqual(qa.get_nowait()[1]["n"], 1)
        self.assertEqual(qb.get_nowait()[1]["n"], 1)

    def test_slow_subscriber_sheds_oldest(self):
        bus = Bus(per_subscriber=2)
        q = bus.subscribe("slow")
        for i in range(5):
            bus.publish("tick", {"i": i})
        first = q.get_nowait()[1]["i"]
        self.assertEqual(first, 3)
        self.assertGreaterEqual(bus.dropped.get("slow", 0), 2)

    def test_names_unique(self):
        bus = Bus()
        bus.subscribe("x")
        with self.assertRaises(ValueError):
            bus.subscribe("x")


class TestFlows(unittest.TestCase):
    FLOWS = [
        {"id": "archive", "on": "stream_started",
         "then": [{"action": "set_recording", "state": "start"}]},
        {"id": "brb", "on": "scene_changed",
         "when": {"scene_in": ["BRB"]}, "cooldown_s": 60,
         "then": [{"action": "wait", "seconds": 2},
                  {"action": "switch_scene", "sceneName": "Live"}]},
    ]

    def test_parse_and_plan_happy_path(self):
        flows = parse_flows(self.FLOWS)
        got = plan(flows, "scene_changed",
                   {"scope": "program", "sceneName": "BRB"},
                   now=0.0, last_fired={})
        self.assertEqual([f.id for f, _ in got], ["brb"])

    def test_cooldown_blocks_then_releases(self):
        flows = parse_flows(self.FLOWS)
        fired = {}
        self.assertNotEqual(plan(flows, "scene_changed",
                                 {"scope": "program",
                                  "sceneName": "BRB"},
                                 0.0, fired), [])
        fired["brb"] = 0.0
        self.assertEqual(plan(flows, "scene_changed",
                              {"scope": "program",
                               "sceneName": "BRB"},
                              30.0, fired), [])
        self.assertNotEqual(plan(flows, "scene_changed",
                                 {"scope": "program",
                                  "sceneName": "BRB"},
                                 61.0, fired), [])

    def test_step_validation_matrix(self):
        bad_cases = [
            {"id": "1", "on": "stream_started", "then": []},
            {"id": "2", "on": "nope", "then": [
                {"action": "log", "message": "m"}]},
            {"id": "3", "on": "stream_started", "then": [
                {"action": "wait", "seconds": 9999}]},
            {"id": "4", "on": "stream_started", "then": [
                {"action": "http_get", "url": "ftp://x"}]},
            {"id": "5", "on": "stream_started", "then": [
                {"action": "set_stream", "state": "pause"}]},
        ]
        for case in bad_cases:
            with self.assertRaises(ValueError):
                parse_flows([case])


class TestJournal(unittest.TestCase):
    def test_append_read_limit_missing(self):
        j = Journal(os.path.join(tempfile.mkdtemp(), "sub", "j.jsonl"))
        j.append("control", action="switch_scene")
        j.append("flow-fired", flow="f")
        rows = j.entries()
        self.assertEqual([r["kind"] for r in rows],
                         ["control", "flow-fired"])
        self.assertEqual(len(j.entries(limit=1)), 1)
        empty = Journal(os.path.join(tempfile.mkdtemp(),
                                     "none.jsonl"))
        self.assertEqual(empty.entries(), [])

    def test_corrupt_line_skipped(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "j.jsonl")
        with open(path, "w") as fh:
            fh.write('{"kind": "ok"}\ngarbage line\n')
        j = Journal(path)
        self.assertEqual([r["kind"] for r in j.entries()], ["ok"])


if __name__ == "__main__":
    unittest.main()
