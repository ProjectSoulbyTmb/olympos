"""MIND mockobs - an in-process obs-websocket v5 peer for rehearsals.

A scripted stand-in for OBS Studio: performs the real WebSocket
upgrade over real sockets, runs the real Hello/Identify handshake
(including password auth), answers the requests MIND makes, and emits
real protocol events when its production is driven.

This is how network organs in this fleet stay testable without external
services - the gate exercises the whole stack, not a stub beside it.

Run: python mind/mockobs.py   (self-test, exit 0 = peer sane)
"""

from __future__ import annotations

import base64
import json
import os
import socket
import threading

from . import wire
from .auth import respond_to_hello
from .protocol import (
    OP_HELLO,
    OP_IDENTIFIED,
    make_event,
    make_response,
    parse_request,
)


class MockObsServer:
    """Scripted OBS Studio. `password=None` means an open server."""

    def __init__(self, scenes=None, program="Scene A",
                 password: "str | None" = None):
        self.scenes = [str(s) for s in (scenes or ["Scene A", "Scene B"])]
        self.program = program if program in self.scenes else self.scenes[0]
        self.preview = self.scenes[-1] if len(self.scenes) > 1 else program
        self.password = password
        self.streaming = False
        self.recording = False
        self.recording_paused = False
        self._lock = threading.Lock()
        self._clients = {}  # name -> WsConnection
        self._counter = 0
        self._challenge = base64.b64encode(os.urandom(16)).decode()
        self._salt = base64.b64encode(os.urandom(16)).decode()
        self.event_log = []  # every event this peer emitted
        self.request_log = []

        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET,
                                  socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        # without listen() the OS refuses every dial while accept()
        # sits silent - the suite hangs in a rehearsal that never was
        self._listener.listen(4)
        self._listener.settimeout(0.2)
        self.port = self._listener.getsockname()[1]
        self._stop = threading.Event()
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    # -- lifecycle -----------------------------------------------------

    def stop(self):
        self._stop.set()
        try:
            self._listener.close()
        except OSError:
            pass
        with self._lock:
            conns = list(self._clients.values())
            self._clients.clear()
        for conn in conns:
            try:
                conn.sock.close()
            except OSError:
                pass
        self._accept_thread.join(timeout=2.0)

    def _next_client_name(self) -> str:
        with self._lock:
            self._counter += 1
            return f"client-{self._counter}"

    # -- accept / identify ----------------------------------------------

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                sock, addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            # generous ceiling only; stop() closes sockets to unblock
            sock.settimeout(30.0)
            threading.Thread(target=self._serve_client,
                             args=(sock,), daemon=True).start()

    def _serve_client(self, sock: socket.socket):
        name = None
        conn = None
        try:
            raw = b""
            while b"\r\n\r\n" not in raw:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                raw += chunk
                if len(raw) > 65536:
                    return
            head, _, rest = raw.partition(b"\r\n\r\n")
            key = wire.parse_client_upgrade(head.decode("latin-1"))
            sock.sendall(wire.server_accept_response(key))
            conn = wire.WsConnection(sock, mask_outgoing=False)
            if rest:  # pipeline abuse: peer spoke before upgrading
                return

            hello_payload = {
                "obsWebSocketVersion": "mock-5.4.0",
                "rpcVersion": 1,
            }
            if self.password:
                hello_payload["authentication"] = {
                    "challenge": self._challenge,
                    "salt": self._salt,
                }
            conn.send_text(json.dumps(
                {"op": OP_HELLO, "d": hello_payload}))

            opcode, payload = conn.receive_message()
            message = json.loads(payload.decode("utf-8"))
            if message.get("op") != 2:  # Identify
                return
            ident = message.get("d") or {}
            if self.password:
                expected = respond_to_hello(
                    {"challenge": self._challenge, "salt": self._salt},
                    self.password)
                if ident.get("authentication") != expected:
                    conn.send_close(code=4009)  # auth failed, v5 code
                    return
            name = self._next_client_name()
            with self._lock:
                self._clients[name] = conn
            conn.send_text(json.dumps(
                {"op": OP_IDENTIFIED,
                 "d": {"negotiatedRpcVersion": 1}}))

            self._request_loop(conn)
        except (OSError, wire.WireError, wire.ConnectionClosed, ValueError):
            pass
        finally:
            if name:
                with self._lock:
                    self._clients.pop(name, None)
            try:
                sock.close()
            except OSError:
                pass

    def _request_loop(self, conn: wire.WsConnection):
        while True:
            opcode, payload = conn.receive_message()
            if opcode != wire.OP_TEXT:
                continue
            envelope = json.loads(payload.decode("utf-8"))
            if envelope.get("op") != 6:  # Request
                continue
            request_type, request_id, request_data = parse_request(
                envelope.get("d") or {})
            ok, response = self._handle(request_type, request_data)
            reply = make_response(request_type, request_id, result=ok,
                                  response_data=response or {})
            conn.send_text(json.dumps(reply))

    # -- request handling -------------------------------------------------

    def _handle(self, request_type: str, data: dict):
        with self._lock:
            self.request_log.append(request_type)
        handler = getattr(self, f"_req_{request_type}", None)
        if handler is None:
            return False, {}
        try:
            return handler(data)
        except (KeyError, ValueError):
            return False, {}

    def _req_GetVersion(self, data):
        return True, {"obsVersion": "31.0.0", "rpcVersion": 1,
                      "obsWebSocketVersion": "mock-5.4.0"}

    def _req_GetSceneList(self, data):
        with self._lock:
            scenes = [{"sceneIndex": i, "sceneName": s}
                      for i, s in enumerate(self.scenes)]
            return True, {"scenes": scenes,
                          "currentProgramSceneName": self.program}

    def _req_GetCurrentProgramScene(self, data):
        with self._lock:
            return True, {"currentProgramSceneName": self.program}

    def _req_SetCurrentProgramScene(self, data):
        scene = str(data.get("sceneName", ""))
        with self._lock:
            if scene not in self.scenes:
                return False, {}
            changed = scene != self.program
            self.program = scene
        if changed:
            self.emit("CurrentProgramSceneChanged", {"sceneName": scene})
        return True, {}

    def _req_GetCurrentPreviewScene(self, data):
        with self._lock:
            return True, {"currentPreviewSceneName": self.preview}

    def _req_SetCurrentPreviewScene(self, data):
        scene = str(data.get("sceneName", ""))
        with self._lock:
            if scene not in self.scenes:
                return False, {}
            self.preview = scene
        self.emit("CurrentPreviewSceneChanged", {"sceneName": scene})
        return True, {}

    def _req_GetStreamStatus(self, data):
        with self._lock:
            return True, {"outputActive": self.streaming,
                          "outputReconnecting": False}

    def _req_StartStream(self, data):
        return self._set_streaming(True)

    def _req_StopStream(self, data):
        return self._set_streaming(False)

    def _set_streaming(self, active: bool):
        with self._lock:
            changed = active != self.streaming
            self.streaming = active
        if changed:
            self.emit("StreamStateChanged", {"outputActive": active})
        return True, {}

    def _req_GetRecordStatus(self, data):
        with self._lock:
            return True, {"outputActive": self.recording,
                          "outputPaused": self.recording_paused}

    def _req_StartRecord(self, data):
        return self._set_recording(True, False)

    def _req_StopRecord(self, data):
        return self._set_recording(False, False)

    def _set_recording(self, active: bool, paused: bool):
        with self._lock:
            changed = active != self.recording
            self.recording = active
            self.recording_paused = paused
        if changed:
            self.emit("RecordStateChanged",
                      {"outputActive": active, "outputPaused": paused})
        return True, {}

    # -- scripting interface (tests + demo drive the production here) ----

    def script_scene_change(self, scene: str):
        with self._lock:
            if scene not in self.scenes:
                raise ValueError(f"unknown scene {scene!r}")
            self.program = scene
        self.emit("CurrentProgramSceneChanged", {"sceneName": scene})

    def script_stream(self, active: bool):
        self._set_streaming(active)

    def script_record(self, active: bool):
        self._set_recording(active, False)

    def emit(self, event_type: str, data: dict):
        envelope = make_event(event_type, data)
        with self._lock:
            self.event_log.append((event_type, dict(data)))
            targets = list(self._clients.values())
        text = json.dumps(envelope)
        for conn in targets:
            try:
                conn.send_text(text)
            except OSError:
                pass


def selftest() -> int:
    failures = []

    def check(name, fn):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")

    def t_scripting_surface():
        server = MockObsServer(scenes=["A", "B"], program="A")
        try:
            assert isinstance(server.port, int) and server.port > 0
            server.script_stream(True)
            with server._lock:
                assert server.streaming is True
            server.script_scene_change("B")
            types = [event for event, _ in server.event_log]
            assert "StreamStateChanged" in types
            assert "CurrentProgramSceneChanged" in types
            try:
                server.script_scene_change("ghost")
                raise AssertionError("unknown scene accepted")
            except ValueError:
                pass
        finally:
            server.stop()

    check("scripting-surface", t_scripting_surface)

    print(f"mockobs selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
