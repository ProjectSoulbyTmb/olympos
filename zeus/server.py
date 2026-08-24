"""ZEUS authoritative server.

One shared Kernel; every connection is a dashboard, operator console
or automation client. JSON-lines protocol, mirroring the RSPS and
Vulcan contracts:

  -> {"cmd": "status", "args": {}}
  <- {"error": null, "result": {...}}

An optional background thread patrols on its own at
PATROL_SECONDS_REAL so hosted protection stays live unattended.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import json
import socket
import threading
import time

from sdk import ZeusClient, ZeusSDK, wire_client  # noqa: F401
from kernel import Kernel

import content


class ZeusServer:
    def __init__(self, host=None, port=None, kernel=None,
                 auto_patrol=True):
        self.host = host or content.SERVER_HOST
        self.port = port or content.SERVER_PORT
        self.kernel = kernel if kernel is not None else Kernel()
        self.sdk = ZeusSDK(self.kernel)
        self.sessions = {}
        self._lock = threading.Lock()
        self._next_conn = 0
        self._sock = None
        self._thread = None
        self._patrol_thread = None
        self.running = False
        self.auto_patrol = auto_patrol

    @property
    def connection_count(self):
        return len(self.sessions)

    def start_async(self):
        if self.running:
            return
        self._bind()
        self.running = True
        self._thread = threading.Thread(target=self.serve_forever,
                                        daemon=True)
        self._thread.start()
        if self.auto_patrol:
            self._patrol_thread = threading.Thread(
                target=self._patrol_loop, daemon=True)
            self._patrol_thread.start()

    def _bind(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        last_err = None
        for _ in range(10):
            try:
                self._sock.bind((self.host, self.port))
                break
            except OSError as exc:
                last_err = exc
                self.port += 1
        else:
            raise OSError(f"no free port: {last_err}")
        self._sock.listen(8)
        self._sock.settimeout(0.5)
        self.host, self.port = self._sock.getsockname()[:2]

    def serve_forever(self):
        while self.running:
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                self._next_conn += 1
                cid = self._next_conn
                if len(self.sessions) >= content.MAX_SESSIONS:
                    self._deny(conn)
                    continue
                self.sessions[cid] = addr[0]
            thread = threading.Thread(target=self._client_loop,
                                      args=(conn, cid), daemon=True)
            thread.start()

    def _deny(self, conn):
        try:
            conn.sendall(json.dumps(
                {"error": "server full", "result": None})
                .encode("utf-8") + b"\n")
        finally:
            conn.close()

    def _client_loop(self, conn, cid):
        conn.sendall(json.dumps(
            {"error": None, "result": {
                "hello": "zeus", "version": content.VERSION,
                "watches": len(self.kernel.sentinel.manifest),
                "ticks": self.kernel.tick_count}}
        ).encode("utf-8") + b"\n")
        sock_file = conn.makefile("rb")
        try:
            for raw in sock_file:
                if len(raw) > content.MAX_LINE_BYTES:
                    self._send(conn, error="line too long")
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._send(conn, error="bad json")
                    continue
                if not isinstance(msg, dict) or "cmd" not in msg:
                    self._send(conn, error="missing cmd")
                    continue
                resp = self.handle(msg.get("cmd"), msg.get("args") or {})
                self._send(conn, **resp)
                if msg.get("cmd") == "close":
                    break
        except (ConnectionResetError, OSError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            with self._lock:
                self.sessions.pop(cid, None)

    def handle(self, cmd, args):
        cmd = str(cmd)
        if cmd == "close":
            return {"error": None, "result": {"bye": True}}
        method = getattr(self.sdk, cmd, None)
        if cmd not in ZeusSDK._VALID or not callable(method):
            return {"error": f"unknown command: {cmd}", "result": None}
        args = args if isinstance(args, dict) else {}
        try:
            with self._lock:
                result = method(**args)
            return {"error": None, "result": result}
        except KeyError as exc:
            return {"error": str(exc.args[0] if exc.args else exc),
                    "result": None}
        except (ValueError, TypeError) as exc:
            return {"error": str(exc), "result": None}
        except Exception as exc:                 # noqa: BLE001 - wire edge
            return {"error": f"internal error: {exc!r}", "result": None}

    @staticmethod
    def _send(conn, error=None, result=None):
        try:
            conn.sendall(json.dumps({"error": error, "result": result},
                                    separators=(",", ":"),
                                    default=str).encode("utf-8") + b"\n")
        except OSError:
            pass

    def _patrol_loop(self):
        next_at = time.time() + content.PATROL_SECONDS_REAL
        while self.running:
            time.sleep(max(0.05, min(0.5, next_at - time.time())))
            if time.time() < next_at:
                continue
            next_at = time.time() + content.PATROL_SECONDS_REAL
            try:
                with self._lock:
                    self.kernel.tick()
            except Exception as exc:             # noqa: BLE001 - keep alive
                print(f"[zeus] patrol error: {exc}")


def main():
    server = ZeusServer(auto_patrol=True)
    server.start_async()
    print(f"[zeus] guarding from {server.host}:{server.port} "
          f"(auto-patrol every {content.PATROL_SECONDS_REAL}s)")
    print(f"[zeus] connect: python -m zeus.cli --connect "
          f"{server.host} {server.port}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[zeus] shutting down")
        server.running = False


if __name__ == "__main__":
    main()
