"""MIND rules - operator-authored reaction flows over production events.

A flow says: when the production does X, and (optionally) some condition
holds, run these actions. Flows are plain JSON so operators author them
without touching code:

    {"id": "auto-live", "on": "scene_changed",
     "when": {"scene_in": ["Starting Soon"]}, "cooldown_s": 60,
     "then": [{"action": "wait", "seconds": 5},
              {"action": "switch_scene", "scene": "Live"}]}

The decision pass (`observe`) is a pure function of trigger + data +
flow bookkeeping, with an injected clock - deterministic, testable, no
I/O. Execution belongs to the director's executor.

Run: python mind/rules.py   (self-test, exit 0 = engine sane)
"""

from __future__ import annotations

import time

TRIGGERS = (
    "connected",
    "disconnected",
    "scene_changed",
    "preview_scene_changed",
    "stream_started",
    "stream_stopped",
    "recording_started",
    "recording_stopped",
    "input_muted",
    "input_unmuted",
    "studio_mode_enabled",
    "studio_mode_disabled",
)

ACTIONS = {
    # action name -> required keys in the step dict
    "switch_scene": ("scene",),
    "set_recording": ("state",),
    "set_stream": ("state",),
    "http_get": ("url",),
    "log": ("message",),
    "wait": ("seconds",),
}

MAX_WAIT_SECONDS = 30.0
MAX_COOLDOWN_SECONDS = 3600.0
MAX_STEPS_PER_FLOW = 16


class RulesConfigError(ValueError):
    """Raised with a collected list of flow-definition problems."""


class Flow:
    __slots__ = ("id", "on", "when_scene_in", "then", "cooldown_s",
                 "last_fired")

    def __init__(self, flow_id: str, on: str, then: list,
                 when_scene_in=None, cooldown_s: float = 0.0):
        self.id = flow_id
        self.on = on
        self.then = then
        self.when_scene_in = list(when_scene_in) \
            if when_scene_in is not None else None
        self.cooldown_s = float(cooldown_s)
        self.last_fired = None  # injected-clock timestamp or None


def validate_flows(flow_dicts) -> "list[Flow]":
    """Strict validation; raises RulesConfigError listing all problems."""
    problems = []
    flows = []
    seen_ids = set()
    if not isinstance(flow_dicts, list):
        raise RulesConfigError("flows must be a list")
    for index, raw in enumerate(flow_dicts):
        label = f"flows[{index}]"
        if not isinstance(raw, dict):
            problems.append(f"{label}: not an object")
            continue
        flow_id = raw.get("id")
        on = raw.get("on")
        then = raw.get("then")
        if not isinstance(flow_id, str) or not flow_id.strip():
            problems.append(f"{label}: missing non-empty 'id'")
            flow_id = f"<unnamed-{index}>"
        elif flow_id in seen_ids:
            problems.append(f"{label}: duplicate id '{flow_id}'")
        else:
            seen_ids.add(flow_id)
        if on not in TRIGGERS:
            problems.append(f"{label} ({flow_id}): unknown trigger {on!r}")
        if not isinstance(then, list) or not then:
            problems.append(f"{label} ({flow_id}): 'then' must be a "
                            "non-empty list")
            continue
        if len(then) > MAX_STEPS_PER_FLOW:
            problems.append(f"{label} ({flow_id}): too many steps "
                            f"(>{MAX_STEPS_PER_FLOW})")
        steps = []
        for si, step in enumerate(then):
            slabel = f"{label} ({flow_id}) step[{si}]"
            if not isinstance(step, dict):
                problems.append(f"{slabel}: not an object")
                continue
            action = step.get("action")
            if action not in ACTIONS:
                problems.append(f"{slabel}: unknown action {action!r}")
                continue
            for key in ACTIONS[action]:
                if key not in step:
                    problems.append(f"{slabel}: '{action}' needs '{key}'")
            if action == "wait":
                seconds = step.get("seconds")
                if not isinstance(seconds, (int, float)) or \
                        not 0 < float(seconds) <= MAX_WAIT_SECONDS:
                    problems.append(
                        f"{slabel}: wait seconds must be within "
                        f"(0, {MAX_WAIT_SECONDS}]")
            if action == "set_recording" and \
                    step.get("state") not in ("start", "stop"):
                problems.append(f"{slabel}: set_recording state must be "
                                "'start' or 'stop'")
            if action == "set_stream" and \
                    step.get("state") not in ("start", "stop"):
                problems.append(f"{slabel}: set_stream state must be "
                                "'start' or 'stop'")
            if action == "http_get":
                url = str(step.get("url", ""))
                if not url.lower().startswith(("http://", "https://")):
                    problems.append(f"{slabel}: http_get needs an "
                                    "http(s) url")
            steps.append(step)
        when = raw.get("when") or {}
        scene_in = None
        if when:
            if not isinstance(when, dict):
                problems.append(f"{label} ({flow_id}): 'when' must be an "
                                "object")
            else:
                unknown = set(when) - {"scene_in"}
                if unknown:
                    problems.append(f"{label} ({flow_id}): unknown "
                                    f"condition(s) {sorted(unknown)}")
                if "scene_in" in when:
                    listed = when.get("scene_in")
                    if not isinstance(listed, list) or not all(
                            isinstance(x, str) for x in listed):
                        problems.append(f"{label} ({flow_id}): scene_in "
                                        "must be a list of strings")
                    else:
                        scene_in = listed
        cooldown = raw.get("cooldown_s", 0)
        if not isinstance(cooldown, (int, float)) or cooldown < 0 or \
                cooldown > MAX_COOLDOWN_SECONDS:
            problems.append(f"{label} ({flow_id}): cooldown_s out of range")
        flows.append(Flow(str(flow_id), on if on in TRIGGERS else "",
                          steps, scene_in,
                          float(cooldown) if cooldown >= 0 else 0.0))
    if problems:
        raise RulesConfigError("; ".join(problems))
    return flows


def _trigger_for(event_type: str, data: dict) -> "tuple[str | None, str]":
    """Map an obs-websocket event to a rules trigger + scene context."""
    if event_type == "CurrentProgramSceneChanged":
        return ("scene_changed", str(data.get("sceneName", "")))
    if event_type == "CurrentPreviewSceneChanged":
        return ("preview_scene_changed", str(data.get("sceneName", "")))
    mapping = {
        "StreamStateChanged": lambda active:
            ("stream_started" if active else "stream_stopped", ""),
        "RecordStateChanged": lambda active:
            ("recording_started" if active else "recording_stopped", ""),
    }
    if event_type == "StreamStateChanged":
        return mapping["StreamStateChanged"](bool(data.get("outputActive")))
    if event_type == "RecordStateChanged":
        active = bool(data.get("outputActive"))
        paused = bool(data.get("outputPaused"))
        effective = active or paused  # pause keeps output alive
        return mapping["RecordStateChanged"](effective)
    if event_type == "InputMuteStateChanged":
        muted = bool(data.get("inputMuted"))
        return ("input_muted" if muted else "input_unmuted",
                str(data.get("inputName", "")))
    if event_type == "StudioModeStateChanged":
        enabled = bool(data.get("studioModeEnabled"))
        return ("studio_mode_enabled" if enabled
                else "studio_mode_disabled", "")
    return (None, "")


def observe(flows: "list[Flow]", event_type: str, data: dict,
            now: float) -> "list[tuple[Flow, list]]":
    """Pure decision pass: which flows fire, and their planned steps."""
    trigger, context = _trigger_for(event_type, data)
    fired = []
    if trigger is None:
        return fired
    for flow in flows:
        if flow.on != trigger:
            continue
        if flow.when_scene_in is not None and \
                context not in flow.when_scene_in:
            continue
        if flow.last_fired is not None and \
                now - flow.last_fired < flow.cooldown_s:
            continue
        flow.last_fired = now
        fired.append((flow, list(flow.then)))
    return fired


def selftest() -> int:
    failures = []
    fake = {"t": 100.0}

    def check(name, fn):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")

    def t_validation():
        good = [{"id": "a", "on": "stream_started",
                 "then": [{"action": "log", "message": "on air"}]}]
        flows = validate_flows(good)
        assert len(flows) == 1 and flows[0].id == "a"
        bad = [
            {"id": "", "on": "nope", "then": []},
            {"id": "dup", "on": "scene_changed",
             "then": [{"action": "wait", "seconds": 999}]},
            {"id": "dup", "on": "scene_changed",
             "then": [{"action": "switch_scene"}]},
            {"id": "x", "on": "scene_changed",
             "when": {"wat": 1},
             "then": [{"action": "http_get", "url": "ftp://no"}]},
        ]
        try:
            validate_flows(bad)
            raise AssertionError("bad config accepted")
        except RulesConfigError as exc:
            text = str(exc)
            for needle in ("unknown trigger", "duplicate id", "wait seconds",
                           "'switch_scene' needs 'scene'", "unknown "
                           "condition", "http(s) url"):
                assert needle in text, f"missing diagnosis {needle!r}"

    def t_decision_and_cooldown():
        flows = validate_flows([
            {"id": "go-live", "on": "scene_changed",
             "when": {"scene_in": ["Starting Soon"]}, "cooldown_s": 60,
             "then": [{"action": "wait", "seconds": 5},
                      {"action": "switch_scene", "scene": "Live"}]},
            {"id": "note-stop", "on": "stream_stopped",
             "then": [{"action": "log", "message": "offline"}]},
        ])
        # unrelated events never fire
        assert observe(flows, "VendorThing", {}, now=fake["t"]) == []
        # wrong-scene context filtered by `when`
        got = observe(flows, "CurrentProgramSceneChanged",
                      {"sceneName": "Live"}, now=fake["t"])
        assert got == [], "when-clause failed to filter"
        # right context fires both steps in order
        got = observe(flows, "CurrentProgramSceneChanged",
                      {"sceneName": "Starting Soon"}, now=fake["t"])
        assert len(got) == 1
        flow, steps = got[0]
        assert flow.id == "go-live"
        assert [s["action"] for s in steps] == ["wait", "switch_scene"]
        # cooldown suppresses immediate refire ...
        got = observe(flows, "CurrentProgramSceneChanged",
                      {"sceneName": "Starting Soon"}, now=fake["t"] + 10)
        assert got == [], "cooldown leaked"
        # ... and expires exactly at the window edge
        got = observe(flows, "CurrentProgramSceneChanged",
                      {"sceneName": "Starting Soon"}, now=fake["t"] + 60)
        assert got and got[0][0].id == "go-live"

    def t_record_pause_semantics():
        flows = validate_flows([
            {"id": "r", "on": "recording_started",
             "then": [{"action": "log", "message": "rec"}]},
        ])
        # pausing keeps the recording trigger quiet; resuming neither
        assert observe(flows, "RecordStateChanged",
                       {"outputActive": True, "outputPaused": True},
                       now=1.0), "pause should count as recording-active"
        assert observe(flows, "RecordStateChanged",
                       {"outputActive": False, "outputPaused": False},
                       now=2.0) == []

    check("config-validation-diagnoses", t_validation)
    check("decision-cooldown-ordering", t_decision_and_cooldown)
    check("record-pause-semantics", t_record_pause_semantics)

    print(f"rules selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
