"""MIND wire - minimal RFC 6455 WebSocket transport, stdlib only.

Implements exactly what the obs-websocket v5 protocol needs: the
opening handshake (client and server sides), a frame codec with
client-side masking, fragmentation reassembly, and ping/pong/close
control handling. No threads live here; callers own their I/O loops.

House style: every failure raises WireError; ConnectionClosed marks an
orderly remote close so supervisors can distinguish reconnects from
bugs.

Run: python mind/wire.py   (self-test, exit 0 = codec sane)
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

MAX_MESSAGE_BYTES = 4 * 1024 * 1024


class WireError(Exception):
    """Protocol violation or malformed peer data."""


class ConnectionClosed(Exception):
    """The peer performed an orderly WebSocket close."""


def accept_key(client_key: str) -> str:
    """RFC 6455 section 1.3 handshake accept key."""
    digest = hashlib.sha1((client_key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def new_client_key() -> str:
    return base64.b64encode(os.urandom(16)).decode("ascii")


def encode_frame(opcode: int, payload: bytes = b"", mask: bool = False,
                 fin: bool = True) -> bytes:
    """Encode one frame. Client-to-server frames MUST be masked."""
    if not 0 <= opcode <= 0xF:
        raise WireError(f"opcode out of range: {opcode}")
    header = bytearray()
    header.append((0x80 if fin else 0x00) | (opcode & 0x0F))
    length = len(payload)
    mask_bit = 0x80 if mask else 0x00
    if length < 126:
        header.append(mask_bit | length)
    elif length <= 0xFFFF:
        header.append(mask_bit | 126)
        header += struct.pack("!H", length)
    else:
        header.append(mask_bit | 127)
        header += struct.pack("!Q", length)
    if not mask:
        return bytes(header) + payload
    key = os.urandom(4)
    header += key
    return bytes(header) + _mask(payload, key)


def _mask(payload: bytes, key: bytes) -> bytes:
    out = bytearray(payload)
    for i in range(len(out)):
        out[i] ^= key[i & 3]
    return bytes(out)


def read_exact(sock: socket.socket, count: int) -> bytes:
    chunks = b""
    while len(chunks) < count:
        chunk = sock.recv(count - len(chunks))
        if not chunk:
            raise ConnectionClosed("peer closed mid-frame")
        chunks += chunk
    return chunks


def read_frame(sock: socket.socket):
    """Return (fin, opcode, payload) for one frame; unmasks as needed."""
    first, second = read_exact(sock, 2)
    fin = bool(first & 0x80)
    if first & 0x70:
        raise WireError("reserved bits set")
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        (length,) = struct.unpack("!H", read_exact(sock, 2))
    elif length == 127:
        (length,) = struct.unpack("!Q", read_exact(sock, 8))
    if length > MAX_MESSAGE_BYTES:
        raise WireError(f"frame too large: {length}")
    key = read_exact(sock, 4) if masked else None
    payload = read_exact(sock, length) if length else b""
    if key is not None:
        payload = _mask(payload, key)
    return fin, opcode, payload


class WsConnection:
    """One side of a WebSocket over an already-upgraded socket."""

    def __init__(self, sock: socket.socket, mask_outgoing: bool,
                 max_message_bytes: int = MAX_MESSAGE_BYTES):
        self.sock = sock
        self.mask_outgoing = mask_outgoing
        self.max_message_bytes = max_message_bytes

    def send_frame(self, opcode: int, payload: bytes = b"",
                   fin: bool = True):
        self.sock.sendall(encode_frame(opcode, payload,
                                       mask=self.mask_outgoing, fin=fin))

    def send_text(self, text: str):
        self.send_frame(OP_TEXT, text.encode("utf-8"))

    def send_pong(self, payload: bytes = b""):
        self.send_frame(OP_PONG, payload)

    def send_close(self, code: int = 1000):
        self.send_frame(OP_CLOSE, struct.pack("!H", code))

    def receive_message(self):
        """Return (opcode, payload_utf8_bytes) for the next data message.

        Control frames are answered inline (ping->pong, close->echo).
        Fragmented messages are reassembled.
        """
        frags = []
        frag_opcode = None
        total = 0
        while True:
            fin, opcode, payload = read_frame(self.sock)
            if opcode == OP_PING:
                self.send_pong(payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                try:
                    self.send_close()
                except OSError:
                    pass
                raise ConnectionClosed("peer closed session")
            if opcode in (OP_TEXT, OP_BINARY):
                if frag_opcode is not None:
                    raise WireError("new data message mid-fragment")
                frag_opcode = opcode
                frags.append(payload)
                total += len(payload)
            elif opcode == OP_CONT:
                if frag_opcode is None:
                    raise WireError("continuation without start")
                frags.append(payload)
                total += len(payload)
            else:
                raise WireError(f"unknown opcode {opcode}")
            if total > self.max_message_bytes:
                raise WireError("message too large")
            if fin:
                return frag_opcode, b"".join(frags)


def client_handshake(sock: socket.socket, host: str, port: int,
                     path: str = "/", timeout: float = 5.0) -> str:
    """Perform the client side of the opening handshake.

    Returns the server's Sec-WebSocket-Accept value on success.
    """
    key = new_client_key()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.settimeout(timeout)
    sock.sendall(request.encode("ascii"))
    raw = b""
    while b"\r\n\r\n" not in raw:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionClosed("peer closed during handshake")
        raw += chunk
        if len(raw) > 65536:
            raise WireError("handshake headers too large")
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0] if lines else ""
    if not status.startswith("HTTP/1.1 101"):
        raise WireError(f"handshake refused: {status}")
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    expected = accept_key(key)
    got = headers.get("sec-websocket-accept", "")
    if got != expected:
        raise WireError("bad Sec-WebSocket-Accept from server")
    sock.settimeout(None)
    if rest:
        raise WireError("unexpected bytes after handshake")
    return got


def server_accept_response(client_key: str) -> bytes:
    """Build the 101 response bytes for a server-side handshake."""
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(client_key)}\r\n"
        "\r\n"
    ).encode("ascii")


def parse_client_upgrade(head_text: str) -> str:
    """Extract + validate Sec-WebSocket-Key from a server-side request."""
    lines = head_text.split("\r\n")
    if not lines or not lines[0].upper().startswith("GET"):
        raise WireError("not a GET upgrade request")
    wanted = {"upgrade": False, "connection": False}
    key = None
    for line in lines[1:]:
        name, _, value = line.partition(":")
        lname = name.strip().lower()
        value = value.strip()
        if lname == "upgrade" and value.lower() == "websocket":
            wanted["upgrade"] = True
        elif lname == "connection" and "upgrade" in value.lower():
            wanted["connection"] = True
        elif lname == "sec-websocket-key":
            key = value
    if not all(wanted.values()) or not key:
        raise WireError("missing websocket upgrade headers")
    return key


def selftest() -> int:
    import threading

    failures = []

    def check(name, fn):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")

    def t_accept_vector():
        # RFC 6455 section 1.3 worked example.
        assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == \
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", "RFC accept vector mismatch"

    def _roundtrip(payload_size, form):
        payload = bytes(range(256)) * (payload_size // 256)
        frame = encode_frame(OP_TEXT, payload, mask=True)
        # decode through a socketpair so read_frame sees a real stream
        left, right = socket.socketpair()
        try:
            left.sendall(frame)
            fin, opcode, got = read_frame(right)
            assert fin and opcode == OP_TEXT, "header lost"
            assert got == payload, f"{form} payload corrupted"
        finally:
            left.close()
            right.close()

    def t_small(): _roundtrip(300, "7-bit+ext16")
    def t_wide(): _roundtrip(70000, "ext64")

    def t_fragmentation():
        left, right = socket.socketpair()
        conn = WsConnection(right, mask_outgoing=False)
        try:
            left.sendall(encode_frame(OP_TEXT, b"hel", mask=True, fin=False))
            left.sendall(encode_frame(OP_CONT, b"lo ", mask=True, fin=False))
            left.sendall(encode_frame(OP_CONT, b"world", mask=True, fin=True))
            opcode, data = conn.receive_message()
            assert opcode == OP_TEXT and data == b"hello world", \
                f"fragment assembly wrong: {data!r}"
        finally:
            left.close()
            right.close()

    def t_ping_pong_close():
        left, right = socket.socketpair()
        conn = WsConnection(right, mask_outgoing=False)
        try:
            left.sendall(encode_frame(OP_PING, b"beat", mask=True))
            left.sendall(encode_frame(OP_CLOSE, struct.pack("!H", 1000),
                                      mask=True))
            conn.receive_message()
            raise AssertionError("close did not surface")
        except ConnectionClosed:
            pass
        finally:
            left.close()
            right.close()

    check("rfc6455-accept-vector", t_accept_vector)
    check("frame-roundtrip-small", t_small)
    check("frame-roundtrip-wide", t_wide)
    check("fragment-reassembly", t_fragmentation)
    check("ping-close-control-flow", t_ping_pong_close)

    print(f"wire selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
