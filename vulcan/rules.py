"""Vulcan automation engine: condition/schedule/event rules.

Rules are plain JSON (see content.DEFAULT_RULES). The engine evaluates
tick rules every world tick, fires schedule rules when the simulated
clock crosses their time, and dispatches event rules against events
raised by the physics step. Alert-style actions are rate-limited per
rule via alert_cooldown_ticks; ordinary actuator writes are idempotent
no-ops when nothing changes, so tick rules can run freely.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import copy
from collections import deque

import content

CONDITION_KINDS = {"zone", "device", "mode", "clock", "all", "any", "not",
                   "power", "zone_count", "trend"}
ACTION_KINDS = {"device", "hvac", "scene", "mode", "alert", "lock_all",
                "unlock_all", "lights_all", "hvac_all_off", "shed",
                "sequence", "device_group", "log"}
TRIGGER_TYPES = {"tick", "schedule", "event"}
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
       ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
TREND_EPSILON = 0.05
MAX_PENDING_SEQUENCES = 100


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class RuleEngine:
    def __init__(self, world, warden=True):
        self.world = world
        self.rules = []
        self._last_minute = world.clock_minutes()
        self._alert_last_tick = {}
        self.pending = deque(maxlen=MAX_PENDING_SEQUENCES)
        self.failures = {}
        self.quarantined = {}
        if warden:
            from warden import Warden
            self.warden_obj = Warden()
        else:
            self.warden_obj = None
        for spec in content.DEFAULT_RULES:
            rule = copy.deepcopy(spec)
            rule["builtin"] = True
            rule["enabled"] = True
            self.rules.append(rule)

    # ---------- CRUD ----------

    def add_rule(self, spec):
        rule = dict(spec)
        rid = str(rule.get("id") or "").strip()
        if not rid:
            raise ValueError("rule needs an id")
        if any(r["id"] == rid for r in self.rules):
            raise ValueError(f"rule id already exists: {rid}")
        if not rule.get("name"):
            rule["name"] = rid
        trig = rule.get("trigger")
        if not isinstance(trig, dict) or \
                trig.get("type") not in TRIGGER_TYPES:
            raise ValueError(f"trigger.type must be one of "
                             f"{sorted(TRIGGER_TYPES)}")
        if trig["type"] == "schedule" and "time" not in trig:
            raise ValueError("schedule trigger needs time HH:MM")
        if trig["type"] == "event" and "event" not in trig:
            raise ValueError("event trigger needs event name")
        if trig["type"] == "tick":
            if rule.get("when") is not None:
                self._validate_condition(rule["when"])
        else:
            if rule.get("when"):
                self._validate_condition(rule["when"])
        actions = rule.get("then")
        if not isinstance(actions, list) or not actions:
            raise ValueError("rule needs a non-empty then: [actions]")
        for act in actions:
            self._validate_action(act)
        if rule.get("else"):
            for act in rule["else"]:
                self._validate_action(act)
        rule["builtin"] = False
        rule["enabled"] = bool(rule.get("enabled", True))
        if "priority" in rule:
            rule["priority"] = int(rule["priority"])
        if "max_fires" in rule:
            mf = int(rule["max_fires"])
            if mf < 1:
                raise ValueError("max_fires must be >= 1")
            rule["max_fires"] = mf
        if "run_in_modes" in rule:
            modes = rule["run_in_modes"]
            bad = [m for m in modes if m not in content.MODES]
            if bad:
                raise ValueError(f"unknown modes: {bad}")
        self.rules.append(rule)
        return rule

    def _validate_action(self, act):
        if not isinstance(act, dict) or act.get("kind") \
                not in ACTION_KINDS:
            raise ValueError(f"action kinds: {sorted(ACTION_KINDS)}")
        kind = act["kind"]
        if kind == "sequence":
            steps = act.get("steps")
            if not isinstance(steps, list) or not steps:
                raise ValueError("sequence needs non-empty steps")
            for step in steps:
                if not isinstance(step, list) or not step:
                    raise ValueError("sequence steps must be non-empty "
                                     "action lists")
                for sub in step:
                    self._validate_action(sub)
            gap = int(act.get("gap_ticks", 1))
            if gap < 0:
                raise ValueError("gap_ticks must be >= 0")
        elif kind == "device_group":
            dtype = act.get("type")
            if dtype not in content.DEVICE_TYPES:
                raise ValueError(f"unknown device type: {dtype}")
            if not isinstance(act.get("set") or {}, dict):
                raise ValueError("device_group needs set object")

    def _validate_condition(self, cond):
        if not isinstance(cond, dict) or cond.get("kind") \
                not in CONDITION_KINDS:
            raise ValueError(f"condition kinds: {sorted(CONDITION_KINDS)}")
        kind = cond["kind"]
        if kind in ("all", "any"):
            subs = cond.get(kind)
            if not isinstance(subs, list) or not subs:
                raise ValueError(f"{kind} needs a non-empty list")
            for sub in subs:
                self._validate_condition(sub)
        elif kind == "not":
            self._validate_condition(cond.get("not"))
        elif kind in ("zone", "device"):
            if kind == "zone" and "zone" not in cond:
                raise ValueError("zone condition needs zone")
            if kind == "device" and "device" not in cond:
                raise ValueError("device condition needs device")
            if cond.get("op") not in OPS or "attr" not in cond:
                raise ValueError("condition needs attr and op in "
                                 + str(sorted(OPS)))
        elif kind == "power":
            if cond.get("op") not in OPS or "value" not in cond:
                raise ValueError("power condition needs op and value")
        elif kind == "zone_count":
            if cond.get("op") not in OPS or "value" not in cond \
                    or "count" not in cond:
                raise ValueError("zone_count needs attr, op, value, "
                                 "count")
        elif kind == "trend":
            if "zone" not in cond:
                raise ValueError("trend needs zone")
            if cond.get("direction") not in ("rising", "falling", "flat"):
                raise ValueError("trend direction must be rising/"
                                 "falling/flat")

    def toggle_rule(self, rule_id, enabled=None):
        rule = self._get(rule_id)
        rule["enabled"] = (not rule["enabled"]) if enabled is None \
            else bool(enabled)
        return rule

    def delete_rule(self, rule_id):
        rule = self._get(rule_id)
        if rule.get("builtin"):
            raise ValueError("builtin rules cannot be deleted; toggle "
                             "them instead")
        self.rules = [r for r in self.rules if r["id"] != rule_id]

    def list_rules(self):
        out = []
        for r in self.rules:
            clean = {k: v for k, v in r.items()
                     if k not in ("_last_value",)}
            out.append(clean)
        return out

    def export_state(self):
        """Snapshot for persistence (user rules + enabled flags)."""
        return {"rules": copy.deepcopy(self.rules)}

    def import_state(self, state):
        """Restore saved automation; missing key keeps defaults."""
        rules = (state or {}).get("rules")
        if not rules:
            return 0
        if not isinstance(rules, list):
            raise ValueError("automation payload must be a list")
        seen = set()
        for r in rules:
            rid = r.get("id") if isinstance(r, dict) else None
            if not rid or rid in seen:
                raise ValueError(f"bad or duplicate rule id: {rid}")
            seen.add(rid)
        self.rules = copy.deepcopy(rules)
        return len(self.rules)

    def _get(self, rule_id):
        for r in self.rules:
            if r["id"] == rule_id:
                return r
        raise KeyError(f"unknown rule: {rule_id}")

    # ---------- evaluation ----------

    def on_tick(self, world, fired_events):
        self._revive_quarantined(world)
        self._drain_pending(world)
        now = world.clock_minutes()
        crossed = set()
        prev = self._last_minute
        self._last_minute = now
        for r in self.rules:
            if r["enabled"] and r["trigger"]["type"] == "schedule":
                target = self._hhmm(r["trigger"]["time"])
                if self._crossed(prev, now, target):
                    crossed.add(r["id"])
        ctx_base = self._base_context(world)
        last_text = world.events[-1]["text"] if world.events else None
        for entry in fired_events:
            who = entry.get('device') or entry.get('zone') or ""
            watts = f" {entry['watts']} W" if 'watts' in entry else ""
            text = f"{entry['event']} {who}{watts}".strip()
            if text != last_text:
                world.log("event", text)
            last_text = text
        ordered = sorted((r for r in self.rules if r["enabled"]),
                         key=lambda r: -int(r.get("priority", 0)))
        for rule in ordered:
            if not rule["enabled"]:
                continue
            modes = rule.get("run_in_modes")
            if modes and world.mode not in modes:
                continue
            trig = rule["trigger"]
            ttype = trig["type"]
            fired_match = None
            if ttype == "tick":
                fired_match = [{}]
            elif ttype == "schedule":
                if rule["id"] in crossed:
                    fired_match = [{}]
            elif ttype == "event":
                fired_match = [e for e in fired_events
                               if e.get("event") == trig["event"]]
            for entry in fired_match or ():
                ctx = dict(ctx_base)
                ctx.update({k: v for k, v in entry.items()
                            if isinstance(v, (str, int, float))})
                branch = "then" \
                    if self._match(rule.get("when"), world, ctx) \
                    else "else"
                if branch == "then":
                    self._fire(rule, world, ctx)
                elif rule.get("else"):
                    self._run(rule, "else", world, ctx)
        if self.warden_obj is not None:
            try:
                self.warden_obj.patrol(world)
            except Exception as exc:
                world.log("heal", f"warden patrol error: {exc!r}")

    def _fire(self, rule, world, ctx):
        """Run then-branch under the circuit breaker; honor max_fires."""
        rid = rule["id"]
        try:
            self._run(rule, "then", world, ctx)
        except Exception as exc:
            fails = self.failures.get(rid, 0) + 1
            self.failures[rid] = fails
            limit = int(content.WARDEN["rule_fail_limit"])
            world.log("heal", f"rule {rid} failed ({fails}/{limit}): "
                              f"{exc!r}")
            if fails >= limit:
                revive = int(content.WARDEN["rule_revive_ticks"])
                rule["enabled"] = False
                self.quarantined[rid] = world.tick_count + revive
                world.alert("warn", f"rule {rid} auto-disabled after "
                                    f"{fails} failures; revival in "
                                    f"{revive} ticks")
            return
        mf = rule.get("max_fires")
        if mf is not None:
            rule["_fires"] = rule.get("_fires", 0) + 1
            if rule["_fires"] >= int(mf):
                rule["enabled"] = False
                world.log("heal", f"rule {rid} exhausted "
                                  f"max_fires={mf} - disabled")

    def _revive_quarantined(self, world):
        due = [rid for rid, at in self.quarantined.items()
               if world.tick_count >= at]
        for rid in due:
            self.quarantined.pop(rid, None)
            self.failures.pop(rid, None)
            for r in self.rules:
                if r["id"] == rid:
                    r["enabled"] = True
                    break
            world.log("heal", f"rule {rid} revived from quarantine")

    def _drain_pending(self, world):
        if not self.pending:
            return
        now = world.tick_count
        due_now = []
        keep = deque(maxlen=MAX_PENDING_SEQUENCES)
        while self.pending:
            item = self.pending[0]
            if item["due"] <= now and len(due_now) < 32:
                due_now.append(self.pending.popleft())
            else:
                keep.append(self.pending.popleft())
        self.pending = keep
        for item in due_now:
            for act in item["actions"]:
                try:
                    self._execute(act, world, item["ctx"],
                                  item.get("rule") or {"id": "sequence"})
                except Exception as exc:
                    world.log("heal", f"sequence step error: {exc!r}")

    def _base_context(self, world):
        coldest, temp = None, None
        for z in world.zones.values():
            if temp is None or z.temp < temp:
                coldest, temp = z.name, z.temp
        return {"coldest": coldest or "", "temp": temp if temp is not None
                else 0.0}

    def _run(self, rule, branch, world, ctx):
        for act in rule.get(branch, []):
            self._execute(act, world, ctx, rule)

    def _execute(self, act, world, ctx, rule):
        kind = act["kind"]
        if kind == "device":
            dev_id = str(act.get("device", "")).format_map(SafeDict(ctx))
            try:
                world.set_device(dev_id, act.get("set") or {})
            except KeyError:
                pass
        elif kind == "hvac":
            zone = str(act.get("zone", "")).format_map(SafeDict(ctx))
            try:
                world.set_hvac(zone, act.get("set") or {})
            except KeyError:
                pass
        elif kind == "scene":
            try:
                world.apply_scene(act["name"])
            except KeyError:
                pass
        elif kind == "mode":
            try:
                world.set_mode(act["name"])
            except ValueError:
                pass
        elif kind == "alert":
            cooldown = int(rule.get("alert_cooldown_ticks", 1))
            last = self._alert_last_tick.get(rule["id"], -10 ** 9)
            if world.tick_count - last >= cooldown:
                self._alert_last_tick[rule["id"]] = world.tick_count
                msg = str(act.get("message", "")).format_map(SafeDict(ctx))
                world.alert(act.get("level", "warn"), msg)
        elif kind == "lock_all":
            for d in world.devices.values():
                if d.type == "lock":
                    d.apply({"locked": True})
        elif kind == "unlock_all":
            for d in world.devices.values():
                if d.type == "lock":
                    d.apply({"locked": False})
        elif kind == "lights_all":
            for d in world.devices.values():
                if d.type == "light":
                    d.apply(act.get("set") or {})
        elif kind == "hvac_all_off":
            for d in world.devices.values():
                if d.type == "hvac":
                    d.apply({"mode": "off"})
        elif kind == "shed":
            self._shed(world)
        elif kind == "sequence":
            gap = int(act.get("gap_ticks", 1))
            steps = act.get("steps") or []
            due = world.tick_count
            for i, step in enumerate(steps):
                if i > 0:
                    due += gap
                self.pending.append({"due": due, "actions": step,
                                     "ctx": dict(ctx), "rule": rule})
        elif kind == "device_group":
            dtype = act.get("type")
            zone_filter = act.get("zone")
            changes = act.get("set") or {}
            for dev in world.devices.values():
                if dev.type != dtype or not dev.actuator:
                    continue
                if zone_filter and dev.zone != str(zone_filter).format_map(
                        SafeDict(ctx)):
                    continue
                try:
                    dev.apply(changes)
                except ValueError:
                    pass
        elif kind == "log":
            text = str(act.get("text", "")).format_map(SafeDict(ctx))
            world.log("note", text)

    def _shed(self, world):
        limit = content.POWER_LIMIT_W
        shedded = []
        for dev_id in content.LOAD_SHED_ORDER:
            if world.building_power_w() <= limit:
                break
            dev = world.devices.get(dev_id)
            if dev is not None and getattr(dev, "on", False):
                dev.apply({"on": False})
                shedded.append(dev_id)
        if shedded:
            world.alert("warn", "load shed: turned off "
                                + ", ".join(shedded))

    def _match(self, cond, world, ctx):
        if cond is None:
            return True
        kind = cond["kind"]
        if kind == "all":
            return all(self._match(c, world, ctx) for c in cond["all"])
        if kind == "any":
            return any(self._match(c, world, ctx) for c in cond["any"])
        if kind == "not":
            return not self._match(cond["not"], world, ctx)
        if kind == "mode":
            return OPS[cond.get("op", "==")](world.mode,
                                             cond.get("value"))
        if kind == "clock":
            now = world.clock_minutes()
            start = self._hhmm(cond.get("after", "00:00"))
            end = self._hhmm(cond.get("before", "23:59")) + 1
            if start <= end:
                return start <= now < end
            return now >= start or now < end
        if kind == "power":
            return self._compare(world.building_power_w(), cond, ctx)
        if kind == "zone_count":
            attr = str(cond.get("attr", "temp"))
            count = 0
            for zone in world.zones.values():
                actual = self._zone_attr(zone, attr, ctx)
                if self._compare(actual, cond, ctx):
                    count += 1
            return count >= int(cond.get("count", 1))
        if kind == "trend":
            zone = world.zones.get(
                str(cond["zone"]).format_map(SafeDict(ctx)))
            if zone is None:
                return False
            window = int(cond.get("window", len(zone.history) or 1))
            hist = list(zone.history)[-window:]
            if len(hist) < 2:
                return cond.get("direction") == "flat"
            delta = hist[-1] - hist[0]
            direction = cond.get("direction")
            if direction == "rising":
                return delta > TREND_EPSILON
            if direction == "falling":
                return delta < -TREND_EPSILON
            return abs(delta) <= TREND_EPSILON
        if kind == "zone":
            zone_name = str(cond["zone"]).format_map(SafeDict(ctx))
            zone = world.zones.get(zone_name)
            if zone is None:
                return False
            actual = self._zone_attr(zone, str(cond.get("attr", "temp")),
                                     ctx)
            return self._compare(actual, cond, ctx)
        if kind == "device":
            dev_id = str(cond["device"]).format_map(SafeDict(ctx))
            dev = world.devices.get(dev_id)
            if dev is None:
                return False
            snap = dev.snapshot()
            actual = snap.get(str(cond.get("attr", "")))
            return self._compare(actual, cond, ctx)
        return False

    @staticmethod
    def _zone_attr(zone, attr, ctx):
        if attr == "temp":
            return round(zone.temp, 2)
        if attr == "occupants":
            return zone.occupants()
        if attr == "power_w":
            return sum(d.watts() for d in zone.devices.values())
        return None

    def _compare(self, actual, cond, ctx):
        value = cond.get("value")
        op = OPS[cond.get("op", "==")]
        try:
            if isinstance(actual, bool) or isinstance(value, bool):
                return op(bool(actual), bool(value))
            return op(actual, value)
        except TypeError:
            return False

    @staticmethod
    def _hhmm(s):
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)

    @staticmethod
    def _crossed(prev, now, target):
        if prev == now:
            return False
        if prev < now:
            return prev < target <= now
        return target > prev or target <= now
