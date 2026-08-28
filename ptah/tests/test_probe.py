import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import os
import sys
import subprocess
from unittest.mock import patch

from ptah import llm_probe


class _ProbeStubHandler(BaseHTTPRequestHandler):
    behavior = {"mode": "json", "hits": 0}

    def log_message(self, *a):
        return

    def do_POST(self):
        self.behavior["hits"] += 1
        length = int(self.headers.get("content-length", 0))
        payload = self.rfile.read(length).decode('utf-8') if length else ''
        self.behavior["payload"] = payload
        # capture auth headers if any (do not log secrets elsewhere)
        self.behavior["authorization"] = self.headers.get('authorization')
        self.behavior["x_api_key"] = self.headers.get('x-api-key')
        mode = self.behavior.get("mode")
        if mode == "json":
            body = json.dumps({
                "model": "stub-1",
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
            }).encode('utf-8')
            self.send_response(200)
            self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif mode == "stream":
            # send a tiny SSE stream then close
            self.send_response(200)
            self.send_header('content-type', 'text/event-stream')
            self.end_headers()
            # two events then DONE
            s = 'data: {"model":"stream-1","choices":[{"delta":{"content":"H"}}]}\n\n'
            s += 'data: {"choices":[{"delta":{"content":"i"}}]}\n\n'
            s += 'data: [DONE]\n\n'
            self.wfile.write(s.encode('utf-8'))
        elif mode == 'malformed':
            body = b'not-a-json'
            self.send_response(200)
            self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif mode == 'no_choices':
            # return JSON without a choices list to simulate malformed chat response
            body = json.dumps({
                'model': 'stub-1'
            }).encode('utf-8')
            self.send_response(200)
            self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif mode == 'stream_reject':
            # Simulate a backend that rejects stream=true with 400 but accepts non-stream
            # Inspect payload to decide behavior
            if ('"stream": true' in payload) or ('"stream":true' in payload):
                body = json.dumps({"error": "stream not supported"}).encode('utf-8')
                self.send_response(400)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                # act like json mode
                body = json.dumps({
                    "model": "stub-1",
                    "choices": [{"message": {"content": "{\"ok\": true}"}}],
                }).encode('utf-8')
                self.send_response(200)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        elif mode == 'sse_noparse':
            # return a text/event-stream that contains no JSON parsable completion event
            self.send_response(200)
            self.send_header('content-type', 'text/event-stream')
            self.end_headers()
            s = 'data: hello\n\n'
            s += 'data: [DONE]\n\n'
            self.wfile.write(s.encode('utf-8'))
        elif mode in ('http_404', 'http_501'):
            code = int(mode.rsplit('_', 1)[1])
            body = json.dumps({"error": "backend rejected request"}).encode('utf-8')
            self.send_response(code)
            self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(500)
            self.end_headers()

    def do_GET(self):
        # model inventory endpoint: respond to /v1/models or /models
        if self.path.endswith('/models'):
            # allow tests to configure returned model ids via behavior['models']
            models = self.behavior.get('models', ['stub-1'])
            # construct OpenAI-style response
            data = []
            for m in models:
                if isinstance(m, dict):
                    data.append(m)
                else:
                    data.append({'id': m})
            body = json.dumps({'data': data}).encode('utf-8')
            self.send_response(200)
            self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # otherwise, 404
        self.send_response(404)
        self.end_headers()


class TestProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), _ProbeStubHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}/v1'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_json_response_detected(self):
        _ProbeStubHandler.behavior.update({'mode': 'json', 'hits': 0})
        res = llm_probe.probe(self.base, model='x', timeout_s=2.0)
        self.assertTrue(res.reachable)
        self.assertFalse(res.can_stream)
        self.assertEqual(res.model_reported, 'stub-1')
        self.assertGreaterEqual(res.latency_s, 0)

    def test_streaming_detected(self):
        _ProbeStubHandler.behavior.update({'mode': 'stream', 'hits': 0})
        res = llm_probe.probe(self.base, model='x', timeout_s=2.0)
        self.assertTrue(res.reachable)
        self.assertTrue(res.can_stream)
        self.assertEqual(res.model_reported, 'stream-1')

    def test_malformed_response_raises(self):
        _ProbeStubHandler.behavior.update({'mode': 'malformed', 'hits': 0})
        with self.assertRaises(llm_probe.LLMProbeError):
            llm_probe.probe(self.base, model='x', timeout_s=2.0)

    def test_unreachable_raises(self):
        # pick an unlikely port (assuming nothing listening)
        with self.assertRaises(llm_probe.LLMProbeError):
            llm_probe.probe('http://127.0.0.1:65000/v1', model='x', timeout_s=1.0)

    def test_models_endpoint(self):
        _ProbeStubHandler.behavior.update({'mode': 'json', 'hits': 0, 'models': ['m1', 'm2']})
        res = llm_probe.probe(self.base, model='x', timeout_s=2.0)
        self.assertEqual(res.models, ['m1', 'm2'])

    def test_no_choices_raises(self):
        _ProbeStubHandler.behavior.update({'mode': 'no_choices', 'hits': 0})
        with self.assertRaises(llm_probe.LLMProbeError):
            llm_probe.probe(self.base, model='x', timeout_s=2.0)

    def test_remote_lookalike_rejected(self):
        # hostname that contains a loopback substring but is not loopback
        with self.assertRaises(llm_probe.LLMProbeError):
            llm_probe.probe('http://127.0.0.1.evil.com/v1', model='x', timeout_s=1.0)

    def test_no_config_no_dial(self):
        # ensure we do not implicitly dial localhost for default openai provider
        _ProbeStubHandler.behavior.update({'mode': 'json', 'hits': 0})
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(llm_probe.LLMProbeError) as cm:
                llm_probe.probe_from_env_or_args(None, None, timeout_s=0.5)
            self.assertEqual(cm.exception.kind, 'config')

    def test_anthropic_rejected(self):
        _ProbeStubHandler.behavior.update({'mode': 'json', 'hits': 0})
        with patch.dict(os.environ, {'PTAH_LLM_PROVIDER': 'anthropic'}, clear=True):
            with self.assertRaises(llm_probe.LLMProbeError) as cm:
                llm_probe.probe_from_env_or_args(None, None, timeout_s=0.5)
            self.assertEqual(cm.exception.kind, 'config')
    def test_probe_includes_auth_from_env(self):
        _ProbeStubHandler.behavior.update({'mode': 'json', 'hits': 0})
        env = {
            'PTAH_BASE_URL': self.base,
            'PTAH_API_KEY': 'k'
        }
        with patch.dict(os.environ, env, clear=True):
            res = llm_probe.probe_from_env_or_args(None, None, timeout_s=2.0)
        # server should have seen an Authorization header (any non-empty value is acceptable)
        self.assertTrue(bool(_ProbeStubHandler.behavior.get('authorization')))
        self.assertTrue(res.reachable)

    def test_cli_json_exit_code(self):
        # invoke the module as a subprocess and assert structured JSON output
        _ProbeStubHandler.behavior.update({'mode': 'json', 'hits': 0})
        proc = subprocess.run([sys.executable, '-m', 'ptah.llm_probe', '--base-url', self.base, '--json'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertEqual(out.get('base_url'), self.base)
        self.assertTrue(out.get('reachable'))

    def test_stream_rejected_falls_back(self):
        _ProbeStubHandler.behavior.update({'mode': 'stream_reject', 'hits': 0})
        res = llm_probe.probe(self.base, model='x', timeout_s=2.0)
        self.assertTrue(res.reachable)
        self.assertFalse(res.can_stream)
        self.assertEqual(res.model_reported, 'stub-1')
        self.assertGreaterEqual(_ProbeStubHandler.behavior.get('hits'), 2)

    def test_sse_no_json_raises(self):
        _ProbeStubHandler.behavior.update({'mode': 'sse_noparse', 'hits': 0})
        with self.assertRaises(llm_probe.LLMProbeError):
            llm_probe.probe(self.base, model='x', timeout_s=2.0)

    def test_repeatable_benchmark_reports_capabilities_and_measurements(self):
        _ProbeStubHandler.behavior.update({'mode': 'stream', 'hits': 0})
        report = llm_probe.benchmark_backends(
            [f"local=x@{self.base}"], runs=2, timeout_s=2.0)
        row = report["backends"][0]
        self.assertEqual(report["schema"], "ptah-backend-benchmark-v1")
        self.assertEqual(row["status"], "available")
        self.assertEqual(row["runs_succeeded"], 2)
        self.assertTrue(row["can_stream"])
        self.assertIn("avg", row["latency_s"])
        self.assertGreater(row["throughput_bytes_per_s"]["avg"], 0)

    def test_benchmark_keeps_unavailable_backend_as_explicit_state(self):
        with patch.dict(os.environ, {}, clear=True):
            report = llm_probe.benchmark_backends(["openai"], runs=1,
                                                  timeout_s=0.1)
        row = report["backends"][0]
        self.assertEqual(row["status"], "unavailable")
        self.assertEqual(row["errors"][0]["kind"], "config")

    def test_benchmark_classifies_connection_refusal_as_unavailable(self):
        _ProbeStubHandler.behavior.update({'mode': 'malformed', 'hits': 0})
        report = llm_probe.benchmark_backends(
            ["dead=x@http://127.0.0.1:65000/v1",
             f"malformed=x@{self.base}"], runs=1, timeout_s=0.1)
        unavailable, malformed = report["backends"]
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["reachable"], False)
        self.assertEqual(unavailable["runs_failed"], 1)
        self.assertEqual(unavailable["errors"][0]["kind"], "network")
        self.assertEqual(malformed["status"], "error")
        self.assertEqual(malformed["errors"][0]["kind"], "malformed")
        self.assertEqual(report["summary"]["unavailable"], 1)
        self.assertEqual(report["summary"]["errors"], 1)

    def test_benchmark_preserves_model_and_method_http_errors(self):
        for mode in ('http_404', 'http_501'):
            _ProbeStubHandler.behavior.update({'mode': mode, 'hits': 0})
            report = llm_probe.benchmark_backends(
                [f"local=x@{self.base}"], runs=1, timeout_s=1.0)
            row = report["backends"][0]
            self.assertEqual(row["status"], "error")
            self.assertTrue(row["reachable"])
            self.assertEqual(report["summary"]["unavailable"], 0)
            self.assertEqual(report["summary"]["errors"], 1)
            self.assertEqual(row["errors"][0]["kind"], "http")

    def test_benchmark_includes_explicitly_configured_aliases(self):
        env = {"PTAH_OLLAMA_URL": self.base, "PTAH_OLLAMA_MODEL": "ollama-test"}
        with patch.dict(os.environ, env, clear=True):
            targets = llm_probe.resolve_backend_targets()
        self.assertEqual(targets[-1].provider, "ollama")
        self.assertEqual(targets[-1].model, "ollama-test")


if __name__ == '__main__':
    unittest.main()
