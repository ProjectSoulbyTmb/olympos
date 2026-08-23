import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mind.bus import EventBus  # noqa: E402
from mind.venus_link import drain, _run_action  # noqa: E402


class FakeState:
    """Minimal MindState stand-in: records log calls, prints nothing."""

    def __init__(self):
        self.calls = []

    def log(self, component, action, detail=""):
        self.calls.append((component, action, str(detail)))


class TestVenusLink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.bus = EventBus(self.root)
        self.state = FakeState()

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_does_not_consume(self):
        self.bus.publish("venus.request", {"action": "status"}, source="venus")
        summary = drain(self.root, self.state, execute=False, bus=self.bus)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["executed"], 0)
        self.assertEqual(len(self.bus.pending(type_="venus.request")), 1)

    def test_status_request_completes_ok_with_output(self):
        from mind import daemon
        orig = daemon.cmd_status
        daemon.cmd_status = lambda root, state: print("mind ok")
        try:
            eid = self.bus.publish("venus.request",
                                   {"action": "status"}, source="venus")
            summary = drain(self.root, self.state, execute=True,
                            bus=self.bus)
        finally:
            daemon.cmd_status = orig
        self.assertEqual(summary["executed"], 1)
        archived = json.loads(Path(self.bus.archive, f"{eid}.json").read_text(encoding="utf-8"))
        self.assertEqual(archived["status"], "done")
        self.assertTrue(archived["result"]["ok"])
        self.assertIn("mind ok", archived["result"]["output"])
        self.assertEqual(len(self.bus.pending()), 0)
        self.assertTrue(any(c[1] == "request-done" for c in self.state.calls))

    def test_unknown_action_fails_envelope_without_raising(self):
        eid = self.bus.publish("venus.request", {"action": "self_destruct"}, source="venus")
        summary = drain(self.root, self.state, execute=True, bus=self.bus)
        self.assertEqual(summary["executed"], 1)
        archived = json.loads(Path(self.bus.archive, f"{eid}.json").read_text(encoding="utf-8"))
        self.assertEqual(archived["status"], "failed")
        self.assertIn("unknown action", archived["result"]["output"])

    def test_release_refused_without_explicit_consent(self):
        eid = self.bus.publish("venus.request",
                               {"action": "release", "args": {}},
                               source="venus")
        drain(self.root, self.state, execute=True, bus=self.bus)
        archived = json.loads(Path(self.bus.archive, f"{eid}.json").read_text(encoding="utf-8"))
        self.assertEqual(archived["status"], "failed")
        self.assertIn("refused", archived["result"]["output"])

    def test_run_action_reports_errors_as_results(self):
        ok, output = _run_action(self.root, self.state, "metrics", {})
        # metrics may succeed or fail depending on runs/ contents; either way
        # it must return a tuple and never raise.
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(output, str)

    def test_output_is_tailed_to_limit(self):
        ok, output = _run_action(self.root, self.state, "status", {})
        if ok:
            self.assertLessEqual(len(output), 800)


    def test_thoth_sourced_requests_are_drained(self):
        """Federation: the operator kernel can dispatch repair sweeps."""
        from mind import daemon
        orig = daemon.cmd_net
        daemon.cmd_net = lambda root, state, loop=0: print("net sweep ok")
        try:
            eid = self.bus.publish("venus.request",
                                   {"action": "net", "args": {}},
                                   source="thoth")
            summary = drain(self.root, self.state, execute=True,
                            bus=self.bus)
        finally:
            daemon.cmd_net = orig
        self.assertEqual(summary["executed"], 1)
        archived = json.loads(
            Path(self.bus.archive, f"{eid['id'] if isinstance(eid, dict) else eid}.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(archived["status"], "done")

    def test_consent_gates_apply_to_thoth_source_too(self):
        """A thoth-sourced release is still refused without consent."""
        eid = self.bus.publish("venus.request",
                               {"action": "release", "args": {}},
                               source="thoth")
        drain(self.root, self.state, execute=True, bus=self.bus)
        archived = json.loads(Path(self.bus.archive, f"{eid}.json").read_text(encoding="utf-8"))
        self.assertEqual(archived["status"], "failed")
        self.assertIn("refused", archived["result"]["output"])


if __name__ == "__main__":
    unittest.main()