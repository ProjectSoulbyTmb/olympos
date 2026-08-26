"""MIND snapshot - the authoritative production state.

MIND keeps one opinion of the production, updated only from canonical
events (never scraped). Surfaces read it; flows react to it; nothing
else writes it.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

# canonical event names (flows subscribe on these)
CONNECTED = "connected"
SCENE_CHANGED = "scene_changed"
STREAM_STARTED = "stream_started"
STREAM_STOPPED = "stream_stopped"
RECORDING_STARTED = "recording_started"
RECORDING_STOPPED = "recording_stopped"

ALL_EVENTS = (CONNECTED, SCENE_CHANGED, STREAM_STARTED, STREAM_STOPPED,
              RECORDING_STARTED, RECORDING_STOPPED)

# obs-websocket v5 event -> (canonical, derived data)
_OBS_EVENT_MAP = {
    "CurrentProgramSceneChanged": lambda d: (
        SCENE_CHANGED, {"scope": "program",
                        "sceneName": d.get("sceneName")}),
    "CurrentPreviewSceneChanged": lambda d: (
        SCENE_CHANGED, {"scope": "preview",
                        "sceneName": d.get("sceneName")}),
    "StreamStateChanged": lambda d: (
        STREAM_STARTED if d.get("outputActive") else STREAM_STOPPED,
        {}),
    "RecordStateChanged": lambda d: (
        RECORDING_STARTED if d.get("outputActive")
        else RECORDING_STOPPED, {}),
}


def translate_obs_event(event_type: str, data: dict):
    """Return (canonical_name, data) or None if uninteresting."""
    fn = _OBS_EVENT_MAP.get(event_type)
    if fn is None:
        return None
    return fn(data or {})


class Snapshot:
    """Thread-safe production truth."""

    def __init__(self):
        self._lock = threading.Lock()
        self.connected = False
        self.obs_version = None
        self.program_scene = None
        self.preview_scene = None
        self.scenes = []
        self.streaming = False
        self.recording = False
        self.updated_at = None

    def seed(self, scenes=None, program=None, preview=None,
             streaming=False, recording=False, obs_version=None):
        with self._lock:
            self.connected = True
            self.scenes = list(scenes or [])
            self.program_scene = program
            self.preview_scene = preview
            self.streaming = bool(streaming)
            self.recording = bool(recording)
            self.obs_version = obs_version
            self.updated_at = _now()

    def apply(self, event_type: str, data: dict) -> bool:
        """Apply a canonical event; True if state visibly changed."""
        changed = False
        with self._lock:
            if event_type == SCENE_CHANGED:
                scope = (data or {}).get("scope", "program")
                name = (data or {}).get("sceneName")
                if scope == "program":
                    changed = self.program_scene != name
                    self.program_scene = name
                else:
                    changed = self.preview_scene != name
                    self.preview_scene = name
            elif event_type == STREAM_STARTED and not self.streaming:
                self.streaming, changed = True, True
            elif event_type == STREAM_STOPPED and self.streaming:
                self.streaming, changed = False, True
            elif event_type == RECORDING_STARTED and not self.recording:
                self.recording, changed = True, True
            elif event_type == RECORDING_STOPPED and self.recording:
                self.recording, changed = False, True
            elif event_type == CONNECTED and not self.connected:
                self.connected, changed = True, True
            if changed:
                self.updated_at = _now()
        return changed

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "organ": "mind",
                "connected": self.connected,
                "obsVersion": self.obs_version,
                "programScene": self.program_scene,
                "previewScene": self.preview_scene,
                "scenes": list(self.scenes),
                "streaming": self.streaming,
                "recording": self.recording,
                "updatedAt": self.updated_at,
            }


def _now():
    return datetime.now(timezone.utc).isoformat()


def selftest() -> int:
    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL snapshot.{name}")
            failures.append(name)

    s = Snapshot()
    check("starts-disconnected", s.to_dict()["connected"] is False)
    s.seed(scenes=["Live", "BRB"], program="Live", preview="BRB",
           streaming=False, recording=True, obs_version="mock/1")
    d = s.to_dict()
    check("seeded", d["programScene"] == "Live"
          and d["scenes"] == ["Live", "BRB"] and d["recording"] is True)

    changed = s.apply(SCENE_CHANGED,
                      {"scope": "program", "sceneName": "BRB"})
    check("program-change-applies",
          changed and s.to_dict()["programScene"] == "BRB")

    check("no-change-reports-false",
          s.apply(SCENE_CHANGED,
                  {"scope": "program", "sceneName": "BRB"}) is False)

    s.apply(STREAM_STARTED, {})
    check("stream-on", s.to_dict()["streaming"] is True)
    s.apply(STREAM_STOPPED, {})
    check("stream-off", s.to_dict()["streaming"] is False)

    t = translate_obs_event("StreamStateChanged", {"outputActive": True})
    check("translate-stream", t[0] == STREAM_STARTED)
    check("translate-ignore", translate_obs_event("VendorEvent", {}) is None)

    print(f"snapshot selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
