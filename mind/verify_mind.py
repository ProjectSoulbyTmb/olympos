"""MIND verify gate - proves the stream director end to end.

Sections:
    1. module selftests   wire/auth/protocol/state/rules/journal/bus
    2. dress rehearsal    full stack vs mock OBS over real sockets
                          (handshake+auth, seeding, rules firing,
                           SSE push, control-plane POST, journal)
    3. auth discipline    wrong password is rejected, right one lands
    4. dry-run contract   planned flows never touch the peer
    5. http surface       dashboard/overlays served, bad input rejected

Run: python mind/verify_mind.py   (exit 0 = green, 1 = any failure)
"""

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mind import auth as auth_mod                     # noqa: E402
from mind import bus as bus_mod                       # noqa: E402
from mind import journal as journal_mod               # noqa: E402
from mind import protocol as protocol_mod             # noqa: E402
from mind import rules as rules_mod                   # noqa: E402
from mind import state as state_mod                   # noqa: E402
from mind import wire as wire_mod                     # noqa: E402
from mind.client import ObsClient, ObsClientError     # noqa: E402
from mind.director import Director, run_demo          # noqa: E402
from mind.mockobs import MockObsServer                # noqa: E402

FAILURES = []


def check(name, fn):
    try:
        fn()
        print(f"PASS {name}")
        return True
    except AssertionError as exc:
        FAILURES.append(name)
        print(f"FAIL {name}: {exc}")
        return False
    except Exception as exc:  # crashing a gate section is failing it
        FAILURES.append(name)
        print(f"FAIL {name}: crashed: {exc!r}")
        return False


def section_module_selftests():
    suites = (
        ("wire-codec", wire_mod.selftest),
        ("auth-vectors", auth_mod.selftest),
        ("protocol-envelopes", protocol_mod.selftest),
        ("state-machine", state_mod.selftest),
        ("rules-engine", rules_mod.selftest),
        ("journal-ledger", journal_mod.selftest),
        ("bus-fanout", bus_mod.selftest),
    )
    for name, suite in suites:
        check(name, lambda s=suite: s())


def section_dress_rehearsal():
    def t_rehearsal():
        report = run_demo()
        assert report["ok"], f"rehearsal verdict failed: {report}"
        names = [s["step"] for s in report["steps"]]
        expected = ("handshake-with-auth", "seed-scenes", "seed-program",
                    "status-api-live", "rules-recording-note",
                    "flow-auto-return", "obs-saw-switch",
                    "sse-push-delivered", "dashboard-scene-post",
                    "dashboard-scene-applied", "journal-sequence-clean",
                    "flow-journaled")
        for step_name in expected:
            assert step_name in names, f"rehearsal skipped {step_name}"
    check("end-to-end-dress-rehearsal", t_rehearsal)


def _connect(port, password, events=None):
    client = ObsClient("127.0.0.1", port, password=password,
                       on_event=events)
    client.connect()
    return client


def section_auth_discipline():
    def t_wrong_password_rejected():
        mock = MockObsServer(scenes=["A"], program="A",
                             password="real-secret")
        try:
            try:
                bad = _connect(mock.port, "wrong-guess")
                bad.close()
                raise AssertionError("wrong password accepted")
            except ObsClientError:
                pass  # exactly what we want
            # peer must still serve a well-authenticated session
            good = _connect(mock.port, "real-secret")
            listing = good.request("GetSceneList")
            assert listing["currentProgramSceneName"] == "A"
            good.close()
        finally:
            mock.stop()
    check("wrong-password-rejected-peer-survives",
          t_wrong_password_rejected)


def section_dry_run_contract():
    def t_dry_run_touches_nothing():
        mock = MockObsServer(scenes=["A", "B"], program="A")
        try:
            config = {
                "obs": {"host": "127.0.0.1", "port": mock.port,
                        "password": ""},
                "flows": [
                    {"id": "flip", "on": "scene_changed",
                     "then": [{"action": "switch_scene",
                               "scene": "B"}]},
                ],
                # never fight a live organ for the default dashboard port
                "dashboard": {"port": 0},
            }
            director = Director(config, dry_run=True)
            director.connect_once()
            mock.script_scene_change("B")   # would trigger flip
            time.sleep(0.3)                 # let any damage happen
            # dry-run must NOT have switched anything back
            with mock._lock:
                assert mock.program == "B", \
                    "dry-run executed a side effect"
            assert director.executor.status_note() == "dry-run"
            director.stop()
        finally:
            mock.stop()
    check("dry-run-no-side-effects", t_dry_run_touches_nothing)


def section_http_surface():
    def t_pages_and_validation():
        from mind.bus import Bus
        from mind.server import MindServer

        snapshot = {"connected": False, "program_scene": "X",
                    "preview_scene": "", "scenes": ["X"],
                    "streaming": False, "recording": False,
                    "recording_paused": False, "muted_inputs": [],
                    "studio_mode": False}
        calls = []

        def controller(action, payload):
            calls.append((action, payload))
            return True, {}

        server = MindServer(state_provider=lambda: dict(snapshot),
                            bus=Bus(), controller=controller, port=0)
        server.start()
        try:
            base = server.url

            def get_text(path):
                with urllib.request.urlopen(base + path,
                                            timeout=5) as resp:
                    return resp.read().decode()

            page = get_text("/")
            for marker in ("MIND", "/api/status", "/api/events"):
                assert marker in page, f"dashboard missing {marker}"

            status = json.loads(get_text("/api/status"))
            assert status["program_scene"] == "X"

            assert "PROGRAM" in get_text("/overlay/tally")
            assert "#00:05:00" in get_text("/overlay/timer")

            try:
                urllib.request.urlopen(base + "/nope", timeout=5)
                raise AssertionError("404 route answered 200")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404

            def post(path, body):
                req = urllib.request.Request(
                    base + path, data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return json.loads(resp.read().decode())

            ok = post("/api/scene", {"sceneName": "Y"})
            assert ok["ok"] is True
            assert calls[-1] == ("switch_scene",
                                 {"sceneName": "Y"}), calls[-1]
            bad = post("/api/recording", {"state": "pause"})
            assert bad["ok"] is False, "invalid state must be refused"
        finally:
            server.stop()
    check("http-pages-and-validation", t_pages_and_validation)

    def t_sse_stream_pushes():
        from mind.bus import Bus
        from mind.server import MindServer
        server = MindServer(state_provider=lambda: {}, bus=Bus(),
                            port=0)
        server.start()
        sock = None
        try:
            parsed = urllib.parse.urlsplit(server.url)
            sock = socket.create_connection(
                (parsed.hostname, parsed.port), timeout=5)
            sock.settimeout(5.0)
            sock.sendall(
                f"GET /api/events HTTP/1.1\r\nHost: localhost\r\n"
                "Accept: text/event-stream\r\n\r\n".encode())
            # headers are flushed only AFTER the subscriber registers,
            # so end-of-headers is the deterministic "subscribed" barrier
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                head += chunk
            assert head.startswith(b"HTTP/1.1 200"), head[:120]
            server.bus.publish("recording_started",
                               {"outputActive": True})
            buffer = head
            while b"event: recording_started" not in buffer:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
            assert b"event: recording_started" in buffer, \
                f"SSE push missing: {buffer[:200]!r}"
            assert b"data:" in buffer
        finally:
            if sock is not None:
                sock.close()
            server.stop()
    check("sse-push-stream", t_sse_stream_pushes)


def main() -> int:
    print("verify_mind - MIND stream-director gate")
    section_module_selftests()
    section_dress_rehearsal()
    section_auth_discipline()
    section_dry_run_contract()
    section_http_surface()

    if FAILURES:
        print(f"verify_mind: RED ({len(FAILURES)} failures): "
              + ", ".join(FAILURES))
        return 1
    print("verify_mind: GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
