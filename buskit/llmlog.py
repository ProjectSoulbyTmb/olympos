"""LLM-call attestation: every prompt/response becomes evidence.

Closes INTEGRATION.md gap "witness-for-LLM": when PTAH (or any
brain) acts autonomously, the *content* may be ephemeral but the
*fact and shape* of every call is permanent evidence:

    {v, ts, model, actor, prompt_digest, response_digest,
     prompt_chars, response_chars, latency_ms, ok, error}

Digests are sha256[:16] - enough to prove identity, small enough to
keep forever. Journals are plain JSONL so Hades can seal them and
norn replay can re-run sessions against recorded shapes.
"""

import hashlib
import json
import os
import time

VERSION = 1


def digest(text):
    """Stable short digest identifying a prompt or response."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]


class LLMJournal:
    """Append-only JSONL journal of brain calls."""

    def __init__(self, path, actor="ptah"):
        self.path = path
        self.actor = actor

    def record(self, *, model, prompt, response=None, latency_ms=None,
               error=None):
        rec = {
            "v": VERSION,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "actor": self.actor,
            "model": str(model),
            "prompt_digest": digest(prompt),
            "prompt_chars": len(str(prompt)),
            "response_digest": (None if response is None
                                else digest(response)),
            "response_chars": (None if response is None
                               else len(str(response))),
            "latency_ms": latency_ms,
            "ok": error is None,
            "error": error,
        }
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        return rec

    def attested(self, brain_fn, *, model, prompt, **kw):
        """Call ``brain_fn(prompt, **kw) -> str`` under attestation."""
        t0 = time.monotonic()
        try:
            response = brain_fn(prompt, **kw)
        except Exception as exc:  # noqa: BLE001 - failure is evidence
            self.record(model=model, prompt=prompt,
                        error=f"{type(exc).__name__}: {exc}",
                        latency_ms=int((time.monotonic() - t0) * 1000))
            raise
        self.record(model=model, prompt=prompt, response=response,
                    latency_ms=int((time.monotonic() - t0) * 1000))
        return response

    def entries(self):
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out


def validate(entry):
    """Contract check for one journal record."""
    problems = []
    if entry.get("v") != VERSION:
        problems.append("bad version")
    if not entry.get("model"):
        problems.append("missing model")
    if not entry.get("prompt_digest"):
        problems.append("missing prompt_digest")
    if entry.get("ok") is False and not entry.get("error"):
        problems.append("failed call without error detail")
    if entry.get("response_digest") and \
            entry.get("response_chars") is None:
        problems.append("digest without length")
    return problems
