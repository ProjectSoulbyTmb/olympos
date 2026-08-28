import threading
import unittest
import json
import os
import tempfile
import urllib.request

from ptah.backend import BackendRouter
from ptah.conversation import Store
from ptah.llm import LLMError, Reply
from ptah.request_context import bind_request_context
from ptah.server import ApiServer, make_handler


class _Brain:
    def __init__(self, provider, replies=None, error=None):
        self.provider = provider
        self.replies = list(replies or [])
        self.error = error
        self.calls = 0

    def complete(self, system, messages, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.replies.pop(0)

    def stream(self, system, messages, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        for reply in self.replies:
            yield reply


class TestBackendRouter(unittest.TestCase):
    def test_transient_failover_and_metrics(self):
        primary = _Brain("primary", error=LLMError("server", "down"))
        backup = _Brain("backup", [Reply("ok")])
        router = BackendRouter([("primary", primary), ("backup", backup)],
                               failure_threshold=1, cooldown_s=60)

        reply = router.complete("sys", [])
        self.assertEqual(reply.text, "ok")
        snapshot = router.metrics()
        self.assertTrue(snapshot["ready"])
        self.assertEqual(snapshot["total_calls"], 2)
        self.assertFalse(snapshot["backends"][0]["available"])
        self.assertEqual(router.last_served, "backup")

    def test_auth_failure_does_not_fail_over(self):
        primary = _Brain("primary", error=LLMError("auth", "bad key"))
        backup = _Brain("backup", [Reply("not used")])
        router = BackendRouter([primary, backup])
        with self.assertRaises(LLMError):
            router.complete("sys", [])
        self.assertEqual(backup.calls, 0)

    def test_stream_only_fails_over_before_first_chunk(self):
        primary = _Brain("primary", error=LLMError("timeout", "down"))
        backup = _Brain("backup", [Reply("backup")])
        router = BackendRouter([primary, backup], failure_threshold=1)
        self.assertEqual([part.text for part in router.stream("s", [])],
                         ["backup"])

    def test_stream_does_not_switch_after_output(self):
        class Partial(_Brain):
            def stream(self, system, messages, **kwargs):
                self.calls += 1
                yield Reply("partial")
                raise LLMError("network", "connection lost")

        primary = Partial("primary")
        backup = _Brain("backup", [Reply("wrong")])
        router = BackendRouter([primary, backup])
        stream = router.stream("s", [])
        self.assertEqual(next(stream).text, "partial")
        with self.assertRaises(LLMError):
            next(stream)
        self.assertEqual(backup.calls, 0)

    def test_concurrent_calls_are_counted_without_serializing_provider(self):
        barrier = threading.Barrier(2)

        class Concurrent(_Brain):
            def complete(self, system, messages, **kwargs):
                self.calls += 1
                barrier.wait(timeout=2)
                return Reply("ok")

        brain = Concurrent("primary")
        router = BackendRouter([brain])
        errors = []
        threads = [threading.Thread(
            target=lambda: router.complete("s", [])) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            if thread.is_alive():
                errors.append("deadlock")
        self.assertEqual(errors, [])
        self.assertEqual(router.metrics()["total_successes"], 2)

    def test_server_readiness_and_metrics_routes(self):
        brain = _Brain("primary", [Reply("ok")])
        router = BackendRouter([brain])
        router.complete("s", [])
        with tempfile.TemporaryDirectory(prefix="ptah-backend-api-") as root:
            server = ApiServer(
                ("127.0.0.1", 0),
                make_handler(Store(root=root), lambda *_: None,
                             backend_router=router))
            thread = threading.Thread(target=server.serve_forever,
                                       daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urllib.request.urlopen(base + "/readyz",
                                             timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())["ready"], True)
                with urllib.request.urlopen(base + "/metrics",
                                             timeout=3) as response:
                    self.assertEqual(json.loads(response.read())[
                        "total_successes"], 1)
            finally:
                server.shutdown()
                server.server_close()

    def test_circuit_recovery_after_cooldown(self):
        class Clock:
            def __init__(self):
                self.now = 0.0

            def __call__(self):
                return self.now

        class Flaky(_Brain):
            def complete(self, system, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise LLMError("server", "down")
                return Reply("primary-recovered")

        clock = Clock()
        primary = Flaky("primary")
        backup = _Brain("backup", [Reply("backup"), Reply("backup-2")])
        router = BackendRouter([("primary", primary), ("backup", backup)],
                               failure_threshold=1, cooldown_s=5.0,
                               clock=clock)
        first = router.complete("s", [])
        self.assertEqual(first.text, "backup")
        self.assertFalse(router.metrics()["backends"][0]["available"])
        clock.now += 6.0
        second = router.complete("s", [])
        self.assertEqual(second.text, "primary-recovered")
        snapshot = router.metrics()
        self.assertTrue(snapshot["backends"][0]["available"])
        self.assertEqual(snapshot["backends"][0]["consecutive_failures"], 0)

    def test_metrics_save_and_load(self):
        brain = _Brain("primary", [Reply("ok"), Reply("ok-2")])
        with tempfile.TemporaryDirectory(prefix="ptah-metrics-") as root:
            path = f"{root}/backend-metrics.json"
            router = BackendRouter([brain], metrics_path=path)
            router.complete("s", [])
            router.save_metrics()
            with open(path, "rb") as fh:
                payload = json.loads(fh.read().decode())
            self.assertEqual(payload["schema"], "ptah-backend-metrics-v1")
            restored = BackendRouter([_Brain("primary", [Reply("later")])],
                                     metrics_path=path)
            self.assertGreaterEqual(restored.metrics()["total_calls"], 1)
            self.assertEqual(router.metrics()["persistence_error"], "")

    def test_automatic_metrics_persistence_failure_is_non_fatal_and_visible(self):
        brain = _Brain("primary", [Reply("ok")])
        with tempfile.TemporaryDirectory(prefix="ptah-metrics-fail-") as root:
            target = os.path.join(root, "metrics-dir")
            os.makedirs(target, exist_ok=True)
            router = BackendRouter([brain], metrics_path=target)
            reply = router.complete("s", [])
            self.assertEqual(reply.text, "ok")
            snapshot = router.metrics()
            self.assertEqual(snapshot["total_successes"], 1)
            self.assertTrue(snapshot["persistence_error"])

    def test_save_metrics_failure_raises(self):
        brain = _Brain("primary", [Reply("ok")])
        with tempfile.TemporaryDirectory(prefix="ptah-metrics-fail-") as root:
            target = os.path.join(root, "metrics-dir")
            os.makedirs(target, exist_ok=True)
            router = BackendRouter([brain])
            router.complete("s", [])
            with self.assertRaises(OSError):
                router.save_metrics(target)
            self.assertTrue(router.metrics()["persistence_error"])

    def test_request_context_tracks_last_request_id(self):
        brain = _Brain("primary", [Reply("ok")])
        router = BackendRouter([brain])
        with bind_request_context("req-123"):
            router.complete("s", [])
        stats = router.metrics()["backends"][0]
        self.assertEqual(stats["last_request_id"], "req-123")


if __name__ == "__main__":
    unittest.main()
