"""Vulcan device mechanics: state machines for sensors and actuators.

Devices are dumb state + watts accounting; all numbers come from
content.py. The world owns physics and time; rules own decisions.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import content
from collections import deque


class Device:
    def __init__(self, dev_id, dtype, zone):
        spec = content.DEVICE_TYPES[dtype]
        self.id = dev_id
        self.type = dtype
        self.zone = zone
        self.actuator = spec["actuator"]
        if dtype == "hvac":
            self.mode = "off"
            self.target = content.COMFORT_TARGET_C
            self.duty = None
            self.prev_duty = None
            self.duty_ticks = 0
            self.cooldown_ticks = 0
        elif dtype == "light":
            self.on = False
            self.brightness = 100
        elif dtype == "plug":
            self.on = False
        elif dtype == "lock":
            self.locked = True
        elif dtype == "blind":
            self.open = True
        elif dtype == "fan":
            self.on = False
        elif dtype == "occupancy":
            self.people = 0
            self.idle_ticks = 0
        elif dtype == "contact":
            self.open = False
        elif dtype == "smoke":
            self.alarm = False

    @staticmethod
    def _as_bool(key, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise ValueError(f"{key} must be boolean")

    def apply(self, changes):
        """Actuator intent from SDK/rules; applies only real changes and
        returns the keys actually mutated (no-op writes are ignored)."""
        applied = []
        if self.type == "hvac":
            if "mode" in changes:
                if changes["mode"] not in ("off", "heat", "cool", "auto",
                                           "fan"):
                    raise ValueError("hvac mode must be off/heat/cool/"
                                     "auto/fan")
                if self.mode != changes["mode"]:
                    self.mode = changes["mode"]
                    applied.append("mode")
            if "target" in changes:
                t = round(float(changes["target"]), 1)
                if not 5.0 <= t <= 35.0:
                    raise ValueError("hvac target must be 5-35 C")
                if self.target != t:
                    self.target = t
                    applied.append("target")
        elif self.type in ("light", "plug", "fan"):
            if "on" in changes:
                want = self._as_bool("on", changes["on"])
                if self.on != want:
                    self.on = want
                    applied.append("on")
            if self.type == "light" and "brightness" in changes:
                lo, hi = (0, content.DEVICE_TYPES["light"]["max_brightness"])
                want = max(lo, min(hi, int(changes["brightness"])))
                if self.brightness != want:
                    self.brightness = want
                    if want == 0 and self.on:
                        self.on = False
                        applied.append("on")
                    applied.append("brightness")
        elif self.type == "lock":
            if "locked" in changes:
                want = self._as_bool("locked", changes["locked"])
                if self.locked != want:
                    self.locked = want
                    applied.append("locked")
        elif self.type == "blind":
            if "open" in changes:
                want = self._as_bool("open", changes["open"])
                if self.open != want:
                    self.open = want
                    applied.append("open")
        else:
            raise ValueError(f"{self.type} is not actuator-controllable")
        return applied

    def watts(self):
        spec = content.DEVICE_TYPES[self.type]
        if self.type == "hvac":
            base = spec.get("watts_idle", 0)
            if self.duty == "heat":
                return spec["watts_heat"]
            if self.duty == "cool":
                return spec["watts_cool"]
            return base if self.mode != "off" else 0
        if self.type == "light":
            if not self.on:
                return 0
            frac = 0.25 + 0.75 * (self.brightness /
                                  content.DEVICE_TYPES["light"]
                                  ["max_brightness"])
            return int(round(spec["watts"] * frac))
        if not self.actuator:
            return spec.get("watts", 0)
        return spec["watts"] if getattr(self, "on", False) else 0

    def snapshot(self):
        d = {"id": self.id, "type": self.type, "zone": self.zone,
             "watts": self.watts()}
        for key in ("on", "brightness", "locked", "open", "people",
                    "occupied", "alarm", "mode", "target", "duty"):
            if hasattr(self, key):
                d[key] = getattr(self, key)
        if self.type == "occupancy":
            d["occupied"] = self.people > 0
        return d


class Zone:
    def __init__(self, name, floor, area_m2, adjacent, seed_temp=None):
        self.name = name
        self.floor = floor
        self.area_m2 = area_m2
        self.adjacent = list(adjacent)
        self.temp = seed_temp if seed_temp is not None \
            else content.OUTSIDE_TEMP_C + 4.0
        self.devices = {}
        self.history = deque(maxlen=16)

    def by_type(self, dtype):
        return [d for d in self.devices.values() if d.type == dtype]

    def occupants(self):
        n = 0
        for occ in self.by_type("occupancy"):
            n += occ.people
        return n

    def snapshot(self):
        return {"name": self.name, "floor": self.floor,
                "area_m2": self.area_m2, "adjacent": list(self.adjacent),
                "temp": round(self.temp, 2), "occupants": self.occupants(),
                "devices": sorted(d.id for d in self.devices.values()),
                "power_w": sum(d.watts() for d in self.devices.values())}
