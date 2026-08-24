"""Vulcan verify suite - gates every behavioral change.

Run: python vulcan/verify_vulcan.py   (exit 0 = all checks pass)
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from rules import RuleEngine          # noqa: E402
from sdk import VulcanClient, VulcanSDK, wire_client  # noqa: E402
from server import BuildingServer     # noqa: E402
from world import World               # noqa: E402

import content                        # noqa: E402


def fresh():
    world = World()
    engine = RuleEngine(world)
    return world, engine, VulcanSDK(world, engine)


def at(world, hour, minute=55):
    world.clock[3], world.clock[4] = hour, minute


def check_content_integrity():
    ids = [d["id"] for z in content.SEED_ZONES for d in z["devices"]]
    if len(ids) != len(set(ids)):
        return "duplicate device ids"
    for z in content.SEED_ZONES:
        for d in z["devices"]:
            if d["type"] not in content.DEVICE_TYPES:
                return f"unknown type {d['type']}"
        for adj in z["adjacent"]:
            names = {x["name"] for x in content.SEED_ZONES}
            if adj not in names:
                return f"dangling adjacency {z['name']}->{adj}"
    for scene in content.SCENES.values():
        only = (scene.get("lights") or {}).get("only", [])
        for dev_id in only:
            if dev_id not in ids:
                return f"scene references unknown device {dev_id}"
    for dev_id in content.LOAD_SHED_ORDER:
        if dev_id not in ids:
            return f"shed order references unknown device {dev_id}"
    return True


def check_seed_building():
    world, engine, sdk = fresh()
    snap = sdk.state()
    b = snap["building"]
    if b["zones"] != len(content.SEED_ZONES):
        return "zone count mismatch"
    if b["devices"] != sum(len(z["devices"])
                           for z in content.SEED_ZONES):
        return "device count mismatch"
    if b["mode"] != "home":
        return "initial mode should be home"
    return True


def check_clock_advance():
    world, engine, _ = fresh()
    before = world.clock_minutes()
    world.tick(engine)
    if world.clock_minutes() != (before + content.TICK_MINUTES_SIM) % 1440:
        return "clock did not advance one tick"
    if world.tick_count != 1:
        return "tick counter wrong"
    return True


def check_thermal_drift():
    world, engine, _ = fresh()
    world.set_outside_temp(-10.0)
    world.zones["garage"].temp = 20.0
    start = world.zones["garage"].temp
    for _ in range(10):
        world.tick(engine)
    if not world.zones["garage"].temp < start - 1.0:
        return "zone did not drift toward cold outside temp"
    return True


def check_hvac_heat_and_hysteresis():
    world, engine, sdk = fresh()
    sdk.set_hvac("office_a", mode="auto", target=22.0)
    world.zones["office_a"].temp = 15.0
    hvac = world.devices["hvac_office_a"]
    heated = False
    for _ in range(30):
        world.tick(engine)
        if hvac.duty == "heat":
            heated = True
    if not heated:
        return "hvac never heated"
    if world.zones["office_a"].temp < 21.5 - content.HYSTERESIS_C:
        return "temperature did not approach target"
    idle_inside_band = world._hvac_duty(hvac, hvac.target) is None
    if not idle_inside_band:
        return "thermostat chatters inside deadband"
    return True


def check_light_watts():
    world, _, sdk = fresh()
    light = world.devices["light_lobby"]
    base = content.DEVICE_TYPES["light"]["watts"]
    sdk.set_device("light_lobby", on=True, brightness=100)
    if light.watts() != base:
        return "full-brightness watts wrong"
    sdk.set_device("light_lobby", brightness=50)
    if light.watts() >= base:
        return "dimming did not reduce watts"
    sdk.set_device("light_lobby", on=False)
    if light.watts() != 0 or light.brightness != 50:
        return "off light must draw zero watts and keep level"
    sdk.set_device("light_lobby", brightness=999)
    if light.brightness != content.DEVICE_TYPES["light"]["max_brightness"]:
        return "brightness not clamped to maximum"
    try:
        sdk.set_device("light_lobby", on="banana")
        return "non-boolean on accepted"
    except ValueError:
        pass
    return True


def check_occupancy_decay():
    world, engine, sdk = fresh()
    sdk.motion("office_a", people=2)
    occ = world.devices["occ_office_a"]
    for _ in range(content.VACANCY_TIMEOUT_TICKS):
        sdk.motion("office_a")
    for _ in range(content.VACANCY_TIMEOUT_TICKS + 1):
        world.tick(engine)
    if occ.people != 0 or occ.snapshot()["occupied"]:
        return "occupancy did not decay after vacancy timeout"
    sdk.motion("office_a")
    if occ.people != 1 or occ.idle_ticks != 0:
        return "motion did not refresh occupancy"
    return True


def check_occupancy_lighting_rule():
    world, engine, sdk = fresh()
    sdk.mode("night")
    world.set_mode("home")
    sdk.motion("office_b")
    world.tick(engine)
    if not world.devices["light_office_b"].on:
        return "occupancy rule did not switch light on"
    for _ in range(content.VACANCY_TIMEOUT_TICKS + 1):
        world.tick(engine)
    if world.devices["light_office_b"].on:
        return "light stayed on after vacancy timeout"
    return True


def check_night_schedule():
    world, engine, _ = fresh()
    at(world, 21)
    engine._last_minute = world.clock_minutes()
    world.set_mode("home")
    for _ in range(2):
        world.tick(engine)
    if not world.devices["lock_front"].locked:
        return "night scene did not lock doors"
    if world.zones["office_a"].by_type("blind")[0].open:
        return "night scene did not close blinds"
    return True


def check_security_away_opening():
    world, engine, sdk = fresh()
    sdk.mode("away")
    world.devices["lock_front"].locked = False
    sdk.contact("door_front", True)
    world.tick(engine)
    crits = [a for a in world.alerts if a["level"] == "critical"]
    if not crits:
        return "no critical alert for opening while away"
    if not world.devices["lock_front"].locked:
        return "security rule did not re-lock door"
    return True


def check_freeze_guard():
    world, engine, sdk = fresh()
    sdk.set_device("hvac_garage", mode="off")
    world.zones["garage"].temp = 3.0
    world.tick(engine)
    hvac = world.devices["hvac_garage"]
    if hvac.mode != "heat" or hvac.target < content.FREEZE_ALARM_C:
        return "freeze guard did not force heating"
    alerts = [a for a in world.alerts if "Freeze risk" in a["text"]]
    if not alerts:
        return "freeze alert missing"
    return True


def check_server_room_watch():
    world, engine, _ = fresh()
    world.zones["utility"].temp = 30.0
    world.tick(engine)
    if not world.devices["rack_fan"].on:
        return "overheat watch did not start rack fan"
    if world.devices["hvac_utility"].mode != "cool":
        return "overheat watch did not cool utility room"
    return True


def check_smoke_response():
    world, engine, sdk = fresh()
    world.set_mode("night")
    sdk.smoke("smoke_utility", True)
    world.tick(engine)
    if world.devices["lock_front"].locked:
        return "smoke did not unlock exits"
    lights = [d for d in world.devices.values() if d.type == "light"]
    if not all(d.on and d.brightness == 100 for d in lights):
        return "smoke did not flash all lights full"
    hvacs = [d for d in world.devices.values() if d.type == "hvac"]
    if not all(d.mode == "off" for d in hvacs):
        return "smoke did not stop HVAC"
    crits = [a for a in world.alerts if a["level"] == "critical"]
    if not crits:
        return "no smoke alert"
    return True


def check_load_shedding():
    world, engine, sdk = fresh()
    sdk.set_device("plug_ev", on=True)
    sdk.set_device("plug_desk_a", on=True)
    sdk.set_device("plug_desk_b", on=True)
    for zone in ("lobby", "hallway", "meeting", "office_a"):
        sdk.set_hvac(zone, mode="heat", target=24.0)
        world.zones[zone].temp = 10.0
    world.tick(engine)
    if world.building_power_w() > content.POWER_LIMIT_W and \
            world.devices["plug_ev"].on:
        return "shedder left highest-priority load running over limit"
    shed_alerts = [a for a in world.alerts if "load shed" in a["text"]]
    if not shed_alerts:
        return "no load-shed alert"
    return True


def check_save_load_roundtrip(tmp):
    world, engine, sdk = fresh()
    sdk.mode("away")
    sdk.set_hvac("meeting", mode="cool", target=19.0)
    world.zones["meeting"].temp = 23.4
    sdk.set_device("light_meeting", on=True, brightness=60)
    sdk.toggle_rule("occ_light_office_b", enabled=False)
    sdk.add_rule(spec={"id": "user_test_rule",
                       "name": "user rule",
                       "trigger": {"type": "schedule", "time": "12:00"},
                       "then": [{"kind": "scene", "name": "day"}]})
    path = os.path.join(tmp, "vulcan_save.json")
    sdk.save(path=path)
    world2, engine2, sdk2 = fresh()
    result = sdk2.load(path=path)
    if abs(world2.zones["meeting"].temp - 23.4) > 0.01:
        return "temperature not preserved"
    if world2.mode != "away":
        return "mode not preserved"
    if world2.devices["light_meeting"].brightness != 60:
        return "light state not preserved"
    if world2.devices["hvac_meeting"].target != 19.0:
        return "hvac setpoint not preserved"
    if result.get("rules_restored") != len(content.DEFAULT_RULES) + 1:
        return "automation not fully restored"
    if not any(r["id"] == "user_test_rule" for r in engine2.rules):
        return "user rule lost across save/load"
    if next(r for r in engine2.rules
            if r["id"] == "occ_light_office_b")["enabled"]:
        return "disabled flag not preserved"
    return True


def check_rules_crud():
    _, _, sdk = fresh()
    n0 = len(sdk.rules())
    sdk.add_rule(spec={"id": "crud_rule",
                       "trigger": {"type": "event", "event": "motion"},
                       "when": {"kind": "zone", "zone": "lobby",
                                "attr": "occupants", "op": ">=",
                                "value": 3},
                       "then": [{"kind": "alert", "level": "info",
                                 "message": "busy lobby"}]})
    if len(sdk.rules()) != n0 + 1:
        return "add_rule did not add"
    for bad in (
        {"id": "", "trigger": {"type": "tick"},
         "then": [{"kind": "shed"}]},
        {"id": "occ_light_lobby", "trigger": {"type": "tick"},
         "then": [{"kind": "shed"}]},
        {"id": "no_then", "trigger": {"type": "tick"}, "then": []},
        {"id": "bad_trigger", "trigger": {"type": "solar"},
         "then": [{"kind": "shed"}]},
        {"id": "bad_action", "trigger": {"type": "tick"},
         "then": [{"kind": "launch_missiles"}]},
        {"id": "bad_cond", "trigger": {"type": "tick"},
         "when": {"kind": "astrology", "sign": "mars"},
         "then": [{"kind": "shed"}]},
    ):
        try:
            sdk.add_rule(spec=bad)
            return f"invalid rule accepted: {bad.get('id')!r}"
        except ValueError:
            pass
    sdk.delete_rule(rule_id="crud_rule")
    if len(sdk.rules()) != n0:
        return "delete_rule did not delete"
    try:
        sdk.delete_rule(rule_id="freeze_guard")
        return "deleted a builtin rule"
    except ValueError:
        pass
    state = sdk.toggle_rule(rule_id="freeze_guard")
    if state["enabled"]:
        return "toggle did not disable"
    sdk.toggle_rule(rule_id="freeze_guard")
    return True


def check_sdk_surface_lockstep():
    _, _, sdk = fresh()
    missing = wire_client(sdk)
    if missing:
        return f"sdk surface holes: {missing}"
    return True


def check_wire_roundtrip():
    server = BuildingServer(port=0, auto_tick=False)
    server.start_async()
    try:
        client = VulcanClient(server.host, server.port)
        hello = client.connect()
        if hello.get("error") is not None:
            return f"hello carried error: {hello['error']}"
        state = client.state()
        if state["building"]["zones"] != len(content.SEED_ZONES):
            return "wire state zone count mismatch"
        client.set_device(dev_id="light_lobby", on=True)
        snap = client.device(dev_id="light_lobby")
        if not snap["on"]:
            return "wire set_device not reflected"
        try:
            client.device(dev_id="nope")
            return "wire unknown-device error not surfaced"
        except KeyError:
            pass
        client.toggle_rule(rule_id="occ_light_meeting", enabled=False)
        rules = client.rules()
        if next(r for r in rules
                if r["id"] == "occ_light_meeting")["enabled"]:
            return "wire toggle_rule not reflected"
        client.toggle_rule(rule_id="occ_light_meeting", enabled=True)
        try:
            client.set_device(dev_id="light_lobby", on="banana")
            return "wire bad-value error not surfaced"
        except ValueError:
            pass
        result = client.tick(n=1)
        if result["tick"] < 1:
            return "wire tick failed"
        client.close()
        return True
    finally:
        server.running = False


def check_no_phantom_events_after_load(tmp):
    world, engine, sdk = fresh()
    sdk.contact("door_garage", True)
    world.tick(engine)
    path = os.path.join(tmp, "vulcan_open.json")
    sdk.save(path=path)
    world2, engine2, sdk2 = fresh()
    sdk2.load(path=path)
    before = sum(1 for e in world2.events
                 if e["kind"] == "event"
                 and "contact_open" in e["text"])
    world2.tick(engine2)
    after = sum(1 for e in world2.events
                if e["kind"] == "event"
                and "contact_open" in e["text"])
    if after != before:
        return "restored open contact re-fired contact_open"
    if world2.devices["door_garage"].open is not True:
        return "contact state not restored as open"
    return True


def check_motion_events_and_sequence():
    world, engine, sdk = fresh()
    sdk.toggle_rule("occ_light_meeting", enabled=False)
    sdk.motion("meeting", people=3)
    world.tick(engine)
    if not world.devices["window_meeting"].open:
        return "sequence rule did not open blinds on fire"
    world.tick(engine)
    if not (world.devices["light_meeting"].on
            and world.devices["light_meeting"].brightness == 100):
        return "sequence step 0 did not apply"
    world.tick(engine)
    world.tick(engine)
    if world.devices["hvac_meeting"].mode != "cool" \
            or world.devices["hvac_meeting"].target != 20.0:
        return "deferred sequence step did not apply after gap"
    return True


def check_max_fires_exhaustion():
    _, _, sdk = fresh()
    sdk.add_rule(spec={
        "id": "oneshot", "trigger": {"type": "tick"}, "max_fires": 2,
        "then": [{"kind": "log", "text": "boom"}]})
    for _ in range(5):
        sdk.tick(n=1)
    if next(r for r in sdk.rules() if r["id"] == "oneshot")["enabled"]:
        return "max_fires did not disable exhausted rule"
    return True


def check_circuit_breaker_and_revival():
    world, engine, sdk = fresh()
    at(world, 10)
    engine._last_minute = world.clock_minutes()
    sdk.add_rule(spec={
        "id": "broken_rule", "trigger": {"type": "tick"},
        "then": [{"kind": "device", "device": "light_hallway",
                  "set": {"brightness": "banana"}}]})
    limit = content.WARDEN["rule_fail_limit"]
    revive = content.WARDEN["rule_revive_ticks"]
    for _ in range(limit):
        sdk.tick(n=1)
    rule = next(r for r in sdk.rules() if r["id"] == "broken_rule")
    if rule["enabled"]:
        return f"circuit breaker did not trip after {limit} failures"
    if "broken_rule" not in engine.quarantined:
        return "rule not quarantined"
    if not any("auto-disabled" in a["text"] for a in world.alerts):
        return "no quarantine alert"
    sdk.tick(n=revive + 1)
    rule = next(r for r in sdk.rules() if r["id"] == "broken_rule")
    if not rule["enabled"]:
        return "quarantined rule never revived"
    return True


def check_warden_waste_hvac():
    world, engine, _ = fresh()
    world.set_hvac("lobby", {"mode": "heat", "target": 24.0})
    world.devices["door_front"].open = True
    world.tick(engine)
    if world.devices["hvac_lobby"].mode != "off":
        return "warden did not stop HVAC with door open"
    if not any(r["category"] == "waste" for r in engine.warden_obj.repairs):
        return "waste repair not logged"
    return True


def check_warden_runaway_cooldown():
    world, engine, sdk = fresh()
    at(world, 10)
    engine._last_minute = world.clock_minutes()
    sdk.set_hvac("office_a", mode="heat", target=30.0)
    saw_cooldown = False
    for _ in range(int(content.WARDEN["runaway_hvac_ticks"]) + 6):
        world.tick(engine)
        hvac = world.devices["hvac_office_a"]
        if hvac.cooldown_ticks > 0 and hvac.duty is None:
            saw_cooldown = True
            break
    if not saw_cooldown:
        return "runaway HVAC was never forced into cooldown"
    if not any(r["category"] == "hvac" for r in engine.warden_obj.repairs):
        return "runaway repair not logged"
    return True


def check_warden_stuck_sensor():
    world, engine, sdk = fresh()
    sdk.motion("office_b")
    zone = world.zones["office_b"]
    frozen = round(zone.temp, 3)
    for i in range(content.WARDEN["stuck_sensor_ticks"]):
        zone.history.append(frozen)
    world.tick(engine)
    stuck_fixes = [r for r in engine.warden_obj.repairs
                   if r["category"] == "sensor"]
    if not stuck_fixes:
        return "stuck sensor not detected despite active zone"
    return True


def check_warden_bounds_clamp():
    world, engine, _ = fresh()
    world.zones["garage"].temp = 999.0
    world.tick(engine)
    if world.zones["garage"].temp > content.WARDEN["sensor_hi_c"]:
        return "impossible reading not clamped"
    if not any("clamped" in r["text"]
               for r in engine.warden_obj.repairs):
        return "clamp repair not logged"
    return True


def check_corrupt_save_fallback(tmp):
    world, engine, sdk = fresh()
    sdk.mode("night")
    path = os.path.join(tmp, "vulcan_rotate.json")
    sdk.save(path=path)
    bak1 = path + ".bak1"
    if not os.path.exists(bak1):
        return "backup rotation missing .bak1"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{corrupt json!!")
    world2, _, sdk2 = fresh()
    result = sdk2.load(path=path)
    if world2.mode != "night":
        return "did not recover state from backup"
    if not any("recovered from backup" in a["text"]
               for a in world2.alerts):
        return "recovery alert missing"
    if "rules_restored" not in result:
        return "automation not restored from backup"
    return True


def check_escalated_shedding():
    world, engine, sdk = fresh()
    for zone in ("lobby", "hallway", "meeting"):
        sdk.set_hvac(zone, mode="heat", target=24.0)
        world.zones[zone].temp = 10.0
    sdk.set_device("rack_fan", on=True)
    world.tick(engine)
    if world.devices["rack_fan"].on:
        return "warden did not escalate shedding to fans"
    shed_repairs = [r for r in engine.warden_obj.repairs
                    if r["category"] == "shed"]
    if not shed_repairs:
        return "escalated shed repair not logged"
    return True


def check_diagnose_endpoint():
    _, _, sdk = fresh()
    report = sdk.diagnose()
    for key in ("warden", "repairs_total", "findings", "fixed_now"):
        if key not in report:
            return f"diagnose missing key: {key}"
    sdk.warden(enabled=False)
    if sdk.diagnose().get("warden") != "off":
        return "warden toggle not reflected"
    sdk.warden(enabled=True)
    return True


CHECKS = [
    ("content integrity", check_content_integrity),
    ("seed building", check_seed_building),
    ("clock advance", check_clock_advance),
    ("thermal drift", check_thermal_drift),
    ("hvac heat + hysteresis", check_hvac_heat_and_hysteresis),
    ("light watts", check_light_watts),
    ("occupancy decay", check_occupancy_decay),
    ("occupancy lighting rule", check_occupancy_lighting_rule),
    ("night schedule scene", check_night_schedule),
    ("security: away + open contact", check_security_away_opening),
    ("freeze guard", check_freeze_guard),
    ("server-room watch", check_server_room_watch),
    ("smoke response", check_smoke_response),
    ("load shedding", check_load_shedding),
    ("save/load roundtrip", check_save_load_roundtrip),
    ("no phantom events after load", check_no_phantom_events_after_load),
    ("rules crud + validation", check_rules_crud),
    ("sdk surface lockstep", check_sdk_surface_lockstep),
    ("wire roundtrip (TCP)", check_wire_roundtrip),
    ("motion events + sequence actions", check_motion_events_and_sequence),
    ("max_fires exhaustion", check_max_fires_exhaustion),
    ("rule circuit breaker + revival", check_circuit_breaker_and_revival),
    ("warden: hvac waste w/ open contact", check_warden_waste_hvac),
    ("warden: runaway hvac cooldown", check_warden_runaway_cooldown),
    ("warden: stuck sensor heal", check_warden_stuck_sensor),
    ("warden: sensor bounds clamp", check_warden_bounds_clamp),
    ("corrupt save fallback", check_corrupt_save_fallback),
    ("warden: escalated shedding", check_escalated_shedding),
    ("diagnose endpoint", check_diagnose_endpoint),
]


def main():
    passed = 0
    failed = []
    with tempfile.TemporaryDirectory(prefix="vulcan_verify_") as tmp:
        for name, fn in CHECKS:
            try:
                if fn.__code__.co_argcount:
                    result = fn(tmp)
                else:
                    result = fn()
            except Exception as exc:
                result = f"exception: {exc!r}"
            if result is True:
                print(f"[PASS] {name}")
                passed += 1
            else:
                detail = result if isinstance(result, str) else str(result)
                print(f"[FAIL] {name}: {detail}")
                failed.append(name)
    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    if failed:
        print("failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
