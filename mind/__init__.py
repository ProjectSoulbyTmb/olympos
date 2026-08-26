"""MIND - Modular Intelligent Network Director.

An OBS-companion organ for Project Olympos: it watches a live
production over the obs-websocket v5 protocol, keeps an authoritative
snapshot of production state, runs operator-authored reaction flows,
and serves a local-first control plane (dashboard, status API, SSE
event feed, browser-source overlays).

Born from studying the OBS community's open-source tools: automation
flows (Strem), tally awareness (MultiTally), push overlays (Current
Song 2), URL-parameterized browser sources (Browser Timer), and audio
state scripts (QlistGO) - unified behind one stdlib-only director.

    python -m mind demo        # full dress rehearsal against a mock OBS
    python -m mind selfcheck   # internal consistency sweep
    python -m mind serve       # direct a real OBS Studio instance
"""

__version__ = "1.11.0"

ORGAN = "mind"
DEFAULT_DASHBOARD_PORT = 43906
DEFAULT_OBS_PORT = 4455
