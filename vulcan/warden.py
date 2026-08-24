"""Vulcan warden: self-diagnostics and automatic repair.

The warden patrols the building every tick (after rules run) looking
for waste, runaway equipment, dead sensors and unsafe leftovers - and
fixes what it can fix on its own, logging every intervention as a
repair. Tuning lives in content.WARDEN; nothing here hardcodes
numbers. Escalating problems it cannot fully repair are raised as
alerts so operators (or rules) can react.
"""

from collections import deque
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import content


class Warden:
    def __init__(self):
        cfg = content.WARDEN
        self.enabled = bool(cfg["enabled"])
        self.repairs = deque(maxlen=int(cfg["max_repairs_log"]))
        self.repair_count = 0

    # ---------- public surface ----------

    def patrol(self, world):
        findings = []
        findings += self._sensor_bounds(world)
        findings += self._stuck_sensors(world)
        findings += self._runaway_hvac(world)
        findings += self._waste_hvac_open_contact(world)
        findings += self._vacant_lights(world)
        findings += self._escalate_shed(world)
        return findings

    def diagnose(self, world, sdk=None):
        report = {
            "warden": "on" if self.enabled else "off",
            "repairs_total": self.repair_count,
            "findings": [],
        }
        if not self.enabled:
            return report
        before = len(self.repairs)
        report["findings"] = self.patrol(world)
        report["fixed_now"] = len(self.repairs) - before
        report["power_w"] = world.building_power_w()
        report["over_limit"] = \
            world.building_power_w() > content.POWER_LIMIT_W
        return report

    def record(self, world, category, text):
        self.repair_count += 1
        entry = {"n": self.repair_count, "t": world.tick_stamp(),
                 "category": category, "text": text}
        self.repairs.append(entry)
        world.log("heal", f"[{category}] {text}")
        return entry

    # ---------- patrols ----------

    def _sensor_bounds(self, world):
        out = []
        lo = content.WARDEN["sensor_lo_c"]
        hi = content.WARDEN["sensor_hi_c"]
        for zone in world.zones.values():
            if zone.temp < lo or zone.temp > hi:
                bad = zone.temp
                zone.temp = max(lo, min(hi, zone.temp))
                entry = self.record(world, "sensor",
                                    f"{zone.name}: impossible reading "
                                    f"{bad:.1f} C clamped to "
                                    f"{zone.temp:.1f} C")
                out.append(entry)
        return out

    def _stuck_sensors(self, world):
        out = []
        need = int(content.WARDEN["stuck_sensor_ticks"])
        for zone in world.zones.values():
            hvac = next(iter(zone.by_type("hvac")), None)
            active = zone.occupants() > 0 or \
                (hvac is not None and hvac.duty is not None)
            hist = list(zone.history)[-need:]
            if len(hist) < need or not active:
                continue
            if max(hist) - min(hist) > 0.001:
                continue
            neighbors = [self._safe_temp(world, n)
                         for n in zone.adjacent]
            neighbors = [t for t in neighbors if t is not None]
            estimate = sum(neighbors) / len(neighbors) if neighbors \
                else round((world.outside_temp + zone.temp) / 2, 2)
            old = zone.temp
            zone.temp = estimate
            zone.history.clear()
            entry = self.record(
                world, "sensor",
                f"{zone.name}: reading frozen at {old:.1f} C for "
                f"{need} ticks while active - substituted estimate "
                f"{estimate:.1f} C")
            out.append(entry)
        return out

    @staticmethod
    def _safe_temp(world, name):
        z = world.zones.get(name)
        return round(z.temp, 2) if z is not None else None

    def _runaway_hvac(self, world):
        out = []
        limit = int(content.WARDEN["runaway_hvac_ticks"])
        rest = int(content.WARDEN["hvac_cooldown_ticks"])
        for dev in world.devices.values():
            if dev.type != "hvac":
                continue
            if dev.duty is None or dev.duty_ticks < limit:
                continue
            zone = dev.zone
            held = dev.duty
            dev.duty = None
            dev.cooldown_ticks = rest
            dev.duty_ticks = 0
            entry = self.record(
                world, "hvac",
                f"hvac_{zone}: {held} duty held {limit}+ ticks "
                f"without reaching {dev.target:.0f} C - forced "
                f"{rest}-tick cooldown")
            out.append(entry)
        return out

    def _waste_hvac_open_contact(self, world):
        out = []
        for zone in world.zones.values():
            contact = next(iter(zone.by_type("contact")), None)
            if contact is None or not contact.open:
                continue
            for hvac in zone.by_type("hvac"):
                if hvac.mode == "off":
                    continue
                hvac.apply({"mode": "off"})
                hvac.duty = None
                hvac.prev_duty = None
                hvac.duty_ticks = 0
                entry = self.record(
                    world, "waste",
                    f"{zone.name}: HVAC stopped - window/door open "
                    f"({contact.id})")
                out.append(entry)
        return out

    def _vacant_lights(self, world):
        out = []
        need = int(content.WARDEN["vacant_light_ticks"])
        enforce_modes = {"away", "vacation"}
        if world.mode not in enforce_modes:
            return out
        for zone in world.zones.values():
            if zone.occupants() > 0:
                continue
            for light in zone.by_type("light"):
                if not light.on:
                    light._vacant_ticks = 0
                    continue
                light._vacant_ticks = getattr(light, "_vacant_ticks", 0) + 1
                if light._vacant_ticks < need:
                    continue
                light.apply({"on": False})
                light._vacant_ticks = 0
                entry = self.record(
                    world, "energy",
                    f"{light.id}: left on in vacant {zone.name} during "
                    f"{world.mode} mode - switched off")
                out.append(entry)
        return out

    def _escalate_shed(self, world):
        out = []
        if world.building_power_w() <= content.POWER_LIMIT_W:
            return out
        plugs_left = any(getattr(world.devices.get(d), "on", False)
                         for d in content.LOAD_SHED_ORDER)
        if plugs_left:
            return out
        for dtype in content.WARDEN["escalate_shed_types"]:
            if world.building_power_w() <= content.POWER_LIMIT_W:
                break
            for dev in world.devices.values():
                if dev.type == dtype and getattr(dev, "on", False):
                    dev.apply({"on": False})
                    entry = self.record(
                        world, "shed",
                        f"escalated shedding: {dev.id} ({dtype}) off")
                    out.append(entry)
        if world.building_power_w() > content.POWER_LIMIT_W:
            last = getattr(self, "_last_escalation_alert", -10 ** 9)
            if world.tick_count - last >= 12:
                self._last_escalation_alert = world.tick_count
                world.alert("critical",
                            "power over limit with no sheddable load "
                            "left - manual intervention needed")
        return out
