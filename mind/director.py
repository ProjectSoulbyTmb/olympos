"""MIND director - the organ's brainstem.

Wires the OBS session, production state, event bus, rules engine,
journal, and HTTP control plane into one running whole:

    OBS -> ObsClient -> handle_event -> ProductionState + Bus
                                    -> rules.observe -> executor
    HTTP dashboard/API/overlays -> controller -> ObsClient

`run_demo` performs a full dress rehearsal against a scripted mock OBS
over real sockets and returns a structured report - it doubles as the
verify gate's end-to-end section.

Run: python mind/director.py   (self-test = quick wiring sanity)
"""

from __future__ import annotations

import json
import queue
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import DEFAULT_DASHBOARD_PORT
from .bus import Bus
from .client import ObsClient, ObsClientError
from .journal import Journal
from .mockobs import MockObsServer
from .protocol import EventSubscription
from .rules import RulesConfigError, observe, validate_flows
from .server import MindServer
from .state import ProductionState

RECONNECT_BACKOFF = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class Executor:
    """Runs planned rule steps against OBS - or logs them in dry-run."""

    def __init__(self, client_provider, journal: Journal,
                 dry_run: bool = False):
        self.client_provider = client_provider  # -> ObsClient | None
        self.journal = journal
        self.dry_run = dry_run

    def run_step(self, step: dict, flow_id: str) -> "tuple[bool, str]":
        action = step.get("action")
        if self.dry_run:
            return True, f"dry-run {action} {json_compact(step)}"
        try:
            if action == "switch_scene":
                self.client().request(
                    "SetCurrentProgramScene",
                    {"sceneName": str(step["scene"])})
            elif action == "set_recording":
                rtype = ("StartRecord" if step["state"] == "start"
                         else "StopRecord")
                self.client().request(rtype)
            elif action == "set_stream":
                rtype = ("StartStream" if step["state"] == "start"
                         else "StopStream")
                self.client().request(rtype)
            elif action == "http_get":
                url = str(step["url"])
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    resp.read(1024)
            elif action == "log":
                pass  # recorded below regardless
            elif action == "wait":
                time.sleep(min(float(step["seconds"]), 30.0))
            else:
                return False, f"unknown action {action!r}"
        except (ObsClientError, OSError, KeyError, ValueError,
                urllib.error.URLError) as exc:
            return False, f"{action} failed: {exc}"
        self.journal.append("action",
                            {"flow": flow_id, "step": step},
                            source="mind.rules")
        return True, action

    def client(self) -> ObsClient:
        client = self.client_provider()
        if client is None:
            raise ObsClientError("no active obs session")
        return client

    # -- HTTP controller surface ------------------------------------------

    def call_api(self, action: str, payload: dict) \
            -> "tuple[bool, dict]":
        try:
            if action == "switch_scene":
                scene = payload.get("sceneName")
                if not isinstance(scene, str) or not scene:
                    return False, {"error": "sceneName required"}
                if self.dry_run:
                    return True, {"dry_run": True}
                self.client().request("SetCurrentProgramScene",
                                      {"sceneName": scene})
                return True, {}
            if action in ("set_stream", "set_recording"):
                state = payload.get("state")
                if state not in ("start", "stop"):
                    return False, {"error": "state must be start|stop"}
                if self.dry_run:
                    return True, {"dry_run": True}
                table = {
                    "set_stream": ("StartStream", "StopStream"),
                    "set_recording": ("StartRecord", "StopRecord"),
                }
                on, off = table[action]
                self.client().request(on if state == "start" else off)
                return True, {}
            return False, {"error": f"unknown action {action}"}
        except ObsClientError as exc:
            return False, {"error": str(exc)}

    def status_note(self) -> str:
        return "dry-run" if self.dry_run else "armed"


def json_compact(value) -> str:
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)


class Director:
    """Owns one directed production end to end."""

    def __init__(self, config: dict, journal_path: "str | None" = None,
                 dry_run: bool = False, clock=time.monotonic):
        config = config or {}
        obs = config.get("obs") or {}
        dash = config.get("dashboard") or {}

        self.state = ProductionState(clock=clock)
        self.bus = Bus()
        self.flows = validate_flows(config.get("flows", []))
        self.dry_run = bool(dry_run)

        self.journal_path = journal_path or config.get(
            "journal_path") or ""
        if self.journal_path:
            self.journal = Journal(self.journal_path)
        else:
            self.journal = Journal(tempfile.mkstemp(
                prefix="mind-", suffix=".jsonl")[1])

        self.executor = Executor(lambda: self.client, self.journal,
                                 dry_run=self.dry_run)
        # Rule execution runs on its own engine thread. It must never
        # share a stack with the OBS reader: an executor step waits on
        # a RequestResponse only the reader can deliver.
        self._tasks: "queue.Queue" = queue.Queue()
        self._engine: "threading.Thread | None" = None
        self.server = MindServer(
            state_provider=self.state.snapshot,
            bus=self.bus,
            controller=self.executor.call_api,
            host=str(dash.get("host", "127.0.0.1")),
            port=int(dash.get("port", DEFAULT_DASHBOARD_PORT)),
        )
        self.obs_host = str(obs.get("host", "127.0.0.1"))
        self.obs_port = int(obs.get("port", 4455))
        self.password = str(obs.get("password", ""))
        self.client: "ObsClient | None" = None
        self._stop = threading.Event()
        self._supervisor = None
        self._clock = clock

    # -- lifecycle -------------------------------------------------------------

    def start_server(self):
        if self._engine is None or not self._engine.is_alive():
            self._engine = threading.Thread(target=self._engine_loop,
                                            daemon=True,
                                            name="mind-engine")
            self._engine.start()
        self.server.start()
        self.journal.append("server", {"url": self.server.url},
                            source="mind.director")

    def stop(self):
        self._stop.set()
        self._tasks.put(None)  # engine sentinel
        if self._engine is not None:
            self._engine.join(timeout=5.0)
            self._engine = None
        if self.client is not None:
            self.client.close()
            self.client = None
        if self._supervisor is not None:
            self._supervisor.join(timeout=3.0)
            self._supervisor = None
        try:
            self.server.stop()
        except Exception:
            pass

    def _engine_loop(self):
        while True:
            task = self._tasks.get()
            if task is None:
                return
            kind, first, second = task
            try:
                if kind == "event":
                    self._process_event(first, second)
                elif kind == "internal":
                    self._fire_internal(first, second)
            except Exception as exc:  # engine must survive anything
                try:
                    self.journal.append("engine-error",
                                        {"error": repr(exc)},
                                        source="mind.director")
                except OSError:
                    pass

    def connect_once(self) -> ObsClient:
        """Single supervised-free connection attempt (tests, demos)."""
        client = ObsClient(self.obs_host, self.obs_port,
                           password=self.password,
                           on_event=self.handle_event,
                           subscriptions=EventSubscription.ALL)
        client.connect()
        self.client = client
        version = ""
        try:
            version = str(client.request("GetVersion").get(
                "obsVersion", ""))
        except ObsClientError:
            pass
        self.state.mark_connected(version)
        self.seed_from_obs(client)
        self.fire_internal("connected", {})
        self.journal.append("connect",
                            {"host": self.obs_host,
                             "port": self.obs_port,
                             "obsVersion": version},
                            source="mind.director")
        return client

    def supervise_forever(self):
        self.start_server()
        attempt = 0
        while not self._stop.is_set():
            try:
                self.connect_once()
                attempt = 0
                # block while the session lives
                while not self._stop.is_set() and self.client is not None:
                    time.sleep(0.25)
            except ObsClientError as exc:
                self.journal.append("reconnect-failed",
                                    {"error": str(exc),
                                     "attempt": attempt},
                                    source="mind.director")
                self.state.mark_disconnected()
                delay = RECONNECT_BACKOFF[min(attempt,
                                              len(RECONNECT_BACKOFF) - 1)]
                attempt += 1
                self._stop.wait(delay)
            finally:
                if self.client is not None and self._stop.is_set():
                    self.client.close()

    def disconnect_detected(self):
        """Called by the client layer when the session dies."""
        was_connected = self.state.connected()
        self.state.mark_disconnected()
        self.client = None
        if was_connected:
            self.fire_internal("disconnected", {})

    # -- event plumbing -----------------------------------------------------------

    def handle_event(self, event_type: str, data: dict):
        """Reader-thread entry point: enqueue and stay responsive."""
        if event_type == "__disconnected__":
            self.disconnect_detected()
            return
        self._tasks.put(("event", event_type, data))

    def _process_event(self, event_type: str, data: dict):
        mapped = self.state.apply_event(event_type, data)
        self.bus.publish(event_type, data)
        self.journal.append("event", {"eventType": event_type,
                                      "data": data,
                                      "stateMapped": bool(mapped)})
        self.run_flows(event_type, data)

    def fire_internal(self, trigger: str, data: dict):
        """Internal triggers (connected/disconnected), also queued."""
        self._tasks.put(("internal", trigger, data))

    def _fire_internal(self, trigger: str, data: dict):
        self.bus.publish(trigger, data)
        self.journal.append("event", {"eventType": trigger,
                                      "data": data,
                                      "stateMapped": False})
        for flow, steps in self.observe_rules(trigger, data):
            self.execute_flow(flow, steps)

    def observe_rules(self, event_type: str, data: dict):
        return observe(self.flows, event_type, data,
                       now=self._clock())

    def run_flows(self, event_type: str, data: dict):
        for flow, steps in self.observe_rules(event_type, data):
            self.execute_flow(flow, steps)

    def execute_flow(self, flow, steps: list):
        self.journal.append("flow-fired",
                            {"flow": flow.id, "steps": len(steps)},
                            source="mind.rules")
        for step in steps:
            ok, detail = self.executor.run_step(step, flow.id)
            if not ok:
                self.journal.append("action-failed",
                                    {"flow": flow.id,
                                     "error": detail},
                                    source="mind.rules")

    def seed_from_obs(self, client: ObsClient):
        try:
            listing = client.request("GetSceneList")
            preview = ""
            try:
                preview = str(client.request("GetCurrentPreviewScene")
                              .get("currentPreviewSceneName", ""))
            except ObsClientError:
                pass
            self.state.seed_scenes(listing.get("scenes", []),
                                   listing.get(
                                       "currentProgramSceneName", ""),
                                   preview)
            stream_status = client.request("GetStreamStatus")
            record_status = client.request("GetRecordStatus")
            self.state.seed_outputs(
                bool(stream_status.get("outputActive")),
                bool(record_status.get("outputActive")),
                bool(record_status.get("outputPaused")))
        except ObsClientError:
            pass  # partial seeding beats failing the session


# -- dress rehearsal -------------------------------------------------------

DEMO_FLOWS = [
    {"id": "brb-return", "on": "scene_changed",
     "when": {"scene_in": ["BRB"]}, "cooldown_s": 0,
     "then": [{"action": "switch_scene", "scene": "Live"}]},
    {"id": "rec-note", "on": "recording_started",
     "then": [{"action": "log", "message": "recording started"}]},
]

DEMO_SCENES = ["Starting Soon", "Live", "BRB"]


def run_demo(journal_path: "str | None" = None,
             password: "str | None" = "dress-rehearsal") -> dict:
    """Full-stack rehearsal: mock OBS over real sockets, auth included.

    Returns a report dict; `report["ok"]` is the gate verdict.
    """
    report = {"ok": True, "steps": []}

    def step(name, condition):
        ok = bool(condition)
        report["steps"].append({"step": name, "ok": ok})
        report["ok"] = report["ok"] and ok
        return ok

    tmp = tempfile.mkdtemp(prefix="mind-demo-")
    path = journal_path or (tmp + "/journal.jsonl")

    mock = MockObsServer(scenes=list(DEMO_SCENES), program="Starting Soon",
                         password=password)
    config = {
        "obs": {"host": "127.0.0.1", "port": mock.port,
                "password": password},
        "flows": [dict(f) for f in DEMO_FLOWS],
        # ephemeral dashboard: the default port may be owned by a live
        # organ and the rehearsal must never fight a real service
        "dashboard": {"port": 0},
    }
    director = Director(config, journal_path=path)
    sse_sock = None
    try:
        client = director.connect_once()
        step("handshake-with-auth", client.negotiated_rpc_version == 1)
        snap = director.state.snapshot()
        step("seed-scenes", snap["scenes"] == DEMO_SCENES)
        step("seed-program", snap["program_scene"] == "Starting Soon")

        director.start_server()
        with urllib.request.urlopen(director.server.url + "/api/status",
                                    timeout=5) as resp:
            api = json.loads(resp.read().decode())
        step("status-api-live", api["program_scene"] == "Starting Soon")

        # SSE subscriber joins before the show starts
        sse_sock = open_sse(director.server.url + "/api/events")

        # drive the production: record -> BRB scene -> auto-return
        mock.script_record(True)
        step("rules-recording-note",
             wait_until(lambda: any(
                 r["kind"] == "action" and
                 r["data"].get("step", {}).get("action") == "log"
                 for r in director.journal.replay())))
        mock.script_scene_change("BRB")
        step("flow-auto-return",
             wait_until(lambda: director.state.program_scene() == "Live"))
        step("obs-saw-switch",
             wait_until(lambda: "SetCurrentProgramScene"
                        in mock.request_log))
        step("sse-push-delivered", read_sse_until(
            sse_sock, "event: CurrentProgramSceneChanged", timeout=5.0))

        # operator overrides through the control plane
        req = urllib.request.Request(
            director.server.url + "/api/scene",
            data=json.dumps({"sceneName": "Starting Soon"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            posted = json.loads(resp.read().decode())
        step("dashboard-scene-post", posted.get("ok") is True)
        step("dashboard-scene-applied",
             wait_until(lambda: director.state.program_scene()
                        == "Starting Soon"))

        records = director.journal.replay()
        kinds = [r["kind"] for r in records]
        step("journal-sequence-clean", kinds.count("event") >= 3 and
             all(r["seq"] > 0 for r in records))
        step("flow-journaled", "flow-fired" in kinds)
    finally:
        if sse_sock is not None:
            try:
                sse_sock.close()
            except OSError:
                pass
        director.stop()
        mock.stop()
    return report


def open_sse(url: str):
    parsed = urllib.parse.urlsplit(url)
    sock = socket.create_connection((parsed.hostname, parsed.port),
                                    timeout=5.0)
    sock.settimeout(8.0)
    request = (f"GET {parsed.path} HTTP/1.1\r\n"
               f"Host: {parsed.hostname}:{parsed.port}\r\n"
               "Accept: text/event-stream\r\n\r\n")
    sock.sendall(request.encode())
    return sock


def read_sse_until(sock, marker: str, timeout: float = 5.0) -> bool:
    buffer = b""
    sock.settimeout(timeout)
    try:
        while marker.encode() not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                return False
            buffer += chunk
    except (OSError, socket.timeout):
        return False
    return True


def selftest() -> int:
    failures = []

    def check(name, fn):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")

    def t_config_errors_surface():
        try:
            Director({"flows": [{"id": "", "on": "wat", "then": []}]})
            raise AssertionError("bad flows accepted")
        except RulesConfigError:
            pass

    def t_rehearsal():
        report = run_demo()
        for entry in report["steps"]:
            print(f"  rehearsal {entry['step']}: "
                  f"{'ok' if entry['ok'] else 'FAILED'}")
        assert report["ok"], f"rehearsal failed: {report}"

    check("config-errors-surface", t_config_errors_surface)
    check("full-dress-rehearsal", t_rehearsal)

    print(f"director selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
