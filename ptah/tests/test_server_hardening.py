import json
import socket
import time
import urllib.error
import urllib.request
import unittest

from ptah.llm import ScriptedLLM
from ptah.tests.test_server import ApiHarness


class TestServerRequestValidation(unittest.TestCase):
    def setUp(self):
        self.h = ApiHarness()

    def tearDown(self):
        self.h.close()

    def test_short_post_route_is_clean_json_404(self):
        req = urllib.request.Request(self.h.url("/v1"), data=b"{}",
                                     method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(caught.exception.headers["content-type"],
                         "application/json; charset=utf-8")
        self.assertEqual(json.loads(caught.exception.read())["error"],
                         "unknown route")

    def test_invalid_timeout_is_400(self):
        _, meta = self.h.request("POST", "/api/v1/conversations", {})
        status, body = self.h.request(
            "POST", f"/api/v1/conversations/{meta['id']}/messages",
            {"text": "hello", "timeout_s": "soon"})
        self.assertEqual(status, 400)
        self.assertIn("timeout_s", body["error"])

    def test_openai_messages_must_be_array(self):
        status, body = self.h.request(
            "POST", "/v1/chat/completions", {"messages": {}})
        self.assertEqual(status, 400)
        self.assertIn("messages", body["error"])

    def test_conversation_id_cannot_escape_store(self):
        status, body = self.h.request(
            "GET", "/api/v1/conversations/..%2Fmeta.json")
        self.assertEqual(status, 400)
        self.assertIn("conversation id", body["error"])

    def test_openai_stream_uses_sse_contract(self):
        req = urllib.request.Request(
            self.h.url("/v1/chat/completions"),
            data=json.dumps({"messages": [{"role": "user",
                                           "content": "hello"}],
                             "stream": True}).encode(),
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["content-type"],
                             "text/event-stream")
            wire = response.read().decode()
        self.assertIn('"object":"chat.completion.chunk"', wire)
        self.assertIn("data: [DONE]", wire)

    def test_unsupported_method_is_json(self):
        req = urllib.request.Request(self.h.url("/healthz"), method="PUT")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(caught.exception.code, 405)
        self.assertEqual(json.loads(caught.exception.read())["error"],
                         "method not allowed")

    def test_request_id_generated_when_missing(self):
        req = urllib.request.Request(self.h.url("/healthz"), method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            body = json.loads(response.read().decode())
            rid = response.headers["X-Request-ID"]
        self.assertTrue(rid.startswith("ptah-"))
        self.assertEqual(body["request_id"], rid)

    def test_request_id_preserves_safe_incoming_value(self):
        req = urllib.request.Request(
            self.h.url("/healthz"),
            headers={"X-Request-ID": "client.req-123"},
            method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            body = json.loads(response.read().decode())
            rid = response.headers["X-Request-ID"]
        self.assertEqual(rid, "client.req-123")
        self.assertEqual(body["request_id"], "client.req-123")

    def test_request_id_rejects_unsafe_incoming_value(self):
        req = urllib.request.Request(
            self.h.url("/healthz"),
            headers={"X-Request-ID": "not valid id"},
            method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            body = json.loads(response.read().decode())
            rid = response.headers["X-Request-ID"]
        self.assertNotEqual(rid, "not valid id")
        self.assertEqual(body["request_id"], rid)
        self.assertTrue(rid.startswith("ptah-"))


class TestServerAuthHeaders(unittest.TestCase):
    def setUp(self):
        self.h = ApiHarness(token="sekrit")

    def tearDown(self):
        self.h.close()

    def test_unauthorized_response_challenges_bearer(self):
        req = urllib.request.Request(self.h.url("/api/v1/conversations"),
                                     method="GET")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(caught.exception.code, 401)
        self.assertEqual(caught.exception.headers["www-authenticate"],
                         "Bearer")


class TestServerResilience(unittest.TestCase):
    def test_overload_limit_from_server_returns_503(self):
        h = ApiHarness(replies=[json.dumps({"answer": "ok"})] * 6,
                       run_delay=0.4, server_max_active_runs=1)
        try:
            _, first = h.request("POST", "/api/v1/conversations", {})
            _, second = h.request("POST", "/api/v1/conversations", {})
            status, _ = h.request(
                "POST", f"/api/v1/conversations/{first['id']}/messages",
                {"text": "one", "wait": False})
            self.assertEqual(status, 202)
            status, body = h.request(
                "POST", f"/api/v1/conversations/{second['id']}/messages",
                {"text": "two", "wait": False})
            self.assertEqual(status, 503)
            self.assertIn("overloaded", body["error"])
        finally:
            h.close()

    def test_overload_limit_from_handler_returns_503(self):
        h = ApiHarness(replies=[json.dumps({"answer": "ok"})] * 6,
                       run_delay=0.4, handler_max_active_runs=1)
        try:
            _, first = h.request("POST", "/api/v1/conversations", {})
            _, second = h.request("POST", "/api/v1/conversations", {})
            status, _ = h.request(
                "POST", f"/api/v1/conversations/{first['id']}/messages",
                {"text": "one", "wait": False})
            self.assertEqual(status, 202)
            status, body = h.request(
                "POST", f"/api/v1/conversations/{second['id']}/messages",
                {"text": "two", "wait": False})
            self.assertEqual(status, 503)
            self.assertIn("overloaded", body["error"])
        finally:
            h.close()

    def test_client_disconnect_during_waiting_response_releases_run(self):
        h = ApiHarness(replies=[json.dumps({"answer": "ok"})] * 4,
                       run_delay=0.2)
        try:
            _, meta = h.request("POST", "/api/v1/conversations", {})
            cid = meta["id"]
            payload = json.dumps({"text": "hello", "wait": True}).encode()
            sock = socket.create_connection(("127.0.0.1", h.port), timeout=5)
            try:
                request = (
                    f"POST /api/v1/conversations/{cid}/messages HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{h.port}\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Connection: close\r\n\r\n").encode("ascii") + payload
                sock.sendall(request)
            finally:
                sock.close()
            deadline = time.time() + 3
            while time.time() < deadline and cid in h.server._active:
                time.sleep(0.05)
            self.assertNotIn(cid, h.server._active)
            status, body = h.request("GET", f"/api/v1/conversations/{cid}")
            self.assertEqual(status, 200)
            self.assertNotEqual(body.get("status"), "running")
        finally:
            h.close()

    def test_request_id_context_reaches_llm(self):
        llm = ScriptedLLM([json.dumps({"answer": "ok"})])
        h = ApiHarness(llm=llm)
        try:
            _, meta = h.request("POST", "/api/v1/conversations", {})
            status, _ = h.request(
                "POST", f"/api/v1/conversations/{meta['id']}/messages",
                {"text": "hello", "wait": True},
                headers={"content-type": "application/json",
                         "X-Request-ID": "trace-123"})
            self.assertEqual(status, 200)
            self.assertEqual(llm.calls[-1]["request_id"], "trace-123")
        finally:
            h.close()
