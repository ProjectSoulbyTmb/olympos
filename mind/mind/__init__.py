"""MIND - Modular Intelligent Network Director (v2).

A local-first OBS-companion organ, rewritten around one idea: every way
the outside world touches MIND is a **surface** - a named, routable,
individually testable endpoint on a single HTTP port.

Surfaces v2:

    GET  /                operator dashboard
    GET  /api/status       production snapshot as JSON
    GET  /api/events       Server-Sent Events feed (push, not poll)
    GET  /overlay/tally    browser-source tally light
    GET  /overlay/timer    browser-source countdown (?t=HH:MM:SS)
    GET  /healthz          liveness probe
    POST /api/scene       {"sceneName": "..."}   switch program scene
    POST /api/stream      {"state": "start"|"stop"}
    POST /api/recording   {"state": "start"|"stop"}

Under the surfaces sits the same quiet machinery as v1: an obs-websocket
v5 client, an authoritative production snapshot, operator-authored
reaction flows, and a JSONL audit journal. Standard library only.
"""

__version__ = "2.0.0"

ORGAN = "mind"
DEFAULT_DASHBOARD_PORT = 43906
DEFAULT_OBS_PORT = 4455
