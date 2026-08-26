import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mind import __version__
from mind.bus import Bus
from mind.surfaces import (EventsSurface, RecordingControlSurface,
                           Registry, Request, Response,
                           SceneControlSurface, StatusSurface,
                           HealthSurface, StreamControlSurface,
                           Surface, build_server)


class EchoSurface(Surface):
    name = "echo"
    route = "/echo"
    methods = ("POST",)

    def handle(self, request):
        return Response.json({"path": request.path,
                              "q": request.query,
                              "body": request.json()})


class BoomSurface(Surface):
    name = "boom"
    route = "/boom"
    methods = ("GET",)

    def handle(self, request):
        raise RuntimeError("surface crashed")


def _serve(*surfaces):
    reg = Registry()
    for s in surfaces:
        reg.register(s)
    server = build_server(reg, "127.0.0.1", 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.02},
                              daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


def _fetch(url, data=None, method=None):
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


class TestRegistry(unittest.TestCase):
    def test_exact_match_routing(self):
        reg = Registry()
        echo = EchoSurface()
        reg.register(echo)
        self.assertIs(reg.resolve("POST", "/echo"), echo)
        self.assertIsNone(reg.resolve("GET", "/echo"))
        self.assertIsNone(reg.resolve("POST", "/echo/x"))

    def test_duplicate_route_refused(self):
        reg = Registry()
        reg.register(EchoSurface())
        with self.assertRaises(ValueError):
            reg.register(EchoSurface())

    def test_describe_lists_surfaces(self):
        reg = Registry()
        reg.register(HealthSurface(__version__))
        self.assertEqual(len(reg.describe()), 1)


class TestHttpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base = _serve(
            EchoSurface(), BoomSurface(),
            StatusSurface(_FakeSnapshot()),
            HealthSurface(__version__))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_roundtrip_with_query_and_body(self):
        status, body = _fetch(self.base + "/echo?x=1",
                              data=b'{"a": [1]}')
        parsed = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["q"], {"x": "1"})
        self.assertEqual(parsed["body"], {"a": [1]})

    def test_unknown_route_404_text_and_api_json(self):
        status, body = _fetch(self.base + "/nope")
        self.assertEqual(status, 404)
        status, body = _fetch(self.base + "/api/nope")
        self.assertEqual(status, 404)
        self.assertIn("not found", body)

    def test_crashing_surface_answers_500(self):
        status, _ = _fetch(self.base + "/boom")
        self.assertEqual(status, 500)

    def test_bad_json_is_400(self):
        status, _ = _fetch(self.base + "/echo", data=b"{oops")
        self.assertEqual(status, 400)

    def test_status_and_health(self):
        _, body = _fetch(self.base + "/api/status")
        self.assertTrue(json.loads(body)["connected"])
        _, body = _fetch(self.base + "/healthz")
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], __version__)


class _FakeSnapshot:
    def to_dict(self):
        return {"connected": True}


class TestControlSurfaces(unittest.TestCase):
    def _post(self, surface, path, raw):
        return surface.handle(Request("POST", path, {}, {}, raw, ""))

    def test_scene_validation_and_success(self):
        log = []

        def controller(action, data):
            log.append((action, data))
            return True, "switched"

        surf = SceneControlSurface(controller)
        good = self._post(surf, "/api/scene",
                          b'{"sceneName": "Live"}')
        self.assertEqual(good.status, 200)
        self.assertIn('"ok": true', good.body.decode())
        self.assertEqual(log[-1], ("switch_scene",
                                   {"sceneName": "Live"}))
        bad = self._post(surf, "/api/scene", b'{"sceneName": 7}')
        self.assertIn('"ok": false', bad.body.decode())
        junk = self._post(surf, "/api/scene", b'"just a string"')
        self.assertEqual(junk.status, 400)

    def test_missing_controller_is_503(self):
        surf = SceneControlSurface(None)
        resp = self._post(surf, "/api/scene", b'{"sceneName": "A"}')
        self.assertEqual(resp.status, 503)

    def test_stream_and_recording_validation(self):
        for surf in (StreamControlSurface(lambda a, d: (True, "x")),
                     RecordingControlSurface(lambda a, d: (True, "x"))):
            good = self._post(surf, surf.route, b'{"state": "start"}')
            self.assertIn('"ok": true', good.body.decode())
            bad = self._post(surf, surf.route, b'{"state": "pause"}')
            self.assertIn('"ok": false', bad.body.decode())

    def test_controller_exception_is_500(self):
        def exploding(action, data):
            raise ValueError("nope")

        surf = StreamControlSurface(exploding)
        resp = self._post(surf, "/api/stream", b'{"state": "start"}')
        self.assertEqual(resp.status, 500)


class TestEventsSurface(unittest.TestCase):
    def test_sse_frames_and_cleanup(self):
        bus = Bus()
        surf = EventsSurface(bus, heartbeat_seconds=0.05)
        response = surf.handle(Request("GET", "/api/events", {},
                                       {}, b"", ""))
        chunks = response.chunks
        self.assertEqual(next(chunks), b"retry: 2000\n\n")
        bus.publish("scene_changed", {"sceneName": "Live"})
        self.assertEqual(
            next(chunks).decode(),
            'event: scene_changed\ndata: {"sceneName": "Live"}\n\n')
        chunks.close()
        self.assertEqual(bus.subscriber_names(), [])


if __name__ == "__main__":
    unittest.main()
