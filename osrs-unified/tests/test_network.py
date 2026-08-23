import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mind import network  # noqa: E402
from mind.state import MindState  # noqa: E402


class TestNetworkEngine(unittest.TestCase):
    def setUp(self):
        self._old_backoff = network.RETRY_BACKOFF_S
        network.RETRY_BACKOFF_S = 0
        self.td = tempfile.TemporaryDirectory()
        self.root = self.td.name
        self.state = MindState(self.root)

    def tearDown(self):
        network.RETRY_BACKOFF_S = self._old_backoff
        self.td.cleanup()

    def _sweep(self, probe_fn, dns_fn=None):
        dns_fn = dns_fn or (lambda host: {"ok": True,
                                          "addresses": ["93.184.216.34"]})
        return network.sweep(self.root, self.state, probe_fn=probe_fn,
                             dns_fn=dns_fn, retries=0)

    def test_registry_merge_from_state_overrides_defaults(self):
        st = MindState(self.root)
        st.save(net_endpoints=[{"name": "wikipedia-api",
                                "url": "https://test.local/api",
                                "role": "test"}])
        eps = network.load_endpoints(self.root, st)
        wiki = [e for e in eps if e["name"] == "wikipedia-api"][0]
        self.assertEqual(wiki["url"], "https://test.local/api")
        self.assertTrue(any(e["name"] == "github-api" for e in eps))

    def test_classifies_healthy_degraded_and_down(self):
        self.assertEqual(network._classify(120, None), "healthy")
        self.assertEqual(network._classify(4000, None), "degraded")
        self.assertEqual(network._classify(1600, None), "slow")
        self.assertEqual(network._classify(None, None), "down")

    def test_sweep_reports_down_endpoint_without_raising(self):
        report = self._sweep(lambda url, timeout: (False, None))
        self.assertEqual(report["down"], len(report["endpoints"]))
        self.assertGreater(len(report["alerts"]), 0)
        self.assertTrue(Path(self.root, "runs", "net_report.json").exists())

    def test_retry_then_success_counts_as_ok(self):
        calls = {"n": 0}

        def flaky(url, timeout):
            calls["n"] += 1
            return (calls["n"] >= 2, 200)

        result = network.probe_url("https://example.invalid/",
                                   retries=3, probe_fn=flaky)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(calls["n"], 2)

    def test_latency_history_enables_spike_detection(self):
        fast = lambda url, timeout: (True, 200)  # noqa: E731
        self._sweep(fast)
        self._sweep(fast)
        hist_path = Path(self.root, "runs", "net_state.json")
        hist = json.loads(hist_path.read_text(encoding="utf-8"))
        self.assertTrue(any(v for v in hist.values()))
        # A probe far above both the rolling baseline and the warn floor
        # must classify as a spike.
        baseline = hist["github-api"][-1]
        self.assertEqual(
            network._classify(max(network.LATENCY_WARN_MS + 1,
                                  int((baseline or 100) * 3)), baseline),
            "spike")

    def test_heal_suggestions_offline_mode_and_proxy(self):
        report = {"at": "", "endpoints": [{"name": "x", "url": "u",
                                           "status": "down",
                                           "dns_ok": False}],
                  "healthy": 0, "degraded": 0, "down": 1,
                  "egress": {"http_proxy": False, "https_proxy": True,
                             "no_proxy": False},
                  "alerts": []}
        tips = network.heal_suggestions(report)
        self.assertTrue(any("offline mode" in t for t in tips))
        self.assertTrue(any("DNS failure" in t for t in tips))
        self.assertTrue(any("proxy" in t for t in tips))


if __name__ == "__main__":
    unittest.main()
