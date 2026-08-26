"""MIND wire - minimal RFC 6455 websocket framing for the OBS client.

Client side only, text frames only, standard library only. Frames we
send are masked (clients must mask); frames we read may be unmasked
(server) or masked (mock peers in tests).

All I/O goes through WireConn: a socket plus whatever bytes were
already consumed past the HTTP upgrade handshake. Sockets carry no
user attributes, so the read buffer lives here.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT, OP_TEXT, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x8, 0x9, 0xA
MAX_FRAME_BYTES = 8 * 1024 * 1024


class WireError(Exception):
    pass


def accept_key(client_key: str) -> str:
    digest = hashlib.sha1(
        (client_key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(payload: bytes, opcode: int = OP_TEXT,
                 fin: bool = True, mask: bool = True) -> bytes:
    header = bytearray()
    header.append((0x80 if fin else 0x00) | (opcode & 0x0F))
    length = len(payload)
    mask_bit = 0x80 if mask else 0x00
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header += length.to_bytes(2, "big")
    else:
        header.append(mask_bit | 127)
        header += length.to_bytes(8, "big")
    if mask:
        key = os.urandom(4)
        header += key
        payload = bytes(b ^ key[i % 4]
                        for i, b in enumerate(payload))
    return bytes(header) + payload


class WireConn:
    """One websocket connection: raw frames in, text messages out."""

    def __init__(self, sock: socket.socket, leftover: bytes = b""):
        self.sock = sock
        self._buf = bytearray(leftover)

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def open(cls, host: str, port: int, path: str = "/",
             timeout: float = 5.0) -> "WireConn":
        """Connect + perform the opening handshake."""
        sock = socket.create_connection((host, port), timeout=timeout)
        try:
            conn = cls(sock)
            conn.handshake(host, port, path, timeout)
            return conn
        except Exception:
            sock.close()
            raise

    def handshake(self, host: str, port: int, path: str = "/",
                  timeout: float = 5.0):
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n")
        self.sendall(request.encode("ascii"))
        lines = self._read_http_headers()
        status_line = lines[0].decode("latin-1").strip()
        parts = status_line.split(" ", 2)
        if len(parts) < 2 or parts[1] != "101":
            raise WireError(f"handshake refused: {status_line!r}")
        want = "sec-websocket-accept"
        got = ""
        for line in lines[1:]:
            text = line.decode("latin-1")
            if ":" in text:
                name, value = text.split(":", 1)
                if name.strip().lower() == want:
                    got = value.strip()
                    break
        if got != accept_key(key):
            raise WireError("bad Sec-WebSocket-Accept")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    # -- reading -----------------------------------------------------------

    def _read_http_headers(self) -> list:
        while b"\r\n\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WireError("peer closed during handshake")
            self._buf += chunk
            if len(self._buf) > 65536:
                raise WireError("handshake headers too large")
        head, _, rest = bytes(self._buf).partition(b"\r\n\r\n")
        self._buf = bytearray(rest)
        return head.split(b"\r\n")

    def _read_exact(self, count: int) -> bytes:
        while len(self._buf) < count:
            chunk = self.sock.recv(min(65536,
                                       count - len(self._buf)))
            if not chunk:
                raise WireError("connection closed mid-frame")
            self._buf += chunk
        out = bytes(self._buf[:count])
        del self._buf[:count]
        return out

    def read_frame(self):
        """Return (fin, opcode, payload); unmasks when needed."""
        head = self._read_exact(2)
        fin = bool(head[0] & 0x80)
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        length = head[1] & 0x7F
        if length == 126:
            length = int.from_bytes(self._read_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self._read_exact(8), "big")
        if length > MAX_FRAME_BYTES:
            raise WireError(f"frame too large: {length}")
        key = self._read_exact(4) if masked else None
        payload = self._read_exact(length) if length else b""
        if key:
            payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def recv_message(self):
        """Next complete text message, or None when the peer closes.

        Answers pings automatically; swallows pongs; concatenates
        continuation frames.
        """
        buffer = b""
        while True:
            fin, opcode, payload = self.read_frame()
            if opcode == OP_PING:
                self.sendall(encode_frame(payload, OP_PONG))
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                try:
                    self.sendall(encode_frame(b"", OP_CLOSE))
                except OSError:
                    pass
                return None
            if opcode in (OP_TEXT, OP_CONT):
                buffer += payload
                if fin:
                    return buffer.decode("utf-8")

    # -- writing -----------------------------------------------------------

    def sendall(self, data: bytes):
        self.sock.sendall(data)

    def send_text(self, text: str):
        self.sendall(encode_frame(text.encode("utf-8"), OP_TEXT))


def selftest() -> int:
    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL wire.{name}")
            failures.append(name)

    class FakeSock:
        def __init__(self, data):
            self._buf = data

        def recv(self, n):
            out, self._buf = self._buf[:n], self._buf[n:]
            return out

        def sendall(self, data):
            pass

    frame = encode_frame(b"hello", OP_TEXT)
    check("small-frame-shape", frame[0] == 0x81 and frame[1] & 0x7F == 5)

    big = encode_frame(b"x" * 30000, mask=False)
    check("extended-length-flag", big[1] & 0x7F == 126)

    conn = WireConn(FakeSock(frame))
    fin, op, payload = conn.read_frame()
    check("roundtrip-small",
          fin and op == OP_TEXT and payload == b"hello")

    conn = WireConn(FakeSock(big))
    _, _, payload = conn.read_frame()
    check("roundtrip-big-unmasked", len(payload) == 30000)

    conn = WireConn(FakeSock(
        encode_frame(b"", OP_CLOSE) + encode_frame(b"tail")))
    check("close-then-null", conn.recv_message() is None)

    conn = WireConn(FakeSock(
        encode_frame(b"hel", OP_TEXT, fin=False)
        + encode_frame(b"lo", OP_CONT)))
    check("continuation-concat", conn.recv_message() == "hello")

    ping_then_text = (encode_frame(b"keepalive", OP_PING)
                      + encode_frame(b"after"))
    conn = WireConn(FakeSock(ping_then_text))
    pong_sent = []
    conn.sendall = lambda data: pong_sent.append(bytes(data))
    check("ping-answered-text-follows",
          conn.recv_message() == "after" and len(pong_sent) >= 1)

    check("accept-key-vector",
          accept_key("dGhlIHNhbXBsZSBub25jZQ==")
          == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    print(f"wire selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
