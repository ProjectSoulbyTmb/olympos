import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ptah.llm import LLM, LLMConfig, LLMError, ScriptedLLM


class TestScriptedLLM(unittest.TestCase):
    def test_replies_in_order_then_exhausts(self):
        brain = ScriptedLLM(["a", "b"])
        self.assertEqual(brain.complete("s", []).text, "a")
        self.assertEqual(brain.complete("s", []).text, "b")
        with self.assertRaises(LLMError):
            brain.complete("s", [])

    def test_records_calls(self):
        brain = ScriptedLLM(["x"])
        brain.complete("sys", [{"role": "user", "content": "hi"}])
        self.assertEqual(brain.calls[0]["system"], "sys")
        self.assertEqual(brain.calls[0]["messages"][0]["content"], "hi")


class _StubHandler(BaseHTTPRequestHandler):
    behavior = {"mode": "fail-then-ok", "hits": 0}

    def log_message(self, *a):
        pass

    def do_POST(self):                     # noqa: N802
        self.behavior["hits"] += 1
        length = int(self.headers.get("content-length", 0))
        self.rfile.read(length)
        mode = self.behavior["mode"]
        if mode == "always-500" or (mode == "fail-then-ok"
                                    and self.behavior["hits"] < 2):
            blob = json.dumps({"error": "boom"}).encode()
            self.send_response(500)
        elif mode == "auth":
            blob = json.dumps({"error": {"message": "bad key"}}).encode()
            self.send_response(401)
        else:
            payload = {
                "model": "stub-1",
                "choices": [{"message": {"content": "{\"answer\": \"ok\"}"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }
            blob = json.dumps(payload).encode()
            self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)


class TestRetryTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def make(self, **kw):
        cfg = LLMConfig(provider="openai", model="stub-1", api_key="k",
                        base_url=self.base, backoff_base_s=0.01,
                        max_retries=3, timeout_s=5)
        for k, v in kw.items():
            setattr(cfg, k, v)
        return LLM(cfg)

    def test_retry_on_500_then_success(self):
        _StubHandler.behavior.update({"mode": "fail-then-ok", "hits": 0})
        reply = self.make().complete("sys", [{"role": "user",
                                              "content": "go"}])
        self.assertEqual(reply.text, '{"answer": "ok"}')
        self.assertEqual(reply.usage, {"input": 11, "output": 7})
        self.assertGreaterEqual(_StubHandler.behavior["hits"], 2)

    def test_gives_up_after_max_retries(self):
        _StubHandler.behavior.update({"mode": "always-500", "hits": 0})
        with self.assertRaises(LLMError) as ctx:
            self.make(max_retries=2).complete("sys", [])
        self.assertIn("gave up", str(ctx.exception))
        # 1 initial + 2 retries
        self.assertEqual(_StubHandler.behavior["hits"], 3)

    def test_auth_error_fails_fast_without_retry(self):
        _StubHandler.behavior.update({"mode": "auth", "hits": 0})
        with self.assertRaises(LLMError) as ctx:
            self.make().complete("sys", [])
        self.assertEqual(ctx.exception.kind, "auth")
        self.assertEqual(_StubHandler.behavior["hits"], 1)

    def test_unknown_provider_rejected(self):
        cfg = LLMConfig(provider="clairvoyant")
        with self.assertRaises(LLMError):
            LLM(cfg)


if __name__ == "__main__":
    unittest.main()
