"""MIND director - the assembly root wiring OBS to every surface.

One object owns the truth (snapshot), the voice (bus), the memory
(journal), the reflexes (flows), and the face (surface registry).
Everything else is plumbing between those five.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.request

from . import DEFAULT_DASHBOARD_PORT, DEFAULT_OBS_PORT, __version__
from . import flows as flows_mod
from . import snapshot as snapshot_mod
from .bus import Bus
from .journal import Journal
from .obsclient import ObsClient, ObsClientError
from .snapshot import Snapshot, translate_obs_event
from .surfaces import (DashboardSurface, EventsSurface,
                       RecordingControlSurface, Registry,
                       SceneControlSurface, StreamControlSurface,
                       TimerOverlaySurface, TallyOverlaySurface,
                       HealthSurface, StatusSurface, build_server)

RECONNECT_DELAY_S = 2.0


class ConfigError(ValueError):
    pass


class Director:
    def __init__(self, config: dict, dry_run: bool = False,
                 journal_path: str = None, obs_factory=None):
        if not isinstance(config, dict):
            raise ConfigError("config must be a JSON object")
        obs_cfg = config.get("obs") or {}
        dash_cfg = config.get("dashboard") or {}
        try:
            self.obs_host = str(obs_cfg.get("host", "127.0.0.1"))
            self.obs_port = int(obs_cfg.get("port", DEFAULT_OBS_PORT))
            self.obs_password = str(obs_cfg.get("password", "") or "")
            self.dash_host = str(dash_cfg.get("host", "127.0.0.1"))
            self.dash_port = int(
                dash_cfg.get("port", DEFAULT_DASHBOARD_PORT))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"bad config values: {exc}") from exc

        try:
            self.flows = flows_mod.parse_flows(config.get("flows", []))
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        self.last_fired = {}

        if journal_path:
            path = journal_path
        elif config.get("journal_path"):
            path = config["journal_path"]
        else:
            import tempfile
            import os
            path = os.path.join(tempfile.mkdtemp(prefix="mind-journal-"),
                                "journal.jsonl")
        self.journal = Journal(path)

        self.snapshot = Snapshot()
        self.bus = Bus()
        self.registry = self._build_registry()

        self.dry_run = bool(dry_run)
        self.obs_factory = obs_factory or (
            lambda: ObsClient(self.obs_host, self.obs_port,
                              password=self.obs_password))
        self.client = None
        self.server = None
        self._server_thread = None
        self._pump_thread = None
        self._stopped = threading.Event()

    # -- surfaces ------------------------------------------------------------

    def _build_registry(self) -> Registry:
        reg = Registry()
        reg.register(DashboardSurface(__version__))
        reg.register(StatusSurface(self.snapshot))
        reg.register(HealthSurface(__version__))
        reg.register(EventsSurface(self.bus))
        reg.register(TallyOverlaySurface())
        reg.register(TimerOverlaySurface())
        reg.register(SceneControlSurface(self.control))
        reg.register(StreamControlSurface(self.control))
        reg.register(RecordingControlSurface(self.control))
        return reg

    def start_server(self, host: str = None, port: int = None):
        if self.server is not None:
            return
        self.server = build_server(
            self.registry, host or self.dash_host,
            int(port if port is not None else self.dash_port))
        self._server_thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True, name="mind-http")
        self._server_thread.start()

    @property
    def url(self) -> str:
        port = self.server.server_address[1] if self.server \
            else self.dash_port
        return f"http://127.0.0.1:{port}"

    # -- OBS link ---------------------------------------------------------------

    def connect_once(self):
        """One supervised connection attempt; seeds the snapshot."""
        client = self.obs_factory()
        info = client.connect()          # raises ObsClientError on refusal
        self.client = client
        scenes = client.call("GetSceneList")
        stream_status = client.call("GetStreamStatus")
        record_status = client.call("GetRecordStatus")
        names = [s.get("sceneName") for s in scenes.get("scenes", [])]
        self.snapshot.seed(
            scenes=names,
            program=scenes.get("currentProgramSceneName"),
            preview=scenes.get("currentPreviewSceneName"),
            streaming=bool(stream_status.get("outputActive")),
            recording=bool(record_status.get("outputActive")),
            obs_version=info.get("obsWebSocketVersion"))
        self.journal.append("connected",
                            obs=info.get("obsWebSocketVersion"),
                            scenes=len(names))
        self.bus.publish(snapshot_mod.CONNECTED, {})
        self._pump_thread = threading.Thread(target=self._pump,
                                             daemon=True,
                                             name="mind-obs-pump")
        self._pump_thread.start()

    def _pump(self):
        while not self._stopped.is_set() and self.client is not None:
            got = self.client.poll(timeout=0.25)
            if got is None:
                if not self.client.connected:
                    break
                continue
            translated = translate_obs_event(got[0], got[1])
            if translated is None:
                continue
            event_type, data = translated
            changed = self.snapshot.apply(event_type, data)
            if changed or event_type == snapshot_mod.CONNECTED:
                self.bus.publish(event_type, data)
                self.observe_rules(event_type, data)

    def observe_rules(self, trigger: str, data: dict):
        """Plan + launch reactions for an event; never blocks the pump."""
        planned = flows_mod.plan(self.flows, trigger, data,
                                 time.monotonic(), self.last_fired)
        for flow, steps in planned:
            self.last_fired[flow.id] = time.monotonic()
            threading.Thread(target=self.execute_flow,
                             args=(flow, steps),
                             daemon=True,
                             name=f"mind-flow-{flow.id}").start()

    def execute_flow(self, flow, steps: list):
        self.journal.append("flow-fired", flow=flow.id,
                            steps=len(steps))
        results = []
        for step in steps:
            outcome = self.execute_step(step)
            results.append(outcome)
        self.journal.append("flow-done", flow=flow.id,
                            results=results)

    def execute_step(self, step: dict) -> str:
        action = step["action"]
        if action == "log":
            self.journal.append("flow-log", message=step["message"])
            return f"log: {step['message']}"
        if action == "wait":
            time.sleep(min(float(step["seconds"]),
                           flows_mod.MAX_WAIT_SECONDS))
            return f"waited {step['seconds']}s"
        if action == "http_get":
            try:
                with urllib.request.urlopen(step["url"],
                                            timeout=10) as resp:
                    code = resp.status
            except Exception as exc:  # noqa: BLE001
                return f"http_get failed: {exc}"
            return f"http_get {step['url']} -> {code}"
        ok, detail = self.control(action, step)
        return detail if ok else f"refused: {detail}"

    # -- the single side-effect door ---------------------------------------------

    def control(self, action: str, data: dict):
        """Every mutation of the production passes through here."""
        data = dict(data or {})
        if action not in ("switch_scene", "set_stream",
                          "set_recording"):
            return False, f"unknown action: {action}"
        if self.dry_run:
            self.journal.append("dry-run", action=action, **data)
            return True, f"dry-run: {action} {data}"
        ok, detail = self._dispatch_control(action, data)
        self.journal.append("control", action=action, ok=bool(ok),
                            detail=str(detail))
        return ok, detail

    def _dispatch_control(self, action: str, data: dict):
        if self.client is None or not self.client.connected:
            return False, "not connected to OBS"
        try:
            if action == "switch_scene":
                name = data["sceneName"]
                self.client.call("SetCurrentProgramScene",
                                 {"sceneName": name})
                return True, f"program -> {name}"
            if action == "set_stream":
                verb = "StartStream" if data["state"] == "start" \
                    else "StopStream"
                self.client.call(verb)
                return True, f"stream {data['state']}ed"
            if action == "set_recording":
                verb = "StartRecord" if data["state"] == "start" \
                    else "StopRecord"
                self.client.call(verb)
                return True, f"recording {data['state']}ed"
        except KeyError as exc:
            return False, f"missing field: {exc}"
        except ObsClientError as exc:
            return False, str(exc)
        return False, "unhandled action"

    # -- lifecycle ------------------------------------------------------------------

    def supervise_forever(self):
        """Reconnect with backoff until stopped."""
        while not self._stopped.is_set():
            if self.client is None or not self.client.connected:
                try:
                    self.connect_once()
                except ObsClientError:
                    pass
            self._stopped.wait(RECONNECT_DELAY_S)

    def stop(self):
        self._stopped.set()
        client, self.client = self.client, None
        if client is not None:
            client.close()
        server, self.server = self.server, None
        if server is not None:
            server.shutdown()
            server.server_close()


# -- dress rehearsal ------------------------------------------------------------


def run_demo(journal_path: str = None) -> dict:
    """Full rehearsal against the bundled mock OBS.

    Returns {"ok": bool, "steps": [{"step", "ok", "detail"}]}.
    """
    from .mockobs import MockObsServer

    report = {"ok": True, "steps": []}

    def step(name, fn):
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        report["steps"].append({"step": name, "ok": bool(ok),
                                "detail": str(detail)})
        report["ok"] = report["ok"] and ok

    obs = MockObsServer(scenes=["Live", "BRB", "Starting Soon"],
                        program="Live", preview="Starting Soon")

    config = {
        "obs": {"host": "127.0.0.1", "port": None, "password": ""},
        "dashboard": {"host": "127.0.0.1", "port": 0},
        "flows": [
            {"id": "demo-archive",
             "on": "stream_started",
             "then": [{"action": "set_recording", "state": "start"}]},
        ],
    }

    def boot_mockobs():
        obs.start()
        config["obs"]["port"] = obs.port
        return obs.port > 0, f"mock OBS on :{obs.port}"

    step("boot-mockobs", boot_mockobs)

    def director_serves():
        holder["d"] = _build_director(config)
        return True, f"serving {holder['d'].url}"

    holder = {}
    step("director-serves", director_serves)
    director = holder.get("d")
    if director is None:
        report["ok"] = False
        report["steps"].append({"step": "aborted",
                                "ok": False,
                                "detail": "director failed to build"})
        return report

    def dashboard_served():
        body = _http_get(director.url + "/").decode()
        return "MIND" in body, f"{len(body)} bytes"

    step("dashboard-served", dashboard_served)

    def obs_connected():
        director.connect_once()
        return director.snapshot.program_scene == "Live", \
            f"program={director.snapshot.program_scene}"

    step("obs-connected-synced", obs_connected)

    seen = director.bus.subscribe("demo-rehearsal")

    def status_api():
        payload = json.loads(_http_get(director.url + "/api/status"))
        return payload.get("programScene") == "Live", \
            f"scenes={payload.get('scenes')}"

    step("status-api", status_api)

    def switch_via_surface():
        answer = _http_post(director.url + "/api/scene",
                            {"sceneName": "BRB"})
        ok = answer.get("ok") is True
        reached = _wait_until(lambda: director.snapshot.program_scene
                              == "BRB")
        return ok and reached, json.dumps(answer)

    step("scene-switch-via-surface", switch_via_surface)

    def sse_feed_delivered():
        got = _wait_until(lambda: _drain_has(seen, "scene_changed"))
        return got, "scene_changed observed on the bus"

    step("sse-feed-delivered", sse_feed_delivered)

    def flow_archives_on_live():
        answer = _http_post(director.url + "/api/stream",
                            {"state": "start"})
        started = _wait_until(lambda: director.snapshot.streaming)
        recorded = _wait_until(lambda: director.snapshot.recording,
                               timeout=8.0)
        return (answer.get("ok") is True and started and recorded,
                f"streaming={started} auto-record={recorded}")

    step("flow-archive-on-live", flow_archives_on_live)

    def invalid_refused():
        answer = _http_post(director.url + "/api/stream",
                            {"state": "explode"})
        return answer.get("ok") is False, json.dumps(answer)

    step("invalid-input-refused", invalid_refused)

    def journal_audited():
        kinds = [e.get("kind") for e in director.journal.entries()]
        return ("connected" in kinds and "flow-fired" in kinds
                and "control" in kinds), ",".join(sorted(set(kinds)))

    step("journal-audited", journal_audited)

    def teardown():
        director.stop()
        obs.stop()
        return True, "clean exit"

    step("teardown-clean", teardown)
    return report


def _build_director(config):
    director = Director(config)
    director.start_server()
    return director


def _drain_has(q, event_type: str) -> bool:
    found = False
    while True:
        try:
            kind, _ = q.get_nowait()
        except queue.Empty:
            return found
        found = found or kind == event_type


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _http_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read()


def _http_post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as resp:
        return json.loads(resp.read())


def selftest(tmp_dir: str = None) -> int:
    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL director.{name}")
            failures.append(name)

    import tempfile
    import os
    tmp_dir = tmp_dir or tempfile.mkdtemp(prefix="mind-director-")
    jp = os.path.join(tmp_dir, "j.jsonl")
    d = Director({"obs": {"port": DEFAULT_OBS_PORT}},
                 dry_run=True, journal_path=jp)
    check("registry-complete", len(d.registry) == 9)
    routes = sorted((s.route, tuple(s.methods))
                    for s in d.registry)
    check("routes-exact",
          ("/api/scene", ("POST",)) in routes
          and ("/overlay/tally", ("GET",)) in routes)
    check("no-server-yet", d.server is None)
    d.start_server(port=0)
    check("server-binds", d.server is not None
          and d.server.server_address[1] > 0)
    ok, detail = d.control("switch_scene", {"sceneName": "X"})
    check("dry-run-logs", ok and "dry-run" in detail)
    ok, _ = d.control("bogus_action", {})
    check("unknown-action-refused", ok is False)
    rows = [e["kind"] for e in d.journal.entries()]
    check("journal-captures-dry-run", "dry-run" in rows)
    d.stop()
    check("stop-clears-server", d.server is None)

    try:
        Director({"flows": [{"id": "x", "on": "nope",
                             "then": [{"action": "log",
                                       "message": "m"}]}]},
                 journal_path=jp)
        check("bad-flows-refused", False)
    except ConfigError:
        check("bad-flows-refused", True)

    print(f"director selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
