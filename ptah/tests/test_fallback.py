import unittest

from ptah.fallback import FallbackLLM, ScriptedBrain
from ptah.hooks import HookOutcome, run_hooks
from ptah.llm import LLMError, Reply, ScriptedLLM


class RaisingBrain:
    provider = "raising"

    def __init__(self, kind, times=1):
        self.kind = kind
        self.remaining = times
        self.calls = 0

    def complete(self, system, messages):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise LLMError(self.kind, f"synthetic {self.kind}")
        return Reply(text="recovered")


class TestFallbackChain(unittest.TestCase):
    def test_transient_failure_falls_back(self):
        primary = RaisingBrain("rate_limit", times=1)
        brain = FallbackLLM(primary, [ScriptedBrain("fallback answer")])
        reply = brain.complete("sys", [])
        self.assertEqual(reply.text, "fallback answer")
        self.assertIn("scripted", brain.last_served)

    def test_auth_errors_fail_fast(self):
        primary = RaisingBrain("auth", times=99)
        fallback = ScriptedBrain("should not be reached")
        brain = FallbackLLM(primary, [fallback])
        with self.assertRaises(LLMError):
            brain.complete("sys", [])
        self.assertEqual(fallback.complete.__self__._text,
                         "should not be reached")  # untouched

    def test_order_and_exhaustion(self):
        b1 = RaisingBrain("server", times=99)
        b2 = RaisingBrain("network", times=99)
        brain = FallbackLLM(RaisingBrain("timeout", times=99), [b1, b2])
        with self.assertRaises(LLMError):
            brain.complete("sys", [])
        self.assertEqual(b1.calls, 1)
        self.assertEqual(b2.calls, 1)

    def test_primary_recovers_per_call(self):
        primary = RaisingBrain("server", times=0)   # always healthy now
        brain = FallbackLLM(ScriptedBrain("primary ok"),
                            [ScriptedBrain("never")])
        for _ in range(3):
            self.assertEqual(brain.complete("s", []).text, "primary ok")
            self.assertEqual(brain.last_served, "scripted")

    def test_requires_fallback(self):
        with self.assertRaises(ValueError):
            FallbackLLM(ScriptedBrain("x"), [])


if __name__ == "__main__":
    unittest.main()
