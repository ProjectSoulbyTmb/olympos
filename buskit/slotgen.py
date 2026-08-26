# SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
"""buskit.slotgen - slot-sized canonical codegen calls.

A "slot" is one small generation unit: a function body, a template
fill, a config blob. App-scale codegen is explicitly OUT of scope
(milestone M-GPU1); any reply larger than the slot cap is refused by
name, not truncated.

Every call rides the full reliability chain:

    journaled call (buskit.llmlog - digests, never raw prompts)
      -> retry with exponential backoff + seeded jitter
      -> breaker with visible state + half-open revival (rule 7)
      -> deterministic fallback chain ending in the scripted brain
      -> Hades seal of the journal (scoped instance, see
         SlotCaller.seal_journal)

Doctrine: deterministic-first. The scripted brain is the CI/offline
default and the terminal fallback; a remote model assists simple slots
only and is opt-in via configuration. With endpoints dead the chain
converges deterministically - same seed in, same artifact out, zero
network. Standard library only.
"""

import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from buskit.llmlog import LLMJournal, digest


class SlotError(Exception):
    """Fatal (non-transient) slot failure with a named kind."""

    def __init__(self, kind, message):
        super().__init__(f"[{kind}] {message}")
        self.kind = kind


class TransientError(SlotError):
    """Retryable failure (network/timeout/rate_limit/server/breaker)."""


SLOT_KINDS = ("function_body", "template_fill", "config_gen")
DEFAULT_SLOT_CAP = 4000          # chars; slots are small by law
TRANSIENT_KINDS = frozenset(
    {"network", "timeout", "rate_limit", "server", "breaker_open"})


# ------------------------------------------------------------------- spec
@dataclass
class SlotSpec:
    kind: str                    # one of SLOT_KINDS
    name: str                    # stable slot identifier
    task: str = ""               # human-readable intent
    template: str = ""           # template_fill source text
    fields: dict = field(default_factory=dict)
    seed: str = "0"              # determinism knob
    max_chars: int = DEFAULT_SLOT_CAP

    def __post_init__(self):
        if self.kind not in SLOT_KINDS:
            raise SlotError("bad_request",
                            f"unknown slot kind {self.kind!r}")
        if not self.name.strip():
            raise SlotError("bad_request", "slot needs a name")

    def canonical_prompt(self):
        return f"[{self.kind}] {self.name}: {self.task}".strip()

    def key(self):
        """Stable identity for jitter seeds + scripted render."""
        return digest(f"{self.kind}|{self.name}|{self.seed}")


# ----------------------------------------------------------------- brains
class ScriptedBrain:
    """Deterministic terminal fallback: renders the artifact from the
    spec alone. No network, no randomness, byte-stable forever."""

    provider = "scripted"

    def label(self):
        return "scripted"

    def serve(self, spec):
        d = spec.key()
        safe = "".join(c if (c.isalnum() or c == "_") else "_"
                       for c in spec.name)
        if spec.kind == "function_body":
            args = ", ".join(sorted(spec.fields))
            return (f"def {safe}({args}):\n"
                    f"    \"\"\"{spec.task or spec.name} "
                    f"(slot {spec.seed}, scripted).\"\"\"\n"
                    f"    return {d!r}\n")
        if spec.kind == "template_fill":
            src = spec.template or "# empty template for {name}"
            out = src.replace("{name}", spec.name)
            out = out.replace("{seed}", spec.seed)
            out = out.replace("{digest}", d)
            for k, v in sorted(spec.fields.items()):
                out = out.replace("{" + k + "}", str(v))
            return out
        cfg = {"digest": d,
               "fields": dict(sorted(spec.fields.items())),
               "kind": spec.kind, "name": spec.name, "seed": spec.seed}
        return json.dumps(cfg, sort_keys=True, indent=2)


class RemoteBrain:
    """OpenAI-dialect endpoint client (LM Studio compatible) behind a
    visible breaker: closed -> open after `trip_after` consecutive
    transients -> half_open after `cool_down_s`, one probe decides.
    Refusals are named; nothing hangs past `timeout_s`."""

    provider = "openai"

    def __init__(self, base_url, model, timeout_s=3.0, api_key="",
                 trip_after=3, cool_down_s=0.5):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.api_key = api_key
        self.trip_after = trip_after
        self.cool_down_s = cool_down_s
        self.failures = 0
        self.opened_at = None

    @property
    def state(self):
        if self.opened_at is None:
            return "closed"
        if time.monotonic() - self.opened_at >= self.cool_down_s:
            return "half_open"
        return "open"

    def _allow(self):
        return self.state != "open"

    def _record(self, ok):
        if ok:
            self.failures = 0
            self.opened_at = None
        else:
            self.failures += 1
            if self.failures >= self.trip_after:
                self.opened_at = time.monotonic()

    def label(self):
        return f"remote:{self.model}"

    def serve(self, spec):
        if not self._allow():
            raise TransientError(
                "breaker_open",
                f"breaker open for {self.label()} (cooling down)")
        try:
            text = self._once(spec)
            self._record(True)
            return text
        except SlotError:
            self._record(False)
            raise

    def _once(self, spec):
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": ("You fill one small code slot. Reply with "
                             "the slot artifact only.")},
                {"role": "user", "content": spec.canonical_prompt()},
            ],
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=payload,
            headers={"content-type": "application/json",
                     "user-agent": "buskit-slotgen/1"},
            method="POST")
        try:
            with urllib.request.urlopen(req,
                                        timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            kind = ("rate_limit" if exc.code == 429 else
                    "auth" if exc.code in (401, 403) else
                    "server" if exc.code >= 500 else "bad_request")
            cls = TransientError if kind in TRANSIENT_KINDS else SlotError
            raise cls(kind, f"HTTP {exc.code} from {self.base_url}")
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                OSError) as exc:
            raise TransientError("network", str(exc)[:160])
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (LookupError, TypeError):
            raise SlotError("bad_response",
                            "malformed completion payload")


# ----------------------------------------------------------------- caller
class SlotCaller:
    """Runs one slot through the full chain; journals every leg."""

    def __init__(self, journal_path, brains=(), *, actor="codegen",
                 backoff_base_s=0.25, backoff_cap_s=2.0, max_attempts=3):
        self.journal = LLMJournal(journal_path, actor=actor)
        self.brains = list(brains)
        if not self.brains:
            raise ValueError("SlotCaller needs at least one brain")
        if self.brains[-1].provider != "scripted":
            raise ValueError(
                "chain must END in the scripted brain (doctrine)")
        if sum(1 for b in self.brains
               if b.provider == "scripted") != 1:
            raise ValueError("exactly one scripted terminal brain")
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.max_attempts = max_attempts
        self.last_delays = []       # observability: delays used last call

    def _delay(self, brain, spec, attempt):
        """Exponential backoff with SEEDED jitter: the delay sequence is
        a pure function of (brain label, slot identity, attempt), so
        reruns reproduce it exactly."""
        base = min(self.backoff_cap_s,
                   self.backoff_base_s * (2 ** attempt))
        rng = random.Random(f"{brain.label()}|{spec.key()}|{attempt}")
        return round(rng.uniform(base * 0.5, base * 1.5), 4)

    def generate(self, spec):
        """Advance legs on transient failure; fatal errors refuse a leg
        BY NAME and fall forward to the next brain. The scripted
        terminal leg is infallible for well-formed specs."""
        self.last_delays = []
        refusals = []
        attempts = 0
        for index, brain in enumerate(self.brains):
            last_leg = index == len(self.brains) - 1
            tries = 1 if last_leg else self.max_attempts
            for attempt in range(tries):
                attempts += 1
                t0 = time.monotonic()
                try:
                    text = brain.serve(spec)
                except Exception as exc:  # noqa: BLE001 - journaled
                    kind = str(getattr(exc, "kind", type(exc).__name__))
                    refusals.append({"brain": brain.label(),
                                     "kind": kind,
                                     "error": str(exc)[:200]})
                    self.journal.record(
                        model=brain.label(),
                        prompt=spec.canonical_prompt(),
                        error=f"{kind}: {exc}",
                        latency_ms=int((time.monotonic() - t0) * 1000))
                    if (last_leg or attempt == tries - 1
                            or kind not in TRANSIENT_KINDS):
                        break          # fatal, or leg exhausted
                    delay = self._delay(brain, spec, attempt)
                    self.last_delays.append(delay)
                    time.sleep(delay)
                    continue
                if len(text) > spec.max_chars:
                    refusals.append({"brain": brain.label(),
                                     "kind": "slot_too_large",
                                     "error": f"{len(text)} chars > "
                                              f"cap {spec.max_chars}"})
                    self.journal.record(
                        model=brain.label(),
                        prompt=spec.canonical_prompt(),
                        error=f"slot_too_large: {len(text)} chars",
                        latency_ms=int((time.monotonic() - t0) * 1000))
                    break              # oversize is fatal for the leg
                self.journal.record(model=brain.label(),
                                    prompt=spec.canonical_prompt(),
                                    response=text,
                                    latency_ms=int(
                                        (time.monotonic() - t0) * 1000))
                return GenerationResult(text=text, brain=brain.label(),
                                        attempts=attempts,
                                        refusals=refusals,
                                        journal=self.journal.path)
        raise SlotError(
            "exhausted", "no brain served the slot; refusals: "
            + json.dumps(refusals))

    def seal_journal(self, root, state_dir):
        """Seal the journal with a SCOPED Hades instance (the journal
        product only). Returns the seal counts dict."""
        from hades.kernel import Hades
        rel = os.path.relpath(self.journal.path, root)
        rel = rel.replace("\\", "/")
        h = Hades(root=root, state_dir=state_dir,
                  config={"include_realms": False, "products": [
                      {"name": "llm-journal", "include": [rel],
                       "exclude": []}]})
        return h.seal()


@dataclass
class GenerationResult:
    text: str
    brain: str
    attempts: int
    refusals: list
    journal: str

    @property
    def fell_back(self):
        return self.brain.startswith("scripted")
