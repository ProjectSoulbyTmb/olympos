"""MIND flows - operator-authored reactions, planned purely.

A flow is `on` an event name, optionally gated by `when.scene_in` and a
per-flow cooldown, and runs ordered steps. Planning is a pure function
(no I/O, no clock reads) so it is trivially gate-testable; execution
lives in the director.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import mind.snapshot as snapshot

MAX_STEPS = 16
MAX_WAIT_SECONDS = 120.0

ACTION_KEYS = {
    "log": ("message",),
    "wait": ("seconds",),
    "switch_scene": ("sceneName",),
    "set_stream": ("state",),
    "set_recording": ("state",),
    "http_get": ("url",),
}


@dataclass
class Flow:
    id: str
    on: str
    then: list = field(default_factory=list)
    when_scene_in: list = field(default_factory=list)
    cooldown_s: float = 0.0


def _fail(problems, flow_id, message):
    problems.append(f"{flow_id or '?'}: {message}")


def validate_step(flow_id, raw, problems) -> dict:
    if not isinstance(raw, dict):
        _fail(problems, flow_id, "step must be an object")
        return {}
    action = raw.get("action")
    if action not in ACTION_KEYS:
        _fail(problems, flow_id,
              f"unknown action {action!r} "
              f"(known: {', '.join(sorted(ACTION_KEYS))})")
        return {}
    step = {"action": action}
    if action == "log":
        msg = raw.get("message")
        if not isinstance(msg, str) or not msg.strip():
            _fail(problems, flow_id, "log needs a non-empty message")
            return {}
        step["message"] = msg.strip()
    elif action == "wait":
        try:
            seconds = float(raw.get("seconds"))
        except (TypeError, ValueError):
            _fail(problems, flow_id, "wait needs numeric seconds")
            return {}
        if not 0 < seconds <= MAX_WAIT_SECONDS:
            _fail(problems, flow_id,
                  f"wait seconds must be 0 < s <= {MAX_WAIT_SECONDS}")
            return {}
        step["seconds"] = seconds
    elif action == "switch_scene":
        name = raw.get("sceneName") or raw.get("scene")
        if not isinstance(name, str) or not name.strip():
            _fail(problems, flow_id, "switch_scene needs sceneName")
            return {}
        step["sceneName"] = name.strip()
    elif action in ("set_stream", "set_recording"):
        state = raw.get("state")
        if state not in ("start", "stop"):
            _fail(problems, flow_id,
                  f"{action} state must be 'start' or 'stop'")
            return {}
        step["state"] = state
    elif action == "http_get":
        url = raw.get("url")
        if (not isinstance(url, str)
                or not url.startswith(("http://", "https://"))):
            _fail(problems, flow_id, "http_get needs an http(s) url")
            return {}
        step["url"] = url
    return step


def parse_flows(config_flows) -> list:
    """Parse + validate config flows; ValueError lists every problem."""
    problems = []
    parsed = []
    for i, raw in enumerate(config_flows or []):
        if not isinstance(raw, dict):
            _fail(problems, None, f"flow #{i} must be an object")
            continue
        fid = str(raw.get("id") or f"flow-{i}")
        on = raw.get("on")
        if not isinstance(on, str) or not on.strip():
            _fail(problems, fid, "missing event name for 'on'")
            continue
        on = on.strip()
        if on not in snapshot.ALL_EVENTS:
            _fail(problems, fid,
                  f"unknown event {on!r} "
                  f"(known: {', '.join(snapshot.ALL_EVENTS)})")
            continue
        when = raw.get("when") or {}
        scene_in = when.get("scene_in") if isinstance(when, dict) else None
        if scene_in is not None and (
                not isinstance(scene_in, list)
                or not all(isinstance(s, str) and s.strip()
                           for s in scene_in)):
            _fail(problems, fid, "when.scene_in must be a list of names")
            continue
        try:
            cooldown = float(raw.get("cooldown_s", 0))
        except (TypeError, ValueError):
            _fail(problems, fid, "cooldown_s must be a number")
            continue
        if cooldown < 0:
            _fail(problems, fid, "cooldown_s must be >= 0")
            continue
        steps_raw = raw.get("then")
        if not isinstance(steps_raw, list) or not steps_raw:
            _fail(problems, fid, "then must be a non-empty list of steps")
            continue
        if len(steps_raw) > MAX_STEPS:
            _fail(problems, fid, f"too many steps (max {MAX_STEPS})")
            continue
        steps = [validate_step(fid, s, problems) for s in steps_raw]
        steps = [s for s in steps if s]
        if len(steps) != len(steps_raw):
            continue  # step problems already recorded
        parsed.append(Flow(id=fid, on=on, then=steps,
                           when_scene_in=[s.strip() for s in (scene_in or [])],
                           cooldown_s=cooldown))
    if problems:
        raise ValueError("invalid flows:\n  - " + "\n  - ".join(problems))
    return parsed


def plan(flows, event_type: str, data: dict, now: float,
         last_fired: dict) -> list:
    """Pure decision pass -> [(flow, executable_steps)] in config order."""
    fired = []
    data = data or {}
    for flow in flows:
        if flow.on != event_type:
            continue
        if flow.when_scene_in:
            scope = data.get("scope", "program")
            if scope != "program":
                continue
            if data.get("sceneName") not in flow.when_scene_in:
                continue
        last = last_fired.get(flow.id)
        if last is not None and (now - last) < flow.cooldown_s:
            continue
        fired.append((flow, [dict(step) for step in flow.then]))
    return fired


def selftest() -> int:
    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL flows.{name}")
            failures.append(name)

    good = [
        {"id": "a", "on": "stream_started",
         "then": [{"action": "log", "message": "live"}]},
        {"id": "b", "on": "scene_changed",
         "when": {"scene_in": ["BRB"]}, "cooldown_s": 60,
         "then": [{"action": "wait", "seconds": 1},
                  {"action": "switch_scene", "sceneName": "Live"}]},
    ]
    flows = parse_flows(good)
    check("parse-ok", len(flows) == 2)

    def t_bad_event():
        try:
            parse_flows([{"id": "x", "on": "martians",
                          "then": [{"action": "log", "message": "m"}]}])
            return False
        except ValueError as exc:
            return "unknown event" in str(exc)

    def t_bad_action():
        try:
            parse_flows([{"id": "y", "on": "stream_started",
                          "then": [{"action": "detonate"}]}])
            return False
        except ValueError:
            return True

    def t_empty_then():
        try:
            parse_flows([{"id": "z", "on": "stream_started",
                          "then": []}])
            return False
        except ValueError:
            return True

    last = {}

    def fire(now):
        return plan(flows, "scene_changed",
                    {"scope": "program", "sceneName": "BRB"}, now, last)

    got = fire(0.0)
    check("plan-matches-scene",
          len(got) == 1 and got[0][0].id == "b"
          and [s["action"] for s in got[0][1]] == ["wait", "switch_scene"])

    check("plan-ignores-other-event",
          plan(flows, "recording_started", {}, 5.0, last) == [])

    check("plan-ignores-preview-scope",
          plan(flows, "scene_changed",
               {"scope": "preview", "sceneName": "BRB"}, 5.0, last) == [])

    last["b"] = 10.0
    check("cooldown-blocks-within-window", fire(30.0) == [])
    check("cooldown-allows-after-window", len(fire(90.0)) == 1)

    check("bad-event-refused", t_bad_event())
    check("bad-action-refused", t_bad_action())
    check("empty-then-refused", t_empty_then())

    print(f"flows selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
