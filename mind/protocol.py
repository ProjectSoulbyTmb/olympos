"""MIND protocol - obs-websocket v5 opcodes, subscriptions, envelopes.

Constants and strict-ish envelope helpers shared by the client and the
mock OBS peer. Keeping them in one place means a protocol drift shows
up as one diff.

Run: python mind/protocol.py   (self-test, exit 0 = tables consistent)
"""

from __future__ import annotations

import json

# WebSocket opcodes carrying obs-websocket payloads (v5 spec).
OP_HELLO = 0
OP_WELCOME = 1
OP_IDENTIFY = 2
OP_IDENTIFIED = 3
OP_REIDENTIFY = 4
OP_EVENT = 5
OP_REQUEST = 6
OP_REQUEST_RESPONSE = 7
OP_REQUEST_BATCH = 8
OP_REQUEST_BATCH_RESPONSE = 9

OPCODE_NAMES = {
    OP_HELLO: "Hello",
    OP_WELCOME: "Welcome",
    OP_IDENTIFY: "Identify",
    OP_IDENTIFIED: "Identified",
    OP_REIDENTIFY: "Reidentify",
    OP_EVENT: "Event",
    OP_REQUEST: "Request",
    OP_REQUEST_RESPONSE: "RequestResponse",
    OP_REQUEST_BATCH: "RequestBatch",
    OP_REQUEST_BATCH_RESPONSE: "RequestBatchResponse",
}

RPC_VERSION = 1


class EventSubscription:
    """Bitmask categories from the v5 spec (eventSubscriptions field)."""

    NONE = 0
    GENERAL = 1 << 0
    CONFIG = 1 << 1
    SCENES = 1 << 2
    INPUTS = 1 << 3
    TRANSITIONS = 1 << 4
    FILTERS = 1 << 5
    SCENE_ITEMS = 1 << 6
    MEDIA_INPUTS = 1 << 7
    VENDORS = 1 << 8
    UI = 1 << 9
    ALL = (1 << 10) - 1

    @classmethod
    def valid(cls, value) -> bool:
        return isinstance(value, int) and 0 <= value <= cls.ALL


class ProtocolError(Exception):
    """Malformed envelope or unexpected opcode."""


def envelope(opcode: int, payload: "dict | None" = None) -> dict:
    if opcode not in OPCODE_NAMES:
        raise ProtocolError(f"unknown opcode {opcode}")
    message = {"op": opcode}
    if payload is not None:
        message["d"] = payload
    return message


def parse_message(raw: bytes) -> "tuple[int, dict]":
    """Parse one text frame into (opcode, data-dict)."""
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"unparseable frame: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("envelope must be an object")
    opcode = message.get("op")
    if not isinstance(opcode, int) or opcode not in OPCODE_NAMES:
        raise ProtocolError(f"unknown opcode {opcode!r}")
    data = message.get("d", {})
    if not isinstance(data, dict):
        raise ProtocolError("payload must be an object")
    return opcode, data


def make_identify(auth_string: "str | None", event_subscriptions: int,
                  rpc_version: int = RPC_VERSION) -> dict:
    payload = {"rpcVersion": rpc_version,
               "eventSubscriptions": event_subscriptions}
    if auth_string is not None:
        payload["authentication"] = auth_string
    return envelope(OP_IDENTIFY, payload)


def make_request(request_type: str, request_id: str,
                 request_data: "dict | None" = None) -> dict:
    if not request_type or not request_id:
        raise ProtocolError("requestType and requestId are required")
    payload = {"requestType": str(request_type), "requestId": str(request_id)}
    if request_data is not None:
        if not isinstance(request_data, dict):
            raise ProtocolError("requestData must be an object")
        payload["requestData"] = request_data
    return envelope(OP_REQUEST, payload)


def parse_request(data: dict) -> "tuple[str, str, dict]":
    request_type = data.get("requestType")
    request_id = data.get("requestId")
    if not isinstance(request_type, str) or not request_type:
        raise ProtocolError("missing requestType")
    if not isinstance(request_id, str) or not request_id:
        raise ProtocolError("missing requestId")
    request_data = data.get("requestData") or {}
    if not isinstance(request_data, dict):
        raise ProtocolError("requestData must be an object")
    return request_type, request_id, request_data


def make_response(request_type: str, request_id: str, result: bool = True,
                  response_data: "dict | None" = None) -> dict:
    payload = {"requestType": request_type,
               "requestId": request_id,
               "requestStatus": {"result": bool(result),
                                 "code": 100 if result else 500}}
    if response_data is not None:
        payload["responseData"] = response_data
    return envelope(OP_REQUEST_RESPONSE, payload)


def parse_response(data: dict) -> "tuple[str, str, bool, dict]":
    request_type = data.get("requestType", "")
    request_id = data.get("requestId", "")
    status = data.get("requestStatus") or {}
    result = bool(status.get("result", False))
    response_data = data.get("responseData") or {}
    if not isinstance(request_id, str) or not request_id:
        raise ProtocolError("response missing requestId")
    return request_type, request_id, result, response_data


def make_event(event_type: str, event_data: "dict | None" = None) -> dict:
    if not event_type:
        raise ProtocolError("eventType is required")
    payload = {"eventType": event_type,
               "eventIntent": EventSubscription.ALL}
    if event_data is not None:
        payload["eventData"] = event_data
    return envelope(OP_EVENT, payload)


def parse_event(data: dict) -> "tuple[str, dict]":
    event_type = data.get("eventType")
    if not isinstance(event_type, str) or not event_type:
        raise ProtocolError("event missing eventType")
    event_data = data.get("eventData") or {}
    if not isinstance(event_data, dict):
        raise ProtocolError("eventData must be an object")
    return event_type, event_data


def selftest() -> int:
    failures = []

    def check(name, fn):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")

    def t_roundtrips():
        req = make_request("GetSceneList", "r-7")
        op, data = parse_message(json.dumps(req).encode())
        assert op == OP_REQUEST
        rtype, rid, rdata = parse_request(data)
        assert (rtype, rid, rdata) == ("GetSceneList", "r-7", {})

        resp = make_response("GetSceneList", "r-7", True,
                             {"scenes": [{"sceneName": "Live"}]})
        op, data = parse_message(json.dumps(resp).encode())
        _, rid, ok, rd = parse_response(data)
        assert rid == "r-7" and ok and rd["scenes"][0]["sceneName"] == "Live"

        ev = make_event("CurrentProgramSceneChanged", {"sceneName": "B"})
        op, data = parse_message(json.dumps(ev).encode())
        etype, edata = parse_event(data)
        assert etype == "CurrentProgramSceneChanged"
        assert edata["sceneName"] == "B"

    def t_rejections():
        for bad in (b"", b"{", b"[1]", b'"x"', b'{"op":99,"d":{}}',
                    b'{"op":"text","d":{}}', b'{"op":6,"d":[]}'):
            try:
                parse_message(bad)
                raise AssertionError(f"accepted garbage {bad!r}")
            except ProtocolError:
                pass
        try:
            make_request("", "id")
            raise AssertionError("empty requestType accepted")
        except ProtocolError:
            pass

    def t_subscription_bounds():
        assert EventSubscription.valid(0) and EventSubscription.valid(
            EventSubscription.ALL)
        assert EventSubscription.ALL == 1023, "v5 flag table changed?"
        assert not EventSubscription.valid(1024)
        assert not EventSubscription.valid(-1)

    check("envelope-roundtrips", t_roundtrips)
    check("envelope-rejections", t_rejections)
    check("subscription-flags-bounded", t_subscription_bounds)

    print(f"protocol selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
