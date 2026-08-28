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
Streaming brains may additionally expose .stream(system, messages).
"""

from ptah.llm import Reply


TRANSIENT_KINDS = {"rate_limit", "server", "network", "timeout"}


class ScriptedBrain:
    """Minimal brain adapter so scripted scripts can be a fallback."""

    provider = "scripted"

    def __init__(self, text):
        self._text = text

    def complete(self, system, messages, **kwargs):
        return Reply(text=self._text, model="scripted-fallback")

    def stream(self, system, messages, **kwargs):
        yield self.complete(system, messages, **kwargs)


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

    def complete(self, system, messages, **kwargs):
        chain = [self.primary] + self.fallbacks
        last_transient = None
        for index, brain in enumerate(chain):
            try:
                reply = brain.complete(system, messages, **kwargs)
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

    def stream(self, system, messages, **kwargs):
        """Relay a provider stream, falling back only before first output."""
        chain = [self.primary] + self.fallbacks
        last_transient = None
        for index, brain in enumerate(chain):
            iterator = getattr(brain, "stream", None)
            if iterator is None:
                iterator = lambda s, m, **kw: iter(
                    (brain.complete(s, m, **kw),))
            emitted = False
            try:
                for reply in iterator(system, messages, **kwargs):
                    emitted = True
                    self.last_served = getattr(brain, "model", None) or \
                        getattr(brain, "provider", f"brain{index}")
                    yield reply
                return
            except Exception as exc:              # noqa: BLE001
                kind = getattr(exc, "kind", "") or ""
                transient = kind in TRANSIENT_KINDS or \
                    not hasattr(exc, "kind")
                if emitted or index == len(chain) - 1 or not transient:
                    raise
                last_transient = exc
        if last_transient:
            raise last_transient


def summarize_usage(brain_calls):
    """Aggregate usage dicts across a chain of calls."""
    totals = {"input": 0, "output": 0}
    for call in brain_calls:
        usage = getattr(call, "usage", None) or {}
        totals["input"] += usage.get("input", 0)
        totals["output"] += usage.get("output", 0)
    return totals


def __getattr__(name):
    """Lazy compatibility exports for the health-aware router.

    Keeping this import lazy avoids a cycle because the router reuses the
    transient failure classification defined in this module.
    """
    if name in ("BackendRouter", "HealthAwareBackendRouter",
                "HealthAwareFallbackLLM"):
        from ptah.backend import BackendRouter
        return BackendRouter
    raise AttributeError(name)
