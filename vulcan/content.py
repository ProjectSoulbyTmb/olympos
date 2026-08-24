"""Vulcan data tables - the single source of truth.

Every number, device spec, zone layout, threshold, scene and default
automation recipe lives here. Mechanics modules read from this module
and never re-declare a table (mirrors game/content.py contract).
"""

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 43901
MAX_LINE_BYTES = 65536
MAX_SESSIONS = 16

TICK_SECONDS_REAL = 2.0
TICK_MINUTES_SIM = 5
SAVE_VERSION = 1
MAX_EVENTS = 500
MAX_ALERTS = 100
MAX_STATS = 720

START_CLOCK = (2026, 8, 23, 6, 0)

OUTSIDE_TEMP_C = 8.0
ENVELOPE_LOSS_PER_TICK = 0.05
OPEN_CONTACT_MULT = 3.5
INTERZONE_DIFFUSION = 0.04
OCCUPANT_HEAT_C = 0.03
HVAC_MAX_DELTA_C = 0.9

DEVICE_TYPES = {
    "temp_sensor": {"actuator": False, "watts": 0},
    "occupancy":   {"actuator": False, "watts": 1},
    "contact":     {"actuator": False, "watts": 0},
    "smoke":       {"actuator": False, "watts": 2},
    "hvac":        {"actuator": True, "watts_idle": 45,
                    "watts_heat": 3200, "watts_cool": 2800},
    "light":       {"actuator": True, "watts": 36, "max_brightness": 100},
    "plug":        {"actuator": True, "watts": 220},
    "lock":        {"actuator": True, "watts": 1},
    "blind":       {"actuator": True, "watts": 4},
    "fan":         {"actuator": True, "watts": 55},
}

SEED_ZONES = [
    {"name": "lobby", "floor": 0, "area_m2": 42, "adjacent": ["hallway"],
     "devices": [
         {"id": "light_lobby", "type": "light"},
         {"id": "temp_lobby", "type": "temp_sensor"},
         {"id": "occ_lobby", "type": "occupancy"},
         {"id": "door_front", "type": "contact"},
         {"id": "lock_front", "type": "lock"},
         {"id": "hvac_lobby", "type": "hvac"},
     ]},
    {"name": "hallway", "floor": 0, "area_m2": 25, "adjacent": ["lobby"],
     "devices": [
         {"id": "light_hallway", "type": "light"},
         {"id": "temp_hallway", "type": "temp_sensor"},
         {"id": "occ_hallway", "type": "occupancy"},
         {"id": "hvac_hallway", "type": "hvac"},
     ]},
    {"name": "utility", "floor": 0, "area_m2": 18, "adjacent": ["hallway"],
     "devices": [
         {"id": "light_utility", "type": "light"},
         {"id": "temp_utility", "type": "temp_sensor"},
         {"id": "hvac_utility", "type": "hvac"},
         {"id": "smoke_utility", "type": "smoke"},
         {"id": "rack_fan", "type": "fan"},
     ]},
    {"name": "garage", "floor": 0, "area_m2": 35, "adjacent": [],
     "devices": [
         {"id": "light_garage", "type": "light"},
         {"id": "temp_garage", "type": "temp_sensor"},
         {"id": "door_garage", "type": "contact"},
         {"id": "hvac_garage", "type": "hvac"},
         {"id": "plug_ev", "type": "plug"},
     ]},
    {"name": "office_a", "floor": 1, "area_m2": 30, "adjacent": ["hallway"],
     "devices": [
         {"id": "light_office_a", "type": "light"},
         {"id": "temp_office_a", "type": "temp_sensor"},
         {"id": "occ_office_a", "type": "occupancy"},
         {"id": "window_a", "type": "blind"},
         {"id": "hvac_office_a", "type": "hvac"},
         {"id": "plug_desk_a", "type": "plug"},
     ]},
    {"name": "office_b", "floor": 1, "area_m2": 30, "adjacent": ["hallway"],
     "devices": [
         {"id": "light_office_b", "type": "light"},
         {"id": "temp_office_b", "type": "temp_sensor"},
         {"id": "occ_office_b", "type": "occupancy"},
         {"id": "window_b", "type": "blind"},
         {"id": "hvac_office_b", "type": "hvac"},
         {"id": "plug_desk_b", "type": "plug"},
     ]},
    {"name": "meeting", "floor": 1, "area_m2": 28, "adjacent": ["hallway"],
     "devices": [
         {"id": "light_meeting", "type": "light"},
         {"id": "temp_meeting", "type": "temp_sensor"},
         {"id": "occ_meeting", "type": "occupancy"},
         {"id": "window_meeting", "type": "blind"},
         {"id": "hvac_meeting", "type": "hvac"},
     ]},
]

MODES = ["home", "away", "night", "vacation"]

WARDEN = {
    "enabled": True,
    "stuck_sensor_ticks": 12,
    "sensor_lo_c": -20.0,
    "sensor_hi_c": 60.0,
    "runaway_hvac_ticks": 30,
    "hvac_cooldown_ticks": 8,
    "vacant_light_ticks": 6,
    "rule_fail_limit": 3,
    "rule_revive_ticks": 60,
    "escalate_shed_types": ["fan"],
    "backup_copies": 3,
    "max_repairs_log": 100,
}

COMFORT_TARGET_C = 21.0
HYSTERESIS_C = 0.5
FREEZE_ALARM_C = 5.0
OVERHEAT_ALARM_C = 30.0
SERVER_ROOM_ZONE = "utility"
SERVER_ROOM_MAX_C = 26.0
VACANCY_TIMEOUT_TICKS = 4
POWER_LIMIT_W = 9000
LOAD_SHED_ORDER = ["plug_ev", "plug_desk_a", "plug_desk_b"]
NIGHT_SCENE_AT = "22:00"
MORNING_SCENE_AT = "07:00"

SCENES = {
    "day": {
        "lights": {"on": True, "brightness": 90},
        "blinds": True,
        "locks": False,
        "hvac": {"mode": "auto", "target": COMFORT_TARGET_C},
        "plugs": None,
        "fans": None,
    },
    "night": {
        "lights": {"on": True, "brightness": 15, "only": ["light_hallway"]},
        "blinds": False,
        "locks": True,
        "hvac": {"mode": "auto", "target": COMFORT_TARGET_C - 3.0},
        "plugs": False,
        "fans": False,
    },
    "away": {
        "lights": {"on": False},
        "blinds": False,
        "locks": True,
        "hvac": {"mode": "auto", "target": COMFORT_TARGET_C - 4.0},
        "plugs": False,
        "fans": False,
    },
    "vacation": {
        "lights": {"on": False},
        "blinds": False,
        "locks": True,
        "hvac": {"mode": "heat", "target": FREEZE_ALARM_C + 3.0},
        "plugs": False,
        "fans": False,
    },
}

DEFAULT_RULES = [
    {"id": "occ_light_lobby", "name": "Lobby occupancy lighting",
     "trigger": {"type": "tick"}, "cooldown_ticks": VACANCY_TIMEOUT_TICKS,
     "when": {"kind": "any", "any": [
         {"kind": "device", "device": "occ_lobby", "attr": "occupied",
          "op": "==", "value": True},
         {"kind": "mode", "op": "==", "value": "home"}]},
     "then": [{"kind": "device", "device": "light_lobby",
               "set": {"on": True, "brightness": 80}}],
     "else": [{"kind": "device", "device": "light_lobby",
               "set": {"on": False}}]},
    {"id": "occ_light_office_a", "name": "Office A occupancy lighting",
     "trigger": {"type": "tick"}, "cooldown_ticks": VACANCY_TIMEOUT_TICKS,
     "when": {"kind": "device", "device": "occ_office_a",
              "attr": "occupied", "op": "==", "value": True},
     "then": [{"kind": "device", "device": "light_office_a",
               "set": {"on": True, "brightness": 85}}],
     "else": [{"kind": "device", "device": "light_office_a",
               "set": {"on": False}}]},
    {"id": "occ_light_office_b", "name": "Office B occupancy lighting",
     "trigger": {"type": "tick"}, "cooldown_ticks": VACANCY_TIMEOUT_TICKS,
     "when": {"kind": "device", "device": "occ_office_b",
              "attr": "occupied", "op": "==", "value": True},
     "then": [{"kind": "device", "device": "light_office_b",
               "set": {"on": True, "brightness": 85}}],
     "else": [{"kind": "device", "device": "light_office_b",
               "set": {"on": False}}]},
    {"id": "occ_light_meeting", "name": "Meeting room occupancy lighting",
     "trigger": {"type": "tick"}, "cooldown_ticks": VACANCY_TIMEOUT_TICKS,
     "when": {"kind": "device", "device": "occ_meeting",
              "attr": "occupied", "op": "==", "value": True},
     "then": [{"kind": "device", "device": "light_meeting",
               "set": {"on": True, "brightness": 95}}],
     "else": [{"kind": "device", "device": "light_meeting",
               "set": {"on": False}}]},
    {"id": "sched_night", "name": "Night setback scene",
     "trigger": {"type": "schedule", "time": NIGHT_SCENE_AT},
     "then": [{"kind": "scene", "name": "night"}]},
    {"id": "sched_morning", "name": "Morning scene",
     "trigger": {"type": "schedule", "time": MORNING_SCENE_AT},
     "then": [{"kind": "scene", "name": "day"}]},
    {"id": "sec_away_open", "name": "Security: opening while away",
     "trigger": {"type": "event", "event": "contact_open"},
     "when": {"kind": "mode", "op": "==", "value": "away"},
     "then": [
         {"kind": "lock_all"},
         {"kind": "alert", "level": "critical",
          "message": "Contact opened while building is AWAY: {device}"}]},
    {"id": "smoke_response", "name": "Smoke alarm response",
     "trigger": {"type": "event", "event": "smoke"},
     "then": [
         {"kind": "unlock_all"},
         {"kind": "lights_all", "set": {"on": True, "brightness": 100}},
         {"kind": "hvac_all_off"},
         {"kind": "alert", "level": "critical",
          "message": "SMOKE detected in {zone} - exits unlocked, "
                     "HVAC stopped"}]},
    {"id": "freeze_guard", "name": "Freeze guard",
     "trigger": {"type": "tick"}, "alert_cooldown_ticks": 12,
     "when": {"kind": "zone", "zone": "{coldest}", "attr": "temp",
              "op": "<=", "value": FREEZE_ALARM_C},
     "then": [
         {"kind": "alert", "level": "critical",
          "message": "Freeze risk in {coldest}: {temp:.1f} C"},
         {"kind": "hvac", "zone": "{coldest}",
          "set": {"mode": "heat", "target": COMFORT_TARGET_C}}]},
    {"id": "server_room_watch", "name": "Server room overheat watch",
     "trigger": {"type": "tick"}, "alert_cooldown_ticks": 12,
     "when": {"kind": "zone", "zone": SERVER_ROOM_ZONE, "attr": "temp",
              "op": ">=", "value": SERVER_ROOM_MAX_C},
     "then": [
         {"kind": "alert", "level": "warn",
          "message": "Utility room hot: {temp:.1f} C"},
         {"kind": "device", "device": "rack_fan", "set": {"on": True}},
         {"kind": "hvac", "zone": SERVER_ROOM_ZONE,
          "set": {"mode": "cool", "target": SERVER_ROOM_MAX_C - 3.0}}]},
    {"id": "load_shed", "name": "Power limit load shedding",
     "trigger": {"type": "event", "event": "power_limit_exceeded"},
     "alert_cooldown_ticks": 6,
     "then": [{"kind": "shed"}]},
    {"id": "meeting_prep_sequence", "name": "Meeting room prep sequence",
     "trigger": {"type": "event", "event": "motion"},
     "when": {"kind": "zone", "zone": "{zone}", "attr": "occupants",
              "op": ">=", "value": 3},
     "then": [
         {"kind": "device_group", "type": "blind", "zone": "meeting",
          "set": {"open": True}},
         {"kind": "sequence", "gap_ticks": 2, "steps": [
             [{"kind": "device", "device": "light_meeting",
               "set": {"on": True, "brightness": 100}}],
             [{"kind": "hvac", "zone": "meeting",
               "set": {"mode": "cool", "target": 20.0}}]]}]},
    {"id": "evening_precool", "name": "Evening pre-cool on heat buildup",
     "priority": 5,
     "trigger": {"type": "tick"},
     "when": {"kind": "zone_count", "attr": "temp", "op": ">=",
              "value": 26.0, "count": 3},
     "alert_cooldown_ticks": 12,
     "then": [
         {"kind": "alert", "level": "info",
          "message": "{hot_count} zones above 26 C - pre-cooling"},
         {"kind": "device_group", "type": "blind",
          "set": {"open": False}},
         {"kind": "device_group", "type": "fan", "set": {"on": True}}]},
]
