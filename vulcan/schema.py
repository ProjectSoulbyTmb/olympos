"""Vulcan RIG-schema: rules and saves validate themselves at the door
(Pkl model). A rule either parses against this grammar or is rejected
with a precise message before anything can execute it. Saves are
audited leniently - errors alert, unknown keys log - so forward
compatibility stays sacred.

Grammar ownership stays in rules.py (kind sets); this module only
reads it. Adding a kind touches: rules.py set -> schema row here ->
verify check. Three places, same as verbs.
"""

import re

import content
from rules import ACTION_KINDS, CONDITION_KINDS, OPS, TRIGGER_TYPES

MAX_DEPTH = 8
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

TOP_KEYS = {"version", "saved_at", "clock", "mode", "outside_temp",
            "tick_count", "kwh_total", "zones", "devices", "automation"}
DEVICE_STATE_KEYS = {"type", "on", "brightness", "locked", "open",
                     "people", "alarm", "mode", "target"}


def _err(cond, msg, out):
    if not cond:
        out.append(msg)
    return cond


def _walk_condition(cond, depth, out, where="when"):
    if depth > MAX_DEPTH:
        out.append(f"{where}: condition nesting deeper than {MAX_DEPTH}")
        return
    if not isinstance(cond, dict) or cond.get("kind") \
            not in CONDITION_KINDS:
        out.append(f"{where}.kind must be one of {sorted(CONDITION_KINDS)}")
        return
    kind = cond["kind"]
    nxt = f"{where}.{kind}"
    if kind in ("all", "any"):
        subs = cond.get(kind)
        if not isinstance(subs, list) or not subs:
            out.append(f"{nxt}: needs a non-empty list")
            return
        for sub in subs:
            _walk_condition(sub, depth + 1, out, where=nxt)
    elif kind == "not":
        _walk_condition(cond.get("not"), depth + 1, out, where=nxt)
    elif kind in ("zone", "device"):
        if kind == "zone":
            _err("zone" in cond, f"{nxt}: needs zone", out)
        else:
            _err("device" in cond, f"{nxt}: needs device", out)
        _err(cond.get("op") in OPS and "attr" in cond,
             f"{nxt}: needs attr and op in {sorted(OPS)}", out)
    elif kind == "power":
        _err(cond.get("op") in OPS and "value" in cond,
             f"{nxt}: needs op and value", out)
    elif kind == "zone_count":
        _err(cond.get("op") in OPS and "value" in cond
             and "count" in cond,
             f"{nxt}: needs attr/op/value/count", out)
    elif kind == "trend":
        _err("zone" in cond, f"{nxt}: needs zone", out)
        _err(cond.get("direction") in ("rising", "falling", "flat"),
             f"{nxt}: direction must be rising/falling/flat", out)


def _walk_action(act, depth, out):
    if not isinstance(act, dict) or act.get("kind") not in ACTION_KINDS:
        out.append(f"action.kind must be one of {sorted(ACTION_KINDS)}")
        return
    kind = act["kind"]
    if depth > MAX_DEPTH:
        out.append(f"action {kind}: nesting deeper than {MAX_DEPTH}")
        return
    if kind == "sequence":
        steps = act.get("steps")
        if not isinstance(steps, list) or not steps:
            out.append("sequence: needs non-empty steps")
            return
        gap = act.get("gap_ticks", 1)
        if not isinstance(gap, int) or gap < 0:
            out.append("sequence.gap_ticks must be an int >= 0")
        for i, step in enumerate(steps):
            if not isinstance(step, list) or not step:
                out.append(f"sequence.steps[{i}]: must be a non-empty "
                           "action list")
                continue
            for sub in step:
                _walk_action(sub, depth + 1, out)
    elif kind == "device_group":
        if act.get("type") not in content.DEVICE_TYPES:
            out.append(f"device_group.type unknown: {act.get('type')!r}")
        if not isinstance(act.get("set") or {}, dict):
            out.append("device_group.set must be an object")
    elif kind == "alert":
        _err(isinstance(act.get("message"), str) or
             isinstance(act.get("text"), str),
             "alert: needs message (or text)", out)


def validate_rule(spec):
    """-> list of human-readable problems; [] means the rule is valid."""
    out = []
    if not isinstance(spec, dict):
        return ["rule must be an object"]
    _err(bool(str(spec.get("id") or "").strip()), "id must be a "
         "non-empty string", out)
    trig = spec.get("trigger")
    if not isinstance(trig, dict) or trig.get("type") \
            not in TRIGGER_TYPES:
        out.append(f"trigger.type must be one of {sorted(TRIGGER_TYPES)}")
    elif trig["type"] == "schedule":
        _err(bool(_TIME_RE.match(str(trig.get("time") or ""))),
             "schedule trigger needs time HH:MM (24h)", out)
    elif trig["type"] == "event":
        _err(bool(str(trig.get("event") or "").strip()),
             "event trigger needs an event name", out)
    when = spec.get("when")
    if when is not None:
        _walk_condition(when, 0, out)
    then = spec.get("then")
    if not isinstance(then, list) or not then:
        out.append("rule needs a non-empty then: [actions]")
        return out
    for act in then:
        _walk_action(act, 0, out)
    for act in spec.get("else", []) or []:
        _walk_action(act, 0, out)
    if "priority" in spec and not isinstance(spec["priority"], int):
        out.append("priority must be an int")
    if "max_fires" in spec:
        mf = spec["max_fires"]
        if not isinstance(mf, int) or mf < 1:
            out.append("max_fires must be an int >= 1")
    modes = spec.get("run_in_modes")
    if modes is not None:
        if not isinstance(modes, list):
            out.append("run_in_modes must be a list")
        else:
            bad = [m for m in modes if m not in content.MODES]
            if bad:
                out.append(f"run_in_modes unknown: {bad}")
    return out


def audit_save(data):
    """Lenient save audit -> list of 'error: ...' / 'warn: ...' lines."""
    out = []
    if not isinstance(data, dict):
        return ["error: save payload must be an object"]
    version = data.get("version", 1)
    if not isinstance(version, int) or version < 1:
        out.append(f"error: bad save version {version!r}")
    elif version > content.SAVE_VERSION:
        out.append(f"error: save version {version} newer than "
                   f"{content.SAVE_VERSION}")
    clock = data.get("clock")
    if clock is not None and (
            not isinstance(clock, list) or len(clock) != 5 or
            not all(isinstance(v, int) for v in clock)):
        out.append("error: clock must be 5 integers [y mo d h mi]")
    mode = data.get("mode")
    if mode is not None and mode not in content.MODES:
        out.append(f"error: unknown mode {mode!r}")
    for key in sorted(set(data) - TOP_KEYS):
        out.append(f"warn: unknown save key '{key}' (kept, logged)")
    devices = data.get("devices")
    if isinstance(devices, dict):
        for dev_id, ds in devices.items():
            if not isinstance(ds, dict):
                out.append(f"error: device {dev_id}: payload not object")
                continue
            for key in sorted(set(ds) - DEVICE_STATE_KEYS):
                out.append(f"warn: device {dev_id}: unknown key '{key}'")
    zones = data.get("zones")
    if zones is not None and not isinstance(zones, dict):
        out.append("error: zones must be an object")
    return out


def quarantine_report(specs):
    """Validate a batch of saved rules without raising.
    -> (valid_specs, [(spec, errors)])"""
    good, bad = [], []
    for spec in specs:
        errs = validate_rule(spec) if isinstance(spec, dict) else \
            ["rule must be an object"]
        (good if not errs else bad).append(
            spec if not errs else (spec, errs))
    return good, bad
