"""PTAH llm extras - resilience patterns learned from OpenHands.

FallbackLLM wraps a primary brain with ordered fallback brains.
Per-call semantics (matching OpenHands FallbackStrategy):

  - every request starts at the primary
  - only TRANSIENT failures advance to the next brain
    (rate limit / server / network); auth and bad-request errors
    fail fast without burning fallbacks
  - the reply records which brain actually served it

Works with any brain exposing .complete(system, messages): LLM,
ScriptedLLM, or another FallbackLLM (nesting = multi-level chains).
"""

from ptah.llm import Reply


TRANSIENT_KINDS = {"rate_limit", "server", "network", "timeout"}


class ScriptedBrain:
    """Minimal brain adapter so scripted scripts can be a fallback."""

    provider = "scripted"

    def __init__(self, text):
        self._text = text

    def complete(self, system, messages):
        return Reply(text=self._text, model="scripted-fallback")


class FallbackLLM:
    def __init__(self, primary, fallbacks=()):
        self.primary = primary
        self.fallbacks = list(fallbacks)
        if not self.fallbacks:
            raise ValueError("FallbackLLM needs at least one fallback")
        self.last_served = None

    @property
    def provider(self):
        return getattr(self.primary, "provider", "fallback")

    @property
    def config(self):
        return getattr(self.primary, "config", None)

    def complete(self, system, messages):
        chain = [self.primary] + self.fallbacks
        last_transient = None
        for index, brain in enumerate(chain):
            try:
                reply = brain.complete(system, messages)
                self.last_served = getattr(brain, "model", None) or \
                    getattr(brain, "provider", f"brain{index}")
                return reply
            except Exception as exc:              # noqa: BLE001
                kind = getattr(exc, "kind", "") or ""
                transient = kind in TRANSIENT_KINDS or \
                    not hasattr(exc, "kind")      # unknown brains: treat as transient
                if index == len(chain) - 1 or not transient:
                    raise
                last_transient = exc
        raise last_transient                      # pragma: no cover


def summarize_usage(brain_calls):
    """Aggregate usage dicts across a chain of calls."""
    totals = {"input": 0, "output": 0}
    for call in brain_calls:
        usage = getattr(call, "usage", None) or {}
        totals["input"] += usage.get("input", 0)
        totals["output"] += usage.get("output", 0)
    return totals
