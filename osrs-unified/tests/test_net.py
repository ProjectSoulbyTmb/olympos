import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mind.net.channel import ChannelClient, MindChannelServer  # noqa: E402
from mind.net.gym import GymServer  # noqa: E402
from mind.net.policy import NetPolicy  # noqa: E402


class TestPolicy(unittest.TestCase):
    def _policy(self):
        with tempfile_dir() as td:
            pass
        return None

    def test_default_allowlist_allows_osrs_denies_other(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = NetPolicy(td)
            ok, _ = p.check_outbound("oldschool.runescape.wiki", 443)
            self.assertTrue(ok)
            ok, reason = p.check_outbound("evil.example.com", 443)
            self.assertFalse(ok)
            self.assertIn("allowlist", reason)

    def test_rate_limit_blocks_burst(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = NetPolicy(td)
            p.config["rate_limit_min_interval_s"]["*"] = 60.0
            ok1, _ = p.check_outbound("prices.runescape.wiki", 443)
            ok2, reason = p.check_outbound("prices.runescape.wiki", 443)
            self.assertTrue(ok1)
            self.assertFalse(ok2)
            self.assertIn("rate limited", reason)

    def test_listener_rules(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = NetPolicy(td)
            self.assertTrue(p.check_listener("127.0.0.1", 5731)[0])
            ok, _ = p.check_listener("127.0.0.1", 9999)
            self.assertFalse(ok)
            p.allow_listener("127.0.0.1", 9999)
            self.assertTrue(p.check_listener("127.0.0.1", 9999)[0])

    def test_guarded_urlopen_denies_nonallowlisted(self):
        import tempfile
        from mind.net.policy import guarded_urlopen
        with tempfile.TemporaryDirectory() as td:
            p = NetPolicy(td)
            with self.assertRaises(PermissionError):
                guarded_urlopen(p, "http://evil.example.com/x")


class TestLiveChannel(unittest.TestCase):
    def test_roundtrip_and_bus_spool(self):
        import tempfile
        with tempfile.TemporaryDirectory(
                ignore_cleanup_errors=True) as td:
            server = MindChannelServer(td, host="127.0.0.1", port=0)
            port = server.start()
            try:
                client_a = ChannelClient("127.0.0.1", port)
                client_b = ChannelClient("127.0.0.1", port)
                time.sleep(0.05)
                client_a.send("thoth.hello", {"msg": "hi"}, source="thoth")
                got = client_b.recv(timeout=5)
                self.assertEqual(got["type"], "thoth.hello")
                self.assertEqual(got["payload"]["msg"], "hi")
                self.assertEqual(got["from"], "thoth")
                spooled = server.bus.pending(type_="thoth.hello")
                self.assertEqual(len(spooled), 1)
                ack = client_b.send("mind.ack", {"ok": True})
                self.assertIn("id", ack)
                for c in (client_a, client_b):
                    c.close()
            finally:
                server.stop()

    def test_policy_blocks_disallowed_bind(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = NetPolicy(td)
            server = MindChannelServer(td, host="127.0.0.1", port=12345,
                                       policy=p)
            with self.assertRaises(PermissionError):
                server.start()


class TestGymServer(unittest.TestCase):
    def test_client_session_over_socket(self):
        import tempfile
        from rsps_adapter.env_rsps import RspsPvpEnv
        with tempfile.TemporaryDirectory() as td:
            server = GymServer(host="127.0.0.1", port=43594,
                               policy=NetPolicy(td))
            port = server.start()
            try:
                env = RspsPvpEnv("127.0.0.1", port, timeout=10)
                obs_a, obs_b = env.reset()
                self.assertEqual(obs_a.shape[0], 12)
                done = False
                steps = 0
                while not done and steps < 200:
                    mask_a, _mask_b = env.legal_mask()
                    act = int(mask_a.argmax())
                    next_a, next_b, r_a, r_b, outcome, done = env.step(
                        act, act)
                    steps += 1
                self.assertLess(steps, 201)
                env.close()
                self.assertGreaterEqual(server.sessions_served, 1)
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
