"""MIND client - obs-websocket v5 connection to a real (or mock) OBS.

Handshake, optional challenge/response auth, request/response calls,
and an event pump that feeds the director's snapshot.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import queue
import threading
import uuid

from . import obswire
from .obswire import WireConn, WireError

OP_IDENTIFIED = 3
OP_EVENT = 5
OP_REQUEST = 6
OP_REQUEST_RESPONSE = 7


class ObsClientError(Exception):
    pass


def _auth_secret(password: str, salt: str) -> str:
    return base64.b64encode(hashlib.sha256(
        (password + salt).encode("utf-8")).digest()).decode("ascii")


def _auth_proof(secret: str, challenge: str) -> str:
    return base64.b64encode(hmac.new(
        secret.encode("ascii"), challenge.encode("ascii"),
        hashlib.sha256).digest()).decode("ascii")


class ObsClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 4455,
                 password: str = "", timeout: float = 5.0):
        self.host = host
        self.port = int(port)
        self.password = password or ""
        self.timeout = float(timeout)
        self.conn: "WireConn | None" = None
        self.obs_version = None
        self._pending = {}          # requestId -> queue.Queue(1)
        self._events = queue.Queue(maxsize=512)
        self._lock = threading.Lock()
        self._closed = threading.Event()

    @property
    def connected(self) -> bool:
        return self.conn is not None and not self._closed.is_set()

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> dict:
        """Connect + identify; returns hello info. Raises on failure."""
        if self.connected:
            raise ObsClientError("already connected")
        try:
            conn = WireConn.open(self.host, self.port,
                                 timeout=self.timeout)
        except OSError as exc:
            raise ObsClientError(
                f"cannot reach {self.host}:{self.port}: {exc}") from exc
        try:
            hello = self._read_message(conn)
            if hello.get("op") != 0:
                raise ObsClientError("expected hello frame")
            info = hello["d"]
            identify = {"rpcVersion": 1}
            block = info.get("authentication")
            if block:
                identify["authentication"] = _auth_proof(
                    _auth_secret(self.password, block["salt"]),
                    block["challenge"])
            conn.send_text(json.dumps({"op": 1, "d": identify}))
            reply = self._read_message(conn)
            if reply is None:
                raise ObsClientError("connection closed during identify")
            if reply.get("op") != OP_IDENTIFIED:
                raise ObsClientError(
                    f"identify rejected: op={reply.get('op')}")
            self.obs_version = info.get("obsWebSocketVersion")
            self.conn = conn
            self._closed.clear()
            threading.Thread(target=self._pump, daemon=True,
                             name="mind-obs-reader").start()
            return info
        except Exception:
            conn.close()
            raise

    def close(self):
        conn, self.conn = self.conn, None
        self._closed.set()
        if conn is not None:
            conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    # -- requests -------------------------------------------------------------

    def call(self, request_type: str, data: dict = None) -> dict:
        """Send a request; return responseData. Raises on failure."""
        if not self.connected:
            raise ObsClientError("not connected")
        request_id = uuid.uuid4().hex[:12]
        slot = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[request_id] = slot
        payload = json.dumps({"op": OP_REQUEST, "d": {
            "requestType": request_type,
            "requestId": request_id,
            **({"requestData": data} if data else {})}})
        try:
            self.conn.send_text(payload)
        except (OSError, WireError) as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise ObsClientError(f"send failed: {exc}") from exc
        try:
            response = slot.get(timeout=self.timeout)
        except queue.Empty:
            with self._lock:
                self._pending.pop(request_id, None)
            raise ObsClientError(f"timeout waiting for {request_type}")
        status = response.get("requestStatus") or {}
        if not status.get("result"):
            raise ObsClientError(
                f"{request_type} failed "
                f"(code {status.get('code')})")
        return response.get("responseData") or {}

    def poll(self, timeout: float = None):
        """Next (eventType, eventData) or None after timeout."""
        try:
            return self._events.get(
                timeout=self.timeout if timeout is None else timeout)
        except queue.Empty:
            return None

    # -- internals ---------------------------------------------------------------

    def _read_message(self, conn) -> dict:
        raw = conn.recv_message()
        if raw is None:
            raise ObsClientError("connection closed by peer")
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ObsClientError(f"bad json from peer: {exc}") from exc
        if not isinstance(message, dict) or "op" not in message:
            raise ObsClientError("malformed protocol frame")
        return message

    def _pump(self):
        while not self._closed.is_set() and self.conn is not None:
            try:
                message = self._read_message(self.conn)
            except (ObsClientError, OSError, WireError):
                break
            op, data = message.get("op"), message.get("d") or {}
            if op == OP_EVENT:
                try:
                    self._events.put_nowait(
                        (data.get("eventType"),
                         data.get("eventData") or {}))
                except queue.Full:
                    pass
            elif op == OP_REQUEST_RESPONSE:
                request_id = data.get("requestId")
                with self._lock:
                    slot = self._pending.pop(request_id, None)
                if slot is not None:
                    try:
                        slot.put_nowait(data)
                    except queue.Full:
                        pass
        self._closed.set()


def selftest() -> int:
    """End-to-end against the bundled mock OBS."""
    from .mockobs import MockObsServer
    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL client.{name}")
            failures.append(name)

    server = MockObsServer(password="sesame")
    server.start()
    try:
        check("refuses-wrong-password", _fails_connect(
            "127.0.0.1", server.port, "wrong"))
        client = ObsClient("127.0.0.1", server.port, password="sesame")
        info = client.connect()
        check("identified-with-password",
              client.connected and info.get("rpcVersion") == 1)

        version = client.call("GetVersion")
        check("get-version", "obsWebSocketVersion" in version)

        scenes = client.call("GetSceneList")
        check("scene-list",
              scenes["currentProgramSceneName"] == "Live"
              and len(scenes["scenes"]) == 3)

        client.call("SetCurrentProgramScene", {"sceneName": "BRB"})
        event = client.poll(timeout=2.0)
        check("event-pumped",
              event is not None
              and event[0] == "CurrentProgramSceneChanged"
              and event[1]["sceneName"] == "BRB")

        check("unknown-request-raises",
              _raises(lambda: client.call("No.Such.Request")))
        check("call-while-closed-raises",
              _raises(lambda: ObsClient("127.0.0.1",
                                        server.port).call("GetVersion")))

        client.call("StartStream")
        kinds = []
        while True:
            got = client.poll(timeout=1.0)
            if got is None:
                break
            kinds.append(got[0])
        check("stream-event-flows", "StreamStateChanged" in kinds)
        client.close()
        check("closed-flag", client.connected is False)
    finally:
        server.stop()

    dead = ObsClient("127.0.0.1", 1, timeout=1.0)
    check("unreachable-host-raises",
          _raises(dead.connect))
    print(f"client selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


def _fails_connect(host, port, password):
    client = ObsClient(host, port, password=password, timeout=3.0)
    try:
        client.connect()
        client.close()
        return False
    except ObsClientError:
        return client.conn is None if hasattr(client, "sock") \
            else client.conn is None


def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


if __name__ == "__main__":
    raise SystemExit(selftest())
