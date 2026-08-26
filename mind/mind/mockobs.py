"""MIND mock OBS - a fake OBS Studio for rehearsals and gates.

Implements just enough of obs-websocket v5 on a raw TCP socket:
hello/identify (with optional password auth), the requests MIND uses,
and real event emission when state mutates. The demo and the test
suite run against this instead of a live OBS instance.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import socket
import threading

from . import obswire


class MockObsError(Exception):
    pass


class MockObsServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0,
                 password: str = "",
                 scenes=("Live", "BRB", "Starting Soon"),
                 program="Live", preview="BRB",
                 streaming=False, recording=False):
        self.host = host
        self._port = int(port)
        self.password = password
        self.scenes = list(scenes)
        self.program = program
        self.preview = preview
        self.streaming = streaming
        self.recording = recording
        self.event_log = []
        self.version = "mock-obs/5.0"

        self._state_lock = threading.Lock()
        self._clients = []           # list[_Client]
        self._clients_lock = threading.Lock()
        self._server_sock = None
        self._accept_thread = None
        self._stopping = threading.Event()

    # -- lifecycle ---------------------------------------------------------

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/"

    def start(self):
        self._server_sock = socket.socket(socket.AF_INET,
                                          socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET,
                                     socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self._port))
        self._port = self._server_sock.getsockname()[1]
        self._server_sock.listen(8)
        self._accept_thread = threading.Thread(target=self._accept_loop,
                                               daemon=True,
                                               name="mind-mockobs-accept")
        self._accept_thread.start()

    def stop(self):
        self._stopping.set()
        sock, self._server_sock = self._server_sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        with self._clients_lock:
            clients, self._clients = list(self._clients), []
        for client in clients:
            client.kill()

    # -- introspection -------------------------------------------------------

    def snapshot_state(self) -> dict:
        with self._state_lock:
            return {"scenes": list(self.scenes),
                    "program": self.program,
                    "preview": self.preview,
                    "streaming": self.streaming,
                    "recording": self.recording}

    def wait_for_event(self, event_type: str, timeout: float = 5.0):
        deadline = _monotonic() + timeout
        while _monotonic() < deadline:
            with self._state_lock:
                for kind, data in self.event_log:
                    if kind == event_type:
                        return data
            threading.Event().wait(0.02)
        return None

    # -- connection handling ---------------------------------------------------

    def _accept_loop(self):
        while not self._stopping.is_set():
            try:
                sock, addr = self._server_sock.accept()
            except OSError:
                break
            client = _Client(self, sock, addr)
            with self._clients_lock:
                self._clients.append(client)
            threading.Thread(target=client.serve, daemon=True,
                             name="mind-mockobs-client").start()

    def _drop(self, client):
        with self._clients_lock:
            if client in self._clients:
                self._clients.remove(client)

    # -- protocol -----------------------------------------------------------------

    def _hello_payload(self) -> dict:
        hello = {"obsWebSocketVersion": self.version, "rpcVersion": 1}
        if self.password:
            hello["authentication"] = {
                "challenge": base64.b64encode(
                    secrets.token_bytes(16)).decode(),
                "salt": base64.b64encode(
                    secrets.token_bytes(16)).decode()}
        return hello

    def _check_auth(self, hello: dict, provided: str) -> bool:
        block = hello.get("authentication")
        if not block:
            return True
        secret = base64.b64encode(hashlib.sha256(
            (self.password + block["salt"]).encode("utf-8")).digest()
        ).decode("ascii")
        expected = base64.b64encode(hmac.new(
            secret.encode("ascii"), block["challenge"].encode("ascii"),
            hashlib.sha256).digest()).decode("ascii")
        return hmac.compare_digest(expected, provided or "")

    def _handle_request(self, request_type: str, data: dict):
        """Mutate state; return (responseData, emitted_event_or_None)."""
        with self._state_lock:
            if request_type == "GetVersion":
                return {"obsWebSocketVersion": self.version,
                        "rpcVersion": 1}, None
            if request_type == "GetSceneList":
                return {"scenes":
                        [{"sceneName": s} for s in self.scenes],
                        "currentProgramSceneName": self.program,
                        "currentPreviewSceneName": self.preview}, None
            if request_type == "GetCurrentProgramScene":
                return {"currentProgramSceneName": self.program}, None
            if request_type == "GetCurrentPreviewScene":
                return {"currentPreviewSceneName": self.preview}, None
            if request_type == "GetStreamStatus":
                return {"outputActive": self.streaming}, None
            if request_type == "GetRecordStatus":
                return {"outputActive": self.recording}, None
            if request_type == "SetCurrentProgramScene":
                name = (data or {}).get("sceneName")
                if name not in self.scenes:
                    return {}, ("error", f"no scene {name!r}")
                self.program = name
                return {"sceneName": name}, (
                    "CurrentProgramSceneChanged", {"sceneName": name})
            if request_type in ("StartStream", "StopStream"):
                active = request_type == "StartStream"
                self.streaming = active
                return {"outputActive": active}, (
                    "StreamStateChanged", {"outputActive": active})
            if request_type in ("StartRecord", "StopRecord"):
                active = request_type == "StartRecord"
                self.recording = active
                return {"outputActive": active}, (
                    "RecordStateChanged", {"outputActive": active})
            return {}, ("error", f"unknown request {request_type}")

    def _broadcast(self, event_type: str, data: dict):
        with self._state_lock:
            self.event_log.append((event_type, dict(data)))
        message = json.dumps({"op": 5, "d": {
            "eventType": event_type, "eventData": dict(data)}})
        with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            client.push(message)


class _Client:
    def __init__(self, server: MockObsServer, sock: socket.socket, addr):
        self.server = server
        self.sock = sock
        self.conn = None
        self.addr = addr
        self.alive = True
        self._send_lock = threading.Lock()
        self.hello = None

    def push(self, text: str):
        with self._send_lock:
            try:
                self.conn.send_text(text)
            except (OSError, obswire.WireError, AttributeError):
                self.alive = False

    def kill(self):
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass

    def serve(self):
        try:
            key, leftover = _upgrade(self.sock)
            self.conn = obswire.WireConn(self.sock, leftover)
            self.hello = {"op": 0, "d": self.server._hello_payload()}
            with self._send_lock:
                self.conn.send_text(json.dumps(self.hello))
            while self.alive:
                raw = self.conn.recv_message()
                if raw is None:
                    break
                self._dispatch(raw)
        except (obswire.WireError, OSError, ValueError,
                MockObsError):
            pass
        finally:
            self.server._drop(self)
            self.kill()

    def _dispatch(self, raw: str):
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        op, data = message.get("op"), message.get("d") or {}

        if op == 1:  # identify
            ok = self.server._check_auth(
                self.hello["d"], data.get("authentication") or "")
            if not ok:
                with self._send_lock:
                    self.sock.sendall(obswire.encode_frame(b"", 0x8))
                self.alive = False
                return
            self.push(json.dumps(
                {"op": 3, "d": {"negotiatedRpcVersion": 1}}))

        elif op == 6:  # request
            request_type = data.get("requestType", "")
            request_id = data.get("requestId", "")
            response_data, emitted = self.server._handle_request(
                request_type, data.get("requestData"))
            if emitted and emitted[0] == "error":
                status = {"result": False, "code": 204}
                response_data = {}
            else:
                status = {"result": True, "code": 100}
            self.push(json.dumps({"op": 7, "d": {
                "requestType": request_type,
                "requestId": request_id,
                "requestStatus": status,
                "responseData": response_data}}))
            if emitted and emitted[0] != "error":
                self.server._broadcast(emitted[0], emitted[1])


def _upgrade(sock: socket.socket):
    """Parse the HTTP upgrade; return (client_key, leftover_bytes)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise MockObsError("closed during upgrade")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    if len(lines) < 1 or not lines[0].upper().startswith("GET"):
        raise MockObsError("not a GET request")

    def header_value(name):
        want = name.lower()
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip().lower() == want:
                    return v.strip()
        return ""

    if "websocket" not in header_value("Upgrade").lower():
        raise MockObsError("missing upgrade header")
    key = header_value("Sec-WebSocket-Key")
    if not key:
        raise MockObsError("missing websocket key")
    accept = obswire.accept_key(key)
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n")
    sock.sendall(response.encode("latin-1"))
    return key, rest


def _monotonic():
    import time
    return time.monotonic()


def selftest() -> int:
    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL mockobs.{name}")
            failures.append(name)

    srv = MockObsServer(scenes=["Live", "BRB"])
    srv.start()
    try:
        check("bound-ephemeral-port", srv.port > 0)
        data, emitted = srv._handle_request(
            "GetSceneList", {})
        check("scene-list-shape",
              data["scenes"] == [{"sceneName": "Live"},
                                 {"sceneName": "BRB"}])
        _, emitted = srv._handle_request(
            "SetCurrentProgramScene", {"sceneName": "Live"})
        check("switch-emits-event",
              emitted[0] == "CurrentProgramSceneChanged")
        _, emitted = srv._handle_request("Bogus.Request", {})
        check("unknown-request-errors", emitted[0] == "error")
        open_srv = MockObsServer(password="")
        check("open-hello-unauthenticated",
              "authentication" not in open_srv._hello_payload())
        locked_srv = MockObsServer(password="pw")
        check("locked-hello-challenges",
              "authentication" in locked_srv._hello_payload())
        good_hello = locked_srv._hello_payload()
        check("auth-verifies-right-password",
              locked_srv._check_auth(good_hello, _forge(
                  locked_srv.password, good_hello["authentication"])))
        check("auth-rejects-wrong-password",
              locked_srv._check_auth(good_hello, "bad==") is False)
    finally:
        srv.stop()
    print(f"mockobs selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


def _forge(password: str, block: dict) -> str:
    secret = base64.b64encode(hashlib.sha256(
        (password + block["salt"]).encode("utf-8")).digest()).decode()
    return base64.b64encode(hmac.new(
        secret.encode(), block["challenge"].encode(),
        hashlib.sha256).digest()).decode()


if __name__ == "__main__":
    raise SystemExit(selftest())
