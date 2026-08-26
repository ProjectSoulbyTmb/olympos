"""MIND state - authoritative snapshot of one live production.

Everything the dashboard, overlays, and rules engine need to know about
the OBS instance, updated from both events and request results. All
access is lock-guarded; snapshots are plain dicts so they can be
serialized without ceremony.

Run: python mind/state.py   (self-test, exit 0 = transitions sane)
"""

from __future__ import annotations

import threading
import time


class ProductionState:
    """Thread-safe view of the directed production."""

    def __init__(self, clock=time.monotonic):
        self._lock = threading.Lock()
        self._clock = clock  # injected: norn-style determinism seam
        self._connected = False
        self._obs_version = ""
        self._program_scene = ""
        self._preview_scene = ""
        self._scenes = []
        self._streaming = False
        self._recording = False
        self._recording_paused = False
        self._muted_inputs = set()
        self._studio_mode = False
        self._updated_at = clock()

    # -- lifecycle ---------------------------------------------------

    def mark_connected(self, obs_version: str = ""):
        with self._lock:
            self._connected = True
            if obs_version:
                self._obs_version = str(obs_version)
            self._touch()

    def mark_disconnected(self):
        with self._lock:
            self._connected = False
            self._touch()

    def _touch(self):
        self._updated_at = self._clock()

    # -- event application (obs-websocket v5 event names) ------------

    def apply_event(self, event_type: str, data: dict):
        with self._lock:
            if event_type == "CurrentProgramSceneChanged":
                self._program_scene = str(data.get("sceneName", ""))
            elif event_type == "CurrentPreviewSceneChanged":
                self._preview_scene = str(data.get("sceneName", ""))
            elif event_type == "SceneListChanged":
                scenes = data.get("scenes")
                if isinstance(scenes, list):
                    self._scenes = [str(s.get("sceneName", ""))
                                    for s in scenes if isinstance(s, dict)]
            elif event_type == "StreamStateChanged":
                self._streaming = bool(data.get("outputActive"))
            elif event_type == "RecordStateChanged":
                active = data.get("outputActive")
                if active is not None:
                    self._recording = bool(active)
                paused = data.get("outputPaused")
                if paused is not None:
                    self._recording_paused = bool(paused)
                    if self._recording_paused:
                        self._recording = True
            elif event_type == "InputMuteStateChanged":
                name = str(data.get("inputName", ""))
                muted = bool(data.get("inputMuted"))
                if name:
                    if muted:
                        self._muted_inputs.add(name)
                    else:
                        self._muted_inputs.discard(name)
            elif event_type == "StudioModeStateChanged":
                self._studio_mode = bool(data.get("studioModeEnabled"))
            else:
                return False
            self._touch()
            return True

    # -- seed from request results ------------------------------------

    def seed_scenes(self, scenes: list, current_program: str,
                    current_preview: str = ""):
        names = [str(s.get("sceneName", ""))
                 for s in scenes if isinstance(s, dict)]
        with self._lock:
            self._scenes = names
            if current_program:
                self._program_scene = str(current_program)
            if current_preview:
                self._preview_scene = str(current_preview)
            self._touch()

    def seed_outputs(self, streaming: bool, recording: bool,
                     recording_paused: bool = False):
        with self._lock:
            self._streaming = bool(streaming)
            self._recording = bool(recording)
            self._recording_paused = bool(recording_paused)
            self._touch()

    # -- reads ---------------------------------------------------------

    def connected(self) -> bool:
        with self._lock:
            return self._connected

    def program_scene(self) -> str:
        with self._lock:
            return self._program_scene

    def snapshot(self) -> dict:
        """Consistent dict for APIs and gates."""
        with self._lock:
            return {
                "connected": self._connected,
                "obs_version": self._obs_version,
                "program_scene": self._program_scene,
                "preview_scene": self._preview_scene,
                "scenes": list(self._scenes),
                "streaming": self._streaming,
                "recording": self._recording,
                "recording_paused": self._recording_paused,
                "muted_inputs": sorted(self._muted_inputs),
                "studio_mode": self._studio_mode,
                "updated_at": self._updated_at,
            }


EVENTS_STATE_MAPS = (
    "CurrentProgramSceneChanged",
    "CurrentPreviewSceneChanged",
    "SceneListChanged",
    "StreamStateChanged",
    "RecordStateChanged",
    "InputMuteStateChanged",
    "StudioModeStateChanged",
)


def selftest() -> int:
    failures = []
    fake = {"t": 0.0}

    def clock():
        return fake["t"]

    def check(name, fn):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")

    def t_transitions():
        state = ProductionState(clock=clock)
        assert not state.connected(), "starts disconnected"
        state.mark_connected("30.0-mock")
        snap = state.snapshot()
        assert snap["connected"] and snap["obs_version"] == "30.0-mock"

        assert state.apply_event("CurrentProgramSceneChanged",
                                 {"sceneName": "Live"})
        assert state.program_scene() == "Live"
        assert state.apply_event("StreamStateChanged", {"outputActive": True})
        assert state.snapshot()["streaming"] is True
        assert state.apply_event(
            "RecordStateChanged",
            {"outputActive": False, "outputPaused": True})
        snap = state.snapshot()
        # a paused record implies an active record output
        assert snap["recording"] and snap["recording_paused"]

        state.apply_event("InputMuteStateChanged",
                          {"inputName": "Mic", "inputMuted": True})
        state.apply_event("InputMuteStateChanged",
                          {"inputName": "Desk", "inputMuted": True})
        state.apply_event("InputMuteStateChanged",
                          {"inputName": "Mic", "inputMuted": False})
        assert state.snapshot()["muted_inputs"] == ["Desk"]

        state.seed_scenes([{"sceneName": "A"}, {"sceneName": "B"}],
                          "B", "A")
        snap = state.snapshot()
        assert snap["scenes"] == ["A", "B"]
        assert snap["program_scene"] == "B" and snap["preview_scene"] == "A"

        state.mark_disconnected()
        assert not state.snapshot()["connected"]

    def t_unknown_events_ignored():
        state = ProductionState()
        assert not state.apply_event("VendorEvent", {"any": 1}), \
            "unknown events must not corrupt state"

    check("state-transitions", t_transitions)
    check("unknown-events-ignored", t_unknown_events_ignored)

    print(f"state selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
