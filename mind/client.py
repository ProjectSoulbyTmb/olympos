"""MIND client - obs-websocket v5 session over the MIND wire layer.

One connect performs: TCP -> WebSocket upgrade -> Hello -> Identify
(challenge/response when required) -> Identified. Requests are
correlated by requestId against pending futures; events stream to the
registered callback. A supervisor (director) owns reconnection policy;
this class stays single-session for testability.

Run: python mind/client.py   (self-test needs a peer; see verify gate)
"""

from __future__ import annotations

import itertools
import json
import socket
import threading

from . import wire
from .auth import respond_to_hello
from .protocol import (
    OP_EVENT,
    OP_HELLO,
    OP_IDENTIFIED,
    OP_REQUEST_RESPONSE,
    EventSubscription,
    ProtocolError,
    make_identify,
    make_request,
    parse_event,
    parse_message,
    parse_response,
)

DEFAULT_TIMEOUT = 5.0


class ObsClientError(Exception):
    """Session-level failure (connect, auth, protocol)."""


class RequestTimeout(ObsClientError):
    """No RequestResponse within the timeout window."""


class ObsClient:
    def __init__(self, host: str, port: int, password: str = "",
                 on_event=None, subscriptions: int = EventSubscription.ALL,
                 timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = int(port)
        self.password = password or ""
        self.on_event = on_event  # callable(event_type, data)
        self.subscriptions = int(subscriptions)
        self.timeout = float(timeout)

        self._sock = None
        self._conn = None
        self._reader = None
        self._closing = threading.Event()
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._ids = itertools.count(1)
        self.negotiated_rpc_version = None
        self.obs_version = ""

    # -- session ---------------------------------------------------------

    def connect(self):
        """Perform the full v5 opening handshake. Raises on failure."""
        try:
            sock = socket.create_connection((self.host, self.port),
                                            timeout=self.timeout)
        except OSError as exc:
            raise ObsClientError(f"tcp connect failed: {exc}") from exc
        self._sock = sock
        try:
            wire.client_handshake(sock, self.host, self.port,
                                  path="/", timeout=self.timeout)
            self._conn = wire.WsConnection(sock, mask_outgoing=True)
            hello_op, hello_data = self._next_message()
            if hello_op != OP_HELLO:
                raise ObsClientError(
                    f"expected Hello, got opcode {hello_op}")
            rpc_version = hello_data.get("rpcVersion")
            if not isinstance(rpc_version, int):
                raise ObsClientError("Hello missing rpcVersion")

            auth_string = respond_to_hello(
                hello_data.get("authentication"), self.password)
            identify = make_identify(auth_string, self.subscriptions)
            self._send_envelope(identify)

            ident_op, ident_data = self._next_message()
            if ident_op != OP_IDENTIFIED:
                raise ObsClientError(
                    "Identify rejected (bad password or unsupported "
                    f"rpcVersion): opcode {ident_op}")
            negotiated = ident_data.get("negotiatedRpcVersion")
            if not isinstance(negotiated, int):
                raise ObsClientError("Identified missing "
                                     "negotiatedRpcVersion")
            self.negotiated_rpc_version = negotiated
        except (OSError, wire.WireError, wire.ConnectionClosed,
                ProtocolError) as exc:
            self.close()
            if isinstance(exc, ObsClientError):
                raise
            raise ObsClientError(f"handshake failed: {exc}") from exc

        self._reader = threading.Thread(target=self._read_loop,
                                        daemon=True,
                                        name="mind-obs-reader")
        self._reader.start()

    def close(self):
        self._closing.set()
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter.set()  # wake requesters; they will see closed state
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._reader is not None and \
                threading.current_thread() is not self._reader:
            self._reader.join(timeout=2.0)

    # -- low level ---------------------------------------------------------

    def _send_envelope(self, envelope: dict):
        assert self._conn is not None, "not connected"
        self._conn.send_text(json.dumps(envelope))

    def _next_message(self):
        opcode, payload = self._conn.receive_message()
        return parse_message(payload)

    # -- requests ------------------------------------------------------------

    def request(self, request_type: str,
                request_data: "dict | None" = None,
                timeout: "float | None" = None) -> dict:
        """Send one request, return responseData dict.

        Raises ObsClientError when disconnected/closed and
        RequestTimeout when the reply does not arrive in time.
        """
        if self._conn is None or self._closing.is_set():
            raise ObsClientError("not connected")
        with self._pending_lock:
            request_id = f"mind-{next(self._ids)}"
            waiter = threading.Event()
            self._pending[request_id] = {
                "waiter": waiter, "result": None, "data": None}
        envelope = make_request(request_type, request_id, request_data)
        try:
            self._send_envelope(envelope)
        except (OSError, wire.WireError, wire.ConnectionClosed) as exc:
            self.close()
            raise ObsClientError(f"request send failed: {exc}") from exc
        limit = self.timeout if timeout is None else float(timeout)
        if not waiter.wait(limit):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise RequestTimeout(
                f"{request_type}: no response within {limit}s")
        entry = self._pop_pending(request_id)
        if entry is None or entry.get("result") is None:
            raise ObsClientError(f"{request_type}: session closed "
                                 "before response")
        ok, data = entry["result"], entry["data"]
        if not ok:
            raise ObsClientError(
                f"{request_type}: server reported failure "
                f"{json_compact(data)}")
        return data or {}

    def _pop_pending(self, request_id: str):
        with self._pending_lock:
            return self._pending.pop(request_id, None)

    # -- reader ----------------------------------------------------------------

    def _read_loop(self):
        try:
            while not self._closing.is_set():
                opcode, data = self._next_message()
                if opcode == OP_EVENT:
                    self._dispatch_event(data)
                elif opcode == OP_REQUEST_RESPONSE:
                    self._resolve_request(data)
                # Welcome / others: informational, ignored post-handshake
        except (OSError, wire.WireError, wire.ConnectionClosed,
                ProtocolError):
            pass
        finally:
            was_closing = self._closing.is_set()
            self._closing.set()
            with self._pending_lock:
                pending = list(self._pending.values())
                self._pending.clear()
            for entry in pending:
                entry["waiter"].set()
            if not was_closing and self.on_event is not None:
                try:
                    self.on_event("__disconnected__", {})
                except Exception:
                    pass

    def _resolve_request(self, data: dict):
        request_type, request_id, result, response_data = \
            parse_response(data)
        # peek, don't pop: the requesting thread owns removal via
        # _pop_pending - popping here wins the race against it and
        # turns every successful reply into "session closed"
        with self._pending_lock:
            entry = self._pending.get(request_id)
        if entry is None:
            return  # late reply after timeout; drop it
        entry["result"] = result
        entry["data"] = response_data
        entry["waiter"].set()

    def _dispatch_event(self, data: dict):
        if self.on_event is None:
            return
        event_type, event_data = parse_event(data)
        try:
            self.on_event(event_type, event_data)
        except Exception:
            # a broken subscriber must never kill the reader loop
            pass


def json_compact(value) -> str:
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)


def selftest() -> int:
    print("client selftest: exercised via mind/verify_mind.py "
          "(needs a live mock peer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
