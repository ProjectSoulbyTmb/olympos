"""Vulcan world: the authoritative building model.

Owns simulated time, zone thermodynamics, device state, event and alert
logs and power history. Mechanics only - decisions live in rules.py,
data lives in content.py. Save format is versioned (v1) with load-side
defaults for missing keys.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import calendar
import json
import os
import shutil
import time as _time
from collections import deque

from devices import Device, Zone

import content


def now_str(clock):
    return "%04d-%02d-%02d %02d:%02d" % tuple(clock)


class World:
    """One building. All mutations go through methods here; the server
    serializes access with a lock."""

    def __init__(self):
        self.zones = {}
        self.devices = {}
        self.mode = "home"
        self.tick_count = 0
        self.kwh_total = 0.0
        y, mo, d, h, mi = content.START_CLOCK
        self.clock = [y, mo, d, h, mi]
        self.events = deque(maxlen=content.MAX_EVENTS)
        self.alerts = deque(maxlen=content.MAX_ALERTS)
        self.stats = deque(maxlen=content.MAX_STATS)
        self.outside_temp = content.OUTSIDE_TEMP_C
        self.pending_events = []
        self._build_from_content()

    def _build_from_content(self):
        for spec in content.SEED_ZONES:
            zone = Zone(spec["name"], spec["floor"], spec["area_m2"],
                        spec["adjacent"])
            for dev in spec["devices"]:
                d = Device(dev["id"], dev["type"], zone.name)
                zone.devices[d.id] = d
                self.devices[d.id] = d
            self.zones[zone.name] = zone
        self.log("boot", f"building online: {len(self.zones)} zones, "
                         f"{len(self.devices)} devices")

    # ---------- logging ----------

    def log(self, kind, text):
        self.events.append({"t": self.tick_stamp(), "kind": kind,
                            "text": text})

    def alert(self, level, text):
        entry = {"t": self.tick_stamp(), "level": level, "text": text}
        self.alerts.append(entry)
        self.log("alert", f"[{level}] {text}")
        try:                    # mirror to the Ratatosk post office
            from ratatosk import publish
            publish("vulcan", entry, frm="vulcan", kind=str(level))
        except Exception:
            pass
        return entry

    def tick_stamp(self):
        return {"tick": self.tick_count, "clock": now_str(self.clock)}

    # ---------- clock / time ----------

    def advance_clock(self):
        total = self.clock[3] * 60 + self.clock[4] + content.TICK_MINUTES_SIM
        self.clock[3], self.clock[4] = divmod(total, 60)
        day_carried = 0
        while self.clock[3] >= 24:
            self.clock[3] -= 24
            day_carried += 1
        if day_carried:
            dim = calendar.monthrange(self.clock[0], self.clock[1])[1]
            self.clock[2] += day_carried
            while self.clock[2] > dim:
                self.clock[2] -= dim
                self.clock[1] += 1
                if self.clock[1] > 12:
                    self.clock[1] = 1
                    self.clock[0] += 1
                dim = calendar.monthrange(self.clock[0], self.clock[1])[1]

    def clock_minutes(self):
        return self.clock[3] * 60 + self.clock[4]

    def is_daytime(self):
        return 7 <= self.clock[3] < 19

    # ---------- intents (called by SDK / rules engine) ----------

    def set_device(self, dev_id, changes):
        dev = self.devices.get(dev_id)
        if dev is None:
            raise KeyError(f"unknown device: {dev_id}")
        applied = dev.apply(changes)
        if applied:
            pretty = ", ".join(f"{k}={changes[k]}" for k in applied)
            self.log("device", f"{dev_id}: {pretty}")
        return dev.snapshot()

    def set_hvac(self, zone_name, changes):
        zone = self.zones.get(zone_name)
        if zone is None:
            raise KeyError(f"unknown zone: {zone_name}")
        hvacs = zone.by_type("hvac")
        if not hvacs:
            raise ValueError(f"zone {zone_name} has no HVAC unit")
        applied = hvacs[0].apply(changes)
        snap = hvacs[0].snapshot()
        snap["applied"] = applied
        return snap

    def motion(self, zone_name, people=1):
        zone = self._zone(zone_name)
        occs = zone.by_type("occupancy")
        if not occs:
            raise ValueError(f"zone {zone_name} has no occupancy sensor")
        occ = occs[0]
        occ.people = max(0, int(people))
        occ.idle_ticks = 0
        self.log("motion", f"{zone_name}: {occ.people} present")
        self.pending_events.append({"event": "motion", "zone": zone_name,
                                    "device": occ.id})
        return occ.snapshot()

    def set_contact(self, dev_id, is_open):
        dev = self.devices.get(dev_id)
        if dev is None or dev.type != "contact":
            raise KeyError(f"no contact device: {dev_id}")
        prev, dev.open = dev.open, bool(is_open)
        if prev != dev.open:
            kind = "contact_open" if dev.open else "contact_closed"
            self.log(kind, f"{dev_id} {'opened' if dev.open else 'closed'}")
            return {"event": kind, "device": dev_id}
        return {"event": None, "device": dev_id}

    def smoke_alarm(self, dev_id, active=True):
        dev = self.devices.get(dev_id)
        if dev is None or dev.type != "smoke":
            raise KeyError(f"no smoke detector: {dev_id}")
        prev, dev.alarm = dev.alarm, bool(active)
        if not prev and dev.alarm:
            return {"event": "smoke", "zone": dev.zone}
        if prev and not dev.alarm:
            self.log("smoke_clear", f"{dev_id} reset")
        return {"event": None, "zone": dev.zone}

    def set_outside_temp(self, celsius):
        c = float(celsius)
        if not -40.0 <= c <= 55.0:
            raise ValueError("outside temp must be -40..55 C")
        self.outside_temp = c
        self.log("weather", f"outside temperature now {c:.1f} C")

    def apply_scene(self, scene_name):
        scene = content.SCENES.get(scene_name)
        if scene is None:
            raise KeyError(f"unknown scene: {scene_name}")
        lights = scene.get("lights") or {}
        only = set(lights.get("only", []))
        for dev in self.devices.values():
            if dev.type == "light":
                if only and dev.id not in only:
                    continue
                changes = {}
                if "on" in lights:
                    changes["on"] = lights["on"]
                if "brightness" in lights:
                    changes["brightness"] = lights["brightness"]
                if changes:
                    dev.apply(changes)
            elif dev.type == "blind" and "blinds" in scene:
                dev.apply({"open": scene["blinds"]})
            elif dev.type == "lock" and "locks" in scene:
                dev.apply({"locked": scene["locks"]})
            elif dev.type == "hvac" and scene.get("hvac"):
                dev.apply(dict(scene["hvac"]))
            elif dev.type == "plug" and scene.get("plugs") is not None:
                dev.apply({"on": scene["plugs"]})
            elif dev.type == "fan" and scene.get("fans") is not None:
                dev.apply({"on": scene["fans"]})
        self.log("scene", f"scene '{scene_name}' applied")

    def set_mode(self, mode_name):
        if mode_name not in content.MODES:
            raise ValueError(f"mode must be one of {content.MODES}")
        self.mode = mode_name
        scene_for_mode = {"away": "away", "vacation": "vacation",
                          "night": "night", "home": "day"}
        if mode_name in scene_for_mode:
            try:
                self.apply_scene(scene_for_mode[mode_name])
            except KeyError:
                pass
        self.log("mode", f"building mode -> {mode_name}")

    # ---------- physics ----------

    def _step_thermal(self, fired_events):
        for zone in self.zones.values():
            zone.history.append(round(zone.temp, 3))
            loss = content.ENVELOPE_LOSS_PER_TICK
            for contact in zone.by_type("contact"):
                if contact.open:
                    loss *= content.OPEN_CONTACT_MULT
                    break
            zone.temp += (self.outside_temp - zone.temp) * loss
            if self.is_daytime():
                blinds_open = any(b.open for b in zone.by_type("blind"))
                if blinds_open:
                    zone.temp += 0.15
            zone.temp += zone.occupants() * content.OCCUPANT_HEAT_C
            hvac = next(iter(zone.by_type("hvac")), None)
            if hvac is not None:
                if hvac.cooldown_ticks > 0:
                    hvac.cooldown_ticks -= 1
                    duty = None
                else:
                    duty = self._hvac_duty(hvac, zone.temp)
                if duty == "heat":
                    delta = min(content.HVAC_MAX_DELTA_C,
                                max(0.0, hvac.target + content.HYSTERESIS_C
                                    - zone.temp))
                    zone.temp += delta
                elif duty == "cool":
                    delta = min(content.HVAC_MAX_DELTA_C,
                                max(0.0, zone.temp - (hvac.target
                                    - content.HYSTERESIS_C)))
                    zone.temp -= delta
                if duty is not None and duty == hvac.prev_duty:
                    hvac.duty_ticks += 1
                else:
                    hvac.duty_ticks = 1 if duty is not None else 0
                hvac.prev_duty = duty
                hvac.duty = duty
        names = list(self.zones)
        for name in names:
            zone = self.zones[name]
            for other in zone.adjacent:
                if other not in self.zones:
                    continue
                diff = self.zones[other].temp - zone.temp
                flow = diff * content.INTERZONE_DIFFUSION
                zone.temp += flow
                self.zones[other].temp -= flow
        for name in names:
            z = self.zones[name]
            for occ in z.by_type("occupancy"):
                if occ.people > 0:
                    occ.idle_ticks += 1
                    if occ.idle_ticks >= content.VACANCY_TIMEOUT_TICKS \
                            and occ.people > 0:
                        occ.people = 0
                        occ.idle_ticks = 0
                        fired_events.append(
                            {"event": "vacancy", "zone": name})

    def _hvac_duty(self, hvac, temp):
        if hvac.mode == "off":
            return None
        if hvac.mode == "fan":
            return None
        if hvac.mode == "heat":
            return "heat" if temp < hvac.target else None
        if hvac.mode == "cool":
            return "cool" if temp > hvac.target else None
        if temp <= hvac.target - content.HYSTERESIS_C:
            return "heat"
        if temp >= hvac.target + content.HYSTERESIS_C:
            return "cool"
        return None

    def building_power_w(self):
        return sum(d.watts() for d in self.devices.values())

    # ---------- main tick ----------

    def tick(self, rule_engine=None):
        self.tick_count += 1
        fired = list(self.pending_events)
        self.pending_events = []
        self.advance_clock()
        self._step_thermal(fired)
        for contact in self.devices.values():
            if contact.type != "contact":
                continue
            was = getattr(contact, "_last_open", False)
            if contact.open and not was:
                fired.append({"event": "contact_open",
                              "device": contact.id, "zone": contact.zone})
            contact._last_open = contact.open
        power_w = self.building_power_w()
        if power_w > content.POWER_LIMIT_W:
            fired.append({"event": "power_limit_exceeded",
                          "watts": power_w})
        for smoke in self.devices.values():
            if smoke.type == "smoke" and smoke.alarm:
                fired.append({"event": "smoke", "zone": smoke.zone})
        self.kwh_total += power_w * (content.TICK_MINUTES_SIM / 60.0) / 1000.0
        self.stats.append({"t": now_str(self.clock), "w": power_w})
        if rule_engine is not None:
            rule_engine.on_tick(self, fired)
        return {"tick": self.tick_count, "power_w": power_w,
                "events": len(fired)}

    # ---------- persistence ----------

    def save(self, path, extra=None):
        payload = {
            "version": content.SAVE_VERSION,
            "saved_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "clock": list(self.clock),
            "mode": self.mode,
            "outside_temp": self.outside_temp,
            "tick_count": self.tick_count,
            "kwh_total": round(self.kwh_total, 4),
            "zones": {},
            "devices": {},
        }
        for name, z in self.zones.items():
            payload["zones"][name] = {"temp": round(z.temp, 3)}
        for dev_id, d in self.devices.items():
            state = {"type": d.type}
            for key in ("on", "brightness", "locked", "open", "people",
                        "alarm", "mode", "target"):
                if hasattr(d, key):
                    state[key] = getattr(d, key)
            payload["devices"][dev_id] = state
        if extra:
            for key, val in extra.items():
                if key in payload:
                    raise ValueError(f"save key collision: {key}")
                payload[key] = val
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        self._rotate_backups(path)
        self.log("save", f"state saved -> {os.path.basename(path)}")
        return payload

    def _backup_paths(self, path):
        n = int(content.WARDEN["backup_copies"])
        return [f"{path}.bak{i + 1}" for i in range(n)]

    def _rotate_backups(self, path):
        baks = self._backup_paths(path)
        for i in range(len(baks) - 1, 0, -1):
            if os.path.exists(baks[i - 1]):
                shutil.copyfile(baks[i - 1], baks[i])
        if os.path.exists(path):
            shutil.copyfile(path, baks[0])

    def load(self, path):
        data = None
        tried = []
        for candidate in [path] + self._backup_paths(path):
            if not os.path.exists(candidate):
                continue
            try:
                with open(candidate, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if candidate != path:
                    self.alert("warn",
                               f"save file damaged; state recovered "
                               f"from backup {os.path.basename(candidate)}")
                    self.log("load", f"fallback -> "
                                     f"{os.path.basename(candidate)}")
                break
            except (OSError, ValueError) as exc:
                tried.append(f"{os.path.basename(candidate)}: {exc}")
        if data is None:
            raise OSError(f"no readable save: {'; '.join(tried)}")
        version = data.get("version", 1)
        if version > content.SAVE_VERSION:
            raise ValueError(f"save version {version} newer than "
                             f"{content.SAVE_VERSION}")
        from schema import audit_save
        issues = audit_save(data)
        for issue in issues:
            if issue.startswith("error:"):
                self.alert("warn",
                           f"save audit: {issue[len('error:'):].strip()}")
            else:
                self.log("load", f"save audit {issue}")
        self.clock = list(data.get("clock", self.clock))
        while len(self.clock) < 5:
            self.clock.append(0)
        self.mode = data.get("mode", self.mode)
        self.outside_temp = data.get("outside_temp", self.outside_temp)
        self.tick_count = data.get("tick_count", 0)
        self.kwh_total = data.get("kwh_total", 0.0)
        for name, zs in data.get("zones", {}).items():
            if name in self.zones:
                self.zones[name].temp = float(zs.get("temp",
                                                     self.zones[name].temp))
        for dev_id, ds in data.get("devices", {}).items():
            dev = self.devices.get(dev_id)
            if dev is None:
                continue
            for key, val in ds.items():
                if key == "type":
                    continue
                if hasattr(dev, key):
                    setattr(dev, key, val)
            if dev.type == "contact":
                dev._last_open = dev.open
        self.log("load", f"state loaded v{version} <- "
                         f"{os.path.basename(path)}")
        return data

    # ---------- reporting ----------

    def snapshot(self):
        return {
            "building": {
                "mode": self.mode,
                "tick": self.tick_count,
                "clock": now_str(self.clock),
                "outside_c": self.outside_temp,
                "power_w": self.building_power_w(),
                "kwh_total": round(self.kwh_total, 3),
                "zones": len(self.zones),
                "devices": len(self.devices),
                "critical_alerts": sum(1 for a in self.alerts
                                       if a["level"] == "critical"),
            },
            "zones": {n: z.snapshot() for n, z in self.zones.items()},
        }

    def _zone(self, name):
        zone = self.zones.get(name)
        if zone is None:
            raise KeyError(f"unknown zone: {name}")
        return zone
