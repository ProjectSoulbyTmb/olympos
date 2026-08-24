"""PTAH events - typed, JSON-serializable conversation history.

The conversation is an append-only event stream (JSONL on disk). Every
turn - user input, system prompt assembly, agent actions, tool
observations, confirmations, condensations and finishes - is recorded as
a typed event so state can always be replayed from the log.
"""

import datetime
import itertools
import json

_SEQ = itertools.count(1)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="milliseconds")


def next_id(prefix):
    return f"{prefix}-{next(_SEQ):06d}"


class Event:
    """Base event: a `type` discriminator plus payload fields."""

    TYPE = "event"
    FIELDS = ()

    def __init__(self, **fields):
        self.ts = fields.pop("ts", None) or now_iso()
        self.id = fields.pop("id", None) or next_id(self.TYPE)
        for key in self.FIELDS:
            setattr(self, key, fields.get(key))

    def to_dict(self):
        out = {"type": self.TYPE, "id": self.id, "ts": self.ts}
        for key in self.FIELDS:
            out[key] = getattr(self, key)
        return out

    @classmethod
    def from_dict(cls, data):
        if data.get("type") != cls.TYPE:
            raise ValueError(f"type mismatch: {data.get('type')} != {cls.TYPE}")
        fields = {k: data.get(k) for k in cls.FIELDS}
        return cls(id=data.get("id"), ts=data.get("ts"), **fields)

    def __eq__(self, other):
        return isinstance(other, Event) and self.to_dict() == other.to_dict()

    def __repr__(self):
        return f"<{self.TYPE} {self.id}>"


class UserMessage(Event):
    TYPE = "user_message"
    FIELDS = ("text",)


class SystemPrompt(Event):
    TYPE = "system_prompt"
    FIELDS = ("text",)


class AgentThought(Event):
    """Raw model reply before parsing (kept verbatim for audit)."""
    TYPE = "agent_thought"
    FIELDS = ("text", "usage")


class AgentMessage(Event):
    TYPE = "agent_message"
    FIELDS = ("text",)


class ActionEvent(Event):
    TYPE = "action"
    FIELDS = ("tool", "args", "risk", "risk_reason")


class ObservationEvent(Event):
    TYPE = "observation"
    FIELDS = ("tool", "output", "error", "exit_code", "truncated")


class ConfirmationRequiredEvent(Event):
    TYPE = "confirmation_required"
    FIELDS = ("tool", "args", "risk", "reason")


class DeniedActionEvent(Event):
    TYPE = "denied_action"
    FIELDS = ("tool", "args", "reason")


class CondensationEvent(Event):
    TYPE = "condensation"
    FIELDS = ("dropped", "summary", "kept")


class ErrorEvent(Event):
    TYPE = "error"
    FIELDS = ("message",)


class FinishedEvent(Event):
    TYPE = "finished"
    FIELDS = ("reason",)          # answered | stuck | max_iterations | error


EVENT_TYPES = {cls.TYPE: cls for cls in (
    UserMessage, SystemPrompt, AgentThought, AgentMessage, ActionEvent,
    ObservationEvent, ConfirmationRequiredEvent, DeniedActionEvent,
    CondensationEvent, ErrorEvent, FinishedEvent)}


def serialize(event):
    return json.dumps(event.to_dict(), ensure_ascii=False)


def deserialize(line):
    data = json.loads(line)
    cls = EVENT_TYPES.get(data.get("type"))
    if cls is None:
        raise ValueError(f"unknown event type: {data.get('type')!r}")
    return cls.from_dict(data)
