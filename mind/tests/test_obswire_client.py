import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mind.mockobs import MockObsServer
from mind.obswire import WireConn, accept_key, encode_frame
from mind.obsclient import ObsClient, ObsClientError


class FakeSock:
    def __init__(self, data):
        self._buf = data

    def recv(self, n):
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def sendall(self, data):
        pass


class TestFrames(unittest.TestCase):
    def roundtrip(self, frame):
        fin, op, payload = WireConn(FakeSock(frame)).read_frame()
        return fin, op, payload

    def test_roundtrip_small_masked(self):
        fin, op, payload = self.roundtrip(encode_frame(b"hi"))
        self.assertTrue(fin)
        self.assertEqual(op, 1)
        self.assertEqual(payload, b"hi")

    def test_extended_payload_lengths(self):
        for size in (125, 126, 65535, 70000):
            frame = encode_frame(b"x" * size, mask=False)
            _, _, payload = self.roundtrip(frame)
            self.assertEqual(len(payload), size)

    def test_close_and_ping(self):
        _, op, _ = self.roundtrip(encode_frame(b"", 0x8))
        self.assertEqual(op, 0x8)

    def test_continuation_concatenates(self):
        conn = WireConn(FakeSock(
            encode_frame(b"hel", fin=False)
            + encode_frame(b"lo", opcode=0x0)))
        self.assertEqual(conn.recv_message(), "hello")

    def test_accept_key_known_vector(self):
        self.assertEqual(accept_key("dGhlIHNhbXBsZSBub25jZQ=="),
                         "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")


class TestClientAgainstMockObs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obs = MockObsServer(password="open-sesame",
                                scenes=["Live", "BRB", "Soon"],
                                program="Live", preview="Soon")
        cls.obs.start()

    @classmethod
    def tearDownClass(cls):
        cls.obs.stop()

    def test_wrong_password_refused(self):
        client = ObsClient("127.0.0.1", self.obs.port,
                           password="wrong", timeout=3.0)
        with self.assertRaises(ObsClientError):
            client.connect()
        self.assertIsNone(client.conn)

    def test_full_session(self):
        client = ObsClient("127.0.0.1", self.obs.port,
                           password="open-sesame")
        try:
            info = client.connect()
            self.assertTrue(client.connected)

            version = client.call("GetVersion")
            self.assertIn("obsWebSocketVersion", version)

            scenes = client.call("GetSceneList")
            self.assertEqual(scenes["currentProgramSceneName"],
                             "Live")
            self.assertEqual(len(scenes["scenes"]), 3)

            status = client.call("GetStreamStatus")
            self.assertIn("outputActive", status)

            client.call("SetCurrentProgramScene",
                        {"sceneName": "BRB"})
            event = client.poll(timeout=2.0)
            self.assertIsNotNone(event)
            kind, data = event
            self.assertEqual(kind, "CurrentProgramSceneChanged")
            self.assertEqual(data["sceneName"], "BRB")

            with self.assertRaises(ObsClientError):
                client.call("No.Such.RequestType")

            client.call("StartStream")
            kinds = set()
            while True:
                got = client.poll(timeout=1.5)
                if got is None:
                    break
                kinds.add(got[0])
            self.assertIn("StreamStateChanged", kinds)
        finally:
            client.close()
        self.assertFalse(client.connected)

    def test_unreachable_target_raises(self):
        dead = ObsClient("127.0.0.1", port=1, timeout=1.0)
        with self.assertRaises(ObsClientError):
            dead.connect()

    def test_mockobs_event_log_grows(self):
        before = len(self.obs.event_log)
        self.assertGreaterEqual(before, 2)


if __name__ == "__main__":
    unittest.main()
