# Vulcan — smart-building automation sandbox

Offline smart-building simulation: a thermal model of zones and devices,
a schema-gated rules engine, and a warden that self-heals. Vulcan is the
**proving ground** where autonomous build-and-verify loops harden before
they target arbitrary projects — every SDK verb already carries rights
checks, schema gates, and verify coverage here, so hardening done once
transfers to the wider build loop (see `INTEGRATION.md` §7).

Everything runs locally against local state. No external services, no
shipped scrapers.

## House contract

The 2026-08-23 contract that defines Vulcan:

- **All numbers live in `content.py`.** Mechanics modules import it and
  never re-declare a table. Prose references the constant, it does not
  print the value (see "Where the numbers live").
- **Authoritative JSON-lines server** on `127.0.0.1:43901`. Every
  response object carries an `error` field (null on success),
  mirroring the ZEUS server contract.
- **One SDK surface.** `VulcanSDK` (in-process) and `VulcanClient`
  (TCP wire) expose identical method names, so automation written
  against one runs unchanged against the other.
- **Versioned saves** carry the full ruleset (`SAVE_VERSION` in
  `content.py`); corrupt saves recover from rotating backups.
- **Own verify gate.** `python vulcan/verify_vulcan.py` — 27 checks,
  exit code is the verdict.

## Architecture

| Module | Role |
|---|---|
| `content.py` | Single source of truth: device specs, seed zones, thresholds, scenes, default rules, warden tuning. No logic, only tables. |
| `world.py` | `World` simulation: zones, devices, thermal drift, clock, occupancy, power, alerts/events/stats. One building. |
| `rules.py` | `RuleEngine`: schema-gated automation (triggers / `when` / `then`), CRUD, rule circuit breakers + quarantine/revival. |
| `warden.py` | `Warden`: per-tick self-diagnostics and automatic repair (waste, runaway HVAC, stuck sensors, vacant lights, load shedding). |
| `sdk.py` | `VulcanSDK` + `VulcanClient` — the only surface dashboards and automation see. |
| `host.py` | `BuildingServer`: authoritative JSON-lines server, NORN pulse tick heart, witness attestation, rights profiles. |
| `cli.py` | Console: interactive building control, local or connected. |
| `verify_vulcan.py` | The 27-check gate. |

All Python realms are standard-library only.

## Quick start

```powershell
# console on a fresh local building (no server needed)
python -m vulcan.cli

# run one command and exit
python -m vulcan.cli -c "status"
python -m vulcan.cli -c "scene night"
python -m vulcan.cli -c "diagnose"

# host the building, then connect a dashboard from elsewhere
python vulcan/host.py
python -m vulcan.cli --connect 127.0.0.1 43901
```

Inside the console, `help` lists every command: `status`, `zones`,
`zone NAME`, `devices`, `device ID`, `set`, `hvac`, `motion`, `contact`,
`smoke`, `weather`, `scene`, `mode`, `rules`, `rule_add`, `rule_toggle`,
`rule_del`, `repairs`, `diagnose`, `warden`, `alerts`, `events`,
`stats`, `tick`, `save`, `load`.

## The SDK surface

`VulcanSDK` and `VulcanClient` share these verbs:

`ping` · `state` · `zones` · `zone` · `devices` · `device` ·
`set_device` · `set_hvac` · `motion` · `contact` · `smoke` ·
`outside_temp` · `scene` · `mode` · `rules` · `add_rule` ·
`toggle_rule` · `delete_rule` · `alerts` · `events` · `stats` ·
`tick` · `save` · `load` · `warden` · `diagnose` · `repairs`

Every mutating verb is attested by the NORN witness when a server is
hosted; info verbs are not. Rights profiles narrow which verbs a
connection may call — escalation is logged, never silent.

## The warden

The warden patrols after every tick and fixes what it can on its own,
logging every intervention as a repair:

- **Waste** — stops HVAC left running with a window/door open.
- **Runaway HVAC** — forces a cooldown when a unit holds duty too long
  without reaching target.
- **Stuck sensors** — substitutes a neighbour-estimated reading for a
  sensor frozen while its zone is active.
- **Bounds clamp** — clamps impossible temperature readings.
- **Vacant lights** — switches off lights left on in empty zones during
  `away`/`vacation` mode.
- **Escalated shedding** — drops fans last when power still exceeds the
  limit after plugs are shed; raises a critical alert if nothing is left
  to shed.

Rule failures trip a circuit breaker after `rule_fail_limit` consecutive
failures, quarantine the rule, and auto-revive it after a cool-down.

## Rules engine

Automation is data, not code. A rule is a `trigger` (`tick` / `schedule`
/ `event`), an optional `when` condition, and a list of `then` actions
(`set` device, `scene`, `lock_all`, `unlock_all`, `hvac_all_off`,
`alert`, `shed`, `sequence`, …). A schema gate rejects malformed rules
with precise messages; builtin rules cannot be deleted. See the seed
rules in `content.py` (`occ_light_*`, `sched_night`, `sched_morning`,
`sec_away_open`, `smoke_response`, `freeze_guard`, `server_room_watch`,
`load_shed`, `meeting_prep_sequence`, `evening_precool`).

## Server & protocol

```
-> {"cmd": "state", "args": {}}
<- {"error": null, "result": {...}}
```

- Host `127.0.0.1`, port `43901` (`content.SERVER_PORT`). A port
  collision fails loudly rather than double-binding.
- Every response carries `error` (null on success). Wire errors name the
  fault: `"unknown command"`, `"bad json"`, `"missing cmd"`,
  `"right_denied: ..."`, `"server full"`.
- An optional background thread auto-ticks the building so hosted runs
  stay alive on their own (`TICK_SECONDS_REAL` in `content.py`).

## Verify gate

```powershell
python vulcan/verify_vulcan.py   # 27 checks; exit 0 = all pass
```

Covers content integrity, seed building, clock/thermal drift, HVAC
heat + hysteresis, light watts, occupancy decay + lighting rules, night
schedule, security-while-away, freeze guard, server-room watch, smoke
response, load shedding, save/load roundtrip (+ no phantom events),
rules CRUD + validation, SDK/wire surface lockstep, motion + sequence
actions, `max_fires` exhaustion, rule circuit breaker + revival, every
warden repair path, corrupt-save fallback, and the `diagnose` endpoint.
Wired into `doctor.py`, `sentinel.py`, and CI.

## Where the numbers live

Do not hardcode a Vulcan tunable in prose or in mechanics. They all sit
in `content.py`:

- Server: `SERVER_HOST`, `SERVER_PORT`, `MAX_SESSIONS`, `MAX_LINE_BYTES`.
- Time: `TICK_SECONDS_REAL`, `TICK_MINUTES_SIM`, `START_CLOCK`.
- Envelope/thermal: `OUTSIDE_TEMP_C`, `ENVELOPE_LOSS_PER_TICK`,
  `INTERZONE_DIFFUSION`, `OCCUPANT_HEAT_C`, `HVAC_MAX_DELTA_C`.
- Zones/devices: `SEED_ZONES`, `DEVICE_TYPES`, `MODES`.
- Comfort/safety: `COMFORT_TARGET_C`, `HYSTERESIS_C`, `FREEZE_ALARM_C`,
  `OVERHEAT_ALARM_C`, `SERVER_ROOM_MAX_C`, `POWER_LIMIT_W`.
- Warden: `WARDEN` (all thresholds + `backup_copies`).
- Scenes/rules: `SCENES`, `DEFAULT_RULES`.

## See also

- `INTEGRATION.md` — runtime topology, letter envelope, rights ladder,
  the autonomous build loop (Vulcan is the proving ground).
- `DESIGN.md` — architecture table + decision log (Vulcan house contract).
- `STRATEGY.md` — tier model; Vulcan is a Tier 2 realm.
