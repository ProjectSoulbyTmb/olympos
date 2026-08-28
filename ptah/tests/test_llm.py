import json
from io import BytesIO
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from ptah.llm import (LLM, LLMConfig, LLMError, Reply, ScriptedLLM,
                      _parse_anthropic_stream, _parse_openai_stream)
from ptah.request_context import bind_request_context


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

    def test_reply_surface_has_usage_and_latency(self):
        brain = ScriptedLLM([Reply("x", usage={"prompt_tokens": 2,
                                               "completion_tokens": 3})])
        reply = brain.complete("sys", [])
        self.assertEqual(reply.usage, {"input": 2, "output": 3})
        self.assertIsInstance(reply.latency_s, float)
        self.assertGreaterEqual(reply.latency_s, 0)

    def test_stream_has_same_reply_surface(self):
        parts = list(ScriptedLLM(["hello"]).stream("sys", []))
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].text, "hello")


class TestStreaming(unittest.TestCase):
    def test_openai_sse_text_and_tool_call_are_normalized(self):
        payload = "\n\n".join([
            'data: {"model":"stream-1","choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo","tool_calls":['
            '{"index":0,"id":"c1","function":{"name":"lookup",'
            '"arguments":"{\\"q\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":['
            '{"index":0,"function":{"arguments":"\\"x\\"}"}}]},'
            '"finish_reason":"tool_calls"}]}',
            'data: {"usage":{"prompt_tokens":4,"completion_tokens":3},'
            '"choices":[]}',
            "data: [DONE]",
        ]).encode()
        parts = list(_parse_openai_stream(BytesIO(payload), "fallback"))
        self.assertEqual("".join(part.text for part in parts), "Hello")
        final = parts[-1]
        self.assertEqual(final.model, "stream-1")
        self.assertEqual(final.finish_reason, "tool_calls")
        self.assertEqual(final.usage, {"input": 4, "output": 3})
        self.assertEqual(final.tool_calls[0]["name"], "lookup")
        self.assertEqual(final.tool_calls[0]["arguments"], {"q": "x"})

    def test_anthropic_events_are_normalized(self):
        payload = "\n\n".join([
            "\n".join(('event: message_start',
                       'data: {"type":"message_start","message":'
                       '{"model":"claude","usage":{"input_tokens":5}}}')),
            "\n".join(('event: content_block_delta',
                       'data: {"type":"content_block_delta","delta":'
                       '{"type":"text_delta","text":"Hi"}}')),
            "\n".join(('event: content_block_start',
                       'data: {"type":"content_block_start","index":1,'
                       '"content_block":{"type":"tool_use","id":"t1",'
                       '"name":"run","input":{}}}')),
            "\n".join(('event: content_block_delta',
                       'data: {"type":"content_block_delta","index":1,'
                       '"delta":{"type":"input_json_delta",'
                       '"partial_json":"{\\"ok\\":true}"}}')),
            "\n".join(('event: message_delta',
                       'data: {"type":"message_delta","delta":'
                       '{"stop_reason":"tool_use"},"usage":'
                       '{"output_tokens":2}}')),
            "",
        ]).encode()
        parts = list(_parse_anthropic_stream(BytesIO(payload), "fallback"))
        self.assertEqual("".join(part.text for part in parts), "Hi")
        final = parts[-1]
        self.assertEqual(final.model, "claude")
        self.assertEqual(final.finish_reason, "tool_use")
        self.assertEqual(final.usage, {"input": 5, "output": 2})
        self.assertEqual(final.tool_calls[0]["arguments"], {"ok": True})

    def test_openai_stream_without_done_raises_bad_response(self):
        payload = (
            'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
        ).encode()
        stream = _parse_openai_stream(BytesIO(payload), "fallback")
        self.assertEqual(next(stream).text, "Hi")
        with self.assertRaises(LLMError) as ctx:
            next(stream)
        self.assertEqual(ctx.exception.kind, "bad_response")
        self.assertIn("[DONE]", str(ctx.exception))

    def test_anthropic_message_stop_without_done_is_accepted(self):
        payload = "\n\n".join([
            "\n".join(('event: message_start',
                       'data: {"type":"message_start","message":'
                       '{"model":"claude","usage":{"input_tokens":2}}}')),
            "\n".join(('event: content_block_delta',
                       'data: {"type":"content_block_delta","delta":'
                       '{"type":"text_delta","text":"Hi"}}')),
            "\n".join(('event: message_delta',
                       'data: {"type":"message_delta","delta":'
                       '{"stop_reason":"end_turn"},"usage":'
                       '{"output_tokens":1}}')),
            "\n".join(('event: message_stop',
                       'data: {"type":"message_stop"}')),
            "",
        ]).encode()
        parts = list(_parse_anthropic_stream(BytesIO(payload), "fallback"))
        self.assertEqual("".join(part.text for part in parts), "Hi")
        final = parts[-1]
        self.assertEqual(final.model, "claude")
        self.assertEqual(final.finish_reason, "end_turn")
        self.assertEqual(final.usage, {"input": 2, "output": 1})

    def test_non_stream_parse_normalizes_tool_calls(self):
        brain = LLM(LLMConfig(provider="openai", model="stub",
                              base_url="http://127.0.0.1:1"))
        raw = json.dumps({
            "choices": [{"message": {
                "content": "",
                "function_call": {"name": "old", "arguments": '{"x": 1}'}
            }}]
        }).encode()
        reply = brain._parse(raw)
        self.assertEqual(reply.tool_calls[0]["name"], "old")
        self.assertEqual(reply.tool_calls[0]["arguments"], {"x": 1})


class _StubHandler(BaseHTTPRequestHandler):
    behavior = {"mode": "fail-then-ok", "hits": 0}

    def log_message(self, *a):
        pass

    def do_POST(self):                     # noqa: N802
        self.behavior["hits"] += 1
        length = int(self.headers.get("content-length", 0))
        self.behavior["path"] = self.path
        self.behavior["payload"] = json.loads(self.rfile.read(length).decode())
        self.behavior["authorization"] = self.headers.get("authorization")
        self.behavior["x_request_id"] = self.headers.get("x-request-id")
        mode = self.behavior["mode"]
        if mode == "stream-bad-then-ok" and self.behavior["payload"].get("stream"):
            if self.behavior["hits"] == 1:
                blob = b"data: {bad json}\n\n"
            else:
                blob = b"\n\n".join((
                    b'data: {"model":"stream-1","choices":[{"delta":{"content":"ok"}}]}',
                    b"data: [DONE]")) + b"\n\n"
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
            return
        if mode == "stream-partial-then-bad" and \
                self.behavior["payload"].get("stream"):
            blob = b"\n\n".join((
                b'data: {"choices":[{"delta":{"content":"ok"}}]}',
                b"data: {bad json}")) + b"\n\n"
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
            return
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

    def test_local_alias_uses_one_endpoint_and_optional_key(self):
        _StubHandler.behavior.update({"mode": "ok", "hits": 0})
        cfg = LLMConfig(provider="ollama", model="local-1",
                        base_url=self.base, max_retries=0, timeout_s=5)
        reply = LLM(cfg).complete("sys", [{"role": "user", "content": "go"}])
        self.assertEqual(reply.text, '{"answer": "ok"}')
        self.assertEqual(_StubHandler.behavior["path"], "/v1/chat/completions")
        self.assertEqual(_StubHandler.behavior["payload"]["model"], "local-1")
        self.assertIsNone(_StubHandler.behavior["authorization"])
        self.assertEqual(reply.usage, {"input": 11, "output": 7})
        self.assertIsInstance(reply.latency_s, float)

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

    def test_malformed_stream_retries_and_recovers(self):
        _StubHandler.behavior.update({"mode": "stream-bad-then-ok", "hits": 0})
        parts = list(self.make(max_retries=1).stream("sys", []))
        self.assertEqual("".join(part.text for part in parts), "ok")
        self.assertGreaterEqual(_StubHandler.behavior["hits"], 2)

    def test_malformed_stream_after_output_fails_without_retry(self):
        _StubHandler.behavior.update({"mode": "stream-partial-then-bad",
                                      "hits": 0})
        stream = self.make(max_retries=3).stream("sys", [])
        self.assertEqual(next(stream).text, "ok")
        with self.assertRaises(LLMError) as ctx:
            next(stream)
        self.assertEqual(ctx.exception.kind, "bad_response")
        self.assertEqual(_StubHandler.behavior["hits"], 1)

    def test_request_context_adds_x_request_id_header(self):
        _StubHandler.behavior.update({"mode": "ok", "hits": 0})
        with bind_request_context("req-abc"):
            self.make().complete("sys", [{"role": "user", "content": "go"}])
        self.assertEqual(_StubHandler.behavior["x_request_id"], "req-abc")

    def test_unknown_provider_rejected(self):
        cfg = LLMConfig(provider="clairvoyant")
        with self.assertRaises(LLMError):
            LLM(cfg)


class TestProviderConfiguration(unittest.TestCase):
    def test_local_provider_aliases_share_openai_transport(self):
        for alias in ("ollama", "vllm", "lmstudio", "llama.cpp",
                      "llama-cpp", "llamacpp", "litellm",
                      "openai-compatible", "local"):
            with self.subTest(alias=alias):
                brain = LLM(LLMConfig(provider=alias))
                self.assertEqual(brain.transport, "openai-compatible")
                self.assertEqual(brain._endpoint().split("/chat/")[0][-3:],
                                 "/v1")
                self.assertEqual(brain._headers()["content-type"],
                                 "application/json")

    def test_full_chat_endpoint_is_not_doubled(self):
        endpoint = "http://127.0.0.1:8000/v1/chat/completions"
        brain = LLM(LLMConfig(provider="openai", base_url=endpoint))
        self.assertEqual(brain._endpoint(), endpoint)

    def test_base_endpoint_adds_chat_route_once(self):
        base = "http://127.0.0.1:8000/v1/"
        brain = LLM(LLMConfig(provider="openai", base_url=base))
        self.assertEqual(brain._endpoint(), base.rstrip("/") + "/chat/completions")

    def test_canonical_env_values_beat_backend_aliases(self):
        values = {
            "PTAH_LLM_PROVIDER": "vllm",
            "PTAH_VLLM_URL": "http://alias:8000/v1",
            "PTAH_VLLM_MODEL": "alias-model",
            "PTAH_VLLM_API_KEY": "alias-key",
            "PTAH_BASE_URL": "http://canonical:9000/v1",
            "PTAH_LLM_MODEL": "canonical-model",
            "PTAH_API_KEY": "canonical-key",
        }
        with patch.dict(os.environ, values, clear=True):
            cfg = LLMConfig.from_env()
        self.assertEqual(cfg.provider, "vllm")
        self.assertEqual(cfg.base_url, "http://canonical:9000/v1")
        self.assertEqual(cfg.model, "canonical-model")
        self.assertEqual(cfg.api_key, "canonical-key")

    def test_backend_alias_env_values_beat_defaults(self):
        values = {
            "PTAH_LLM_PROVIDER": "ollama",
            "PTAH_OLLAMA_URL": "http://127.0.0.1:9999/v1",
            "PTAH_OLLAMA_MODEL": "qwen-local",
        }
        with patch.dict(os.environ, values, clear=True):
            cfg = LLMConfig.from_env()
        self.assertEqual(cfg.base_url, values["PTAH_OLLAMA_URL"])
        self.assertEqual(cfg.model, values["PTAH_OLLAMA_MODEL"])

    def test_incomplete_stream_tool_arguments_are_ignored(self):
        payload = "\n\n".join([
            'data: {"choices":[{"delta":{"tool_calls":['
            '{"index":0,"id":"c1","function":{"name":"lookup",'
            '"arguments":"{\\"q\\":"}}]}}]}',
            "data: [DONE]",
        ]).encode()
        parts = list(_parse_openai_stream(BytesIO(payload), "fallback"))
        self.assertEqual(parts[-1].tool_calls, [])


if __name__ == "__main__":
    unittest.main()
