# MIND

**Modular Intelligent Network Director** - a local-first OBS-companion
organ. It watches a live production over `obs-websocket` v5, keeps an
authoritative snapshot of production state, runs operator-authored
reaction flows, and serves a single-port control plane.

Version 2 is a complete rewrite organized around one idea: every way
the outside world touches MIND is a **surface** - a named, routable,
individually testable endpoint.

Standard library only. Python >= 3.9. Local only: no cloud, no remote
repository, no telemetry.

## Quickstart

```powershell
python -m mind demo                 # full rehearsal against mock OBS
python -m mind selfcheck            # module-level sanity sweep
python verify.py                    # the green/red gate (all three rings)

copy config.example.json mind.config.json   # then edit host/port/password
python -m mind serve                # direct a real OBS Studio
python -m mind serve --dry-run      # log flows without touching OBS
python -m mind status               # poll a running dashboard
```

## Surfaces (one port, nine endpoints)

| Surface | Route | Method | Purpose |
|---|---|---|---|
| dashboard | `/` | GET | operator single pane (dark, live) |
| status | `/api/status` | GET | production snapshot as JSON |
| events | `/api/events` | GET | Server-Sent Events feed |
| tally overlay | `/overlay/tally` | GET | browser-source program/preview light (`?scene=Name`) |
| timer overlay | `/overlay/timer` | GET | browser-source countdown (`?t=HH:MM:SS`) |
| health | `/healthz` | GET | liveness probe |
| scene control | `/api/scene` | POST | `{"sceneName": "..."}` |
| stream control | `/api/stream` | POST | `{"state": "start"\|"stop"}` |
| recording control | `/api/recording` | POST | `{"state": "start"\|"stop"}` |

Every POST answer is JSON with the verdict in `ok`. Malformed input is
refused at the surface, before it can reach OBS.

## Architecture

```
obs-websocket v5 ──> ObsClient ──> Director pump ──> Snapshot (truth)
                                        │                │
                                     Flows (reflex)    Bus (voice)
                                        │                │
                                  Journal (memory)   Surfaces (face)
                                                         │
                                          dashboard / status / sse /
                                          overlays / controls / health
```

* **snapshot.py** - authoritative production state; updated only from canonical events.
* **bus.py** - bounded pub/sub; slow SSE consumers shed oldest events, never stall the director.
* **flows.py** - pure planner (`plan()` has no I/O); execution lives in the director.
* **journal.py** - append-only JSONL audit trail.
* **obswire.py / obsclient.py** - RFC 6455 framing + obs-websocket v5 session.
* **mockobs.py** - fake OBS Studio for demos and gates.
* **surfaces/** - the HTTP control plane; `base.Surface` + `Registry`, generic server loop in `http.py`.

## Flows (operator reactions)

```json
{
  "id": "brb-return",
  "on": "scene_changed",
  "when": { "scene_in": ["BRB"] },
  "cooldown_s": 60,
  "then": [
    { "action": "wait", "seconds": 10 },
    { "action": "switch_scene", "sceneName": "Live" }
  ]
}
```

Events: `connected`, `scene_changed`, `stream_started`,
`stream_stopped`, `recording_started`, `recording_stopped`.
Actions: `log`, `wait`, `switch_scene`, `set_stream`, `set_recording`,
`http_get`. Invalid flows are rejected at load with a problem list.

## Waiting orders

`ordersctl.py` is a local queue for future work: orders wait until you
release them by id ("whenever you say").

```powershell
py ordersctl.py place <id> --title "..." [--note "..."] [--payload-file ctx.json]
py ordersctl.py list            # what's waiting
py ordersctl.py release <id>    # fire it now (prints note + payload)
py ordersctl.py cancel <id>     # refuse it
py ordersctl.py log             # audit trail
```

Queue lives in `orders/` (override with `--home` or
`MIND_ORDERS_HOME`). Ids are permanent; released orders move to
`orders/done/`, refused ones to `orders/cancelled/`.

## Gates

```powershell
python -m unittest discover -s tests -v   # ring 1: unit tests
python -m mind selfcheck                  # ring 2: module selftests
python -m mind demo                       # ring 3: dress rehearsal
python verify.py                          # all three, GREEN or RED
```

## Layout

```
mind/            package (surfaces/ is the control plane)
tests/           unittest suite
verify.py        green/red gate
config.example.json
```
