"""Letter envelope: build, validate, and lint organ messages.

Contract (INTEGRATION.md section 4.1):

    {
      "v": 1,
      "id": "<seq>-<from>-<kind>-<token>",
      "ts": "YYYY-MM-DDTHH:MM:SS",
      "from": "vulcan",
      "to": "sentinel",          // mailbox letter; topics omit
      "topic": null,             // set for broadcast lines
      "kind": "incident",
      "rights": "operator",
      "payload": { },
      "error": null              // EVERY envelope carries error
    }

Rules enforced by validate():
- exactly one of `to` (mailbox) or `topic` (broadcast) is set;
- kind must appear in the catalogue for its topic (or be mailbox-only);
- error is None or a string - never absent;
- rights must be a known profile.
"""

import json
import time
import uuid

VERSION = 1

# Known rights profiles (norn.rights vocabulary; see INTEGRATION.md 4.3).
PROFILES = frozenset({
    "watcher", "player", "agent", "agent_rw", "admin", "operator",
})

# Topic catalogue (INTEGRATION.md section 6). topic -> allowed kinds.
TOPICS = {
    "incidents": {"incident"},
    "vitals": {"vital"},
    "grants": {"grant.grant", "grant.revoke", "grant.escalate"},
    "build.request": {"build.describe"},
    "build.stage": {
        "build.design",
        "build.code",
        "build.verify",
        "build.iterate",
        "build.prove",
        "build.seal",
        "build.ship",
    },
    "artifacts.sealed": {"provenance.seal"},
    "policy.update": {"policy.reload"},
    "llm": {"llm.call", "llm.error"},
    "updates": {"fleet.tick", "fleet.build", "fleet.repair",
                "fleet.render"},
}

KINDS = frozenset(k for kinds in TOPICS.values() for k in kinds)

_TS_FMT = "%Y-%m-%dT%H:%M:%S"


def _now_ts():
    return time.strftime(_TS_FMT)


def make(kind, frm, payload, *, to=None, topic=None, rights="watcher",
         error=None, ts=None):
    """Build an envelope. `id` starts unsequenced; the bus stamps it."""
    if to is None and topic is None:
        raise ValueError("envelope needs a recipient: 'to' or 'topic'")
    env = {
        "v": VERSION,
        "id": uuid.uuid4().hex[:12],
        "ts": ts or _now_ts(),
        "from": str(frm),
        "to": to,
        "topic": topic,
        "kind": str(kind),
        "rights": str(rights),
        "payload": payload if isinstance(payload, dict) else dict(payload),
        "error": error,
    }
    problems = validate(env)
    if problems:
        raise ValueError("invalid envelope: " + "; ".join(problems))
    return env


def stamp_seq(env, seq):
    """Compose the final bus id once ratatosk allocates a sequence."""
    parts = [str(env["from"]), env["kind"], env["id"]]
    env["id"] = f"{int(seq)}-{env['from']}-{env['kind']}-{parts[2][-12:]}"
    return env


def validate(env):
    """Return a list of violation strings (empty means valid)."""
    p = []
    if not isinstance(env, dict):
        return ["envelope is not an object"]
    if env.get("v") != VERSION:
        p.append(f"bad version: {env.get('v')!r}")
    try:
        time.strptime(str(env.get("ts")), _TS_FMT)
    except (ValueError, TypeError):
        p.append(f"bad ts: {env.get('ts')!r}")
    if not env.get("id"):
        p.append("missing id")
    if not str(env.get("from") or "").strip():
        p.append("missing from")
    to, topic, kind = env.get("to"), env.get("topic"), env.get("kind")
    if bool(to) == bool(topic):
        p.append("exactly one of 'to' or 'topic' must be set")
    if topic is not None:
        allowed = TOPICS.get(topic)
        if allowed is None:
            p.append(f"unknown topic: {topic!r}")
        elif kind not in allowed:
            p.append(f"kind {kind!r} not allowed on topic {topic!r}")
    elif kind not in KINDS:
        p.append(f"unknown mailbox kind: {kind!r}")
    if env.get("rights") not in PROFILES:
        p.append(f"unknown rights profile: {env.get('rights')!r}")
    if not isinstance(env.get("payload"), dict):
        p.append("payload must be an object")
    if "error" not in env:
        p.append("missing error field (must exist, may be null)")
    elif env["error"] is not None and not isinstance(env["error"], str):
        p.append("error must be null or a string")
    return p


def dump(env):
    return json.dumps(env, separators=(",", ":"), default=str)


def loads(line, *, strict=True):
    """Parse one JSONL line into an envelope.

    Raises ValueError on malformed JSON, or - when strict - on any
    contract violation (mirrors ratatosk's corrupt-letter quarantine:
    callers decide to skip/quarantine non-strict failures).
    """
    env = json.loads(line)
    problems = validate(env)
    if problems and strict:
        raise ValueError("invalid envelope: " + "; ".join(problems))
    return env, problems


def iter_lint(path):
    """Yield (line_no, violations) for every bad line in a JSONL ledger.

    Blank lines are skipped. Malformed JSON yields a single violation.
    A8: doctor/sentinel wire this in; exit code stays with the caller.
    """
    with open(path, encoding="utf-8") as fh:
        for no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                _, problems = loads(line, strict=False)
            except ValueError as exc:
                yield no, [f"unparseable line: {exc}"]
                continue
            if problems:
                yield no, problems
