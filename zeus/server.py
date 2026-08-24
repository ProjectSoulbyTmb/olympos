"""ZEUS authoritative server.

One shared Kernel; every connection is a dashboard, operator console
or automation client. JSON-lines protocol, mirroring the Vulcan
contract:

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

_HERE2 = os.path.dirname(HERE)          # workspace root: norn/ lives there
if _HERE2 not in sys.path:
    sys.path.insert(0, _HERE2)

try:                                    # NORN capability rights
    import norn.rights as rights
except ImportError:                     # pragma: no cover - degrade open
    rights = None

try:                                    # NORN witness journal
    from norn.witness import Witness
except ImportError:                     # pragma: no cover
    Witness = None

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
        self.profiles = {}        # cid -> rights profile name
        self._lock = threading.Lock()
        self._next_conn = 0
        self._sock = None
        self._thread = None
        self._patrol_thread = None
        self.running = False
        self.auto_patrol = auto_patrol
        self.witness = None
        if Witness is not None:
            try:
                wdir = os.environ.get("NORN_WITNESS_DIR") or os.path.join(
                    os.path.dirname(HERE), "data", "witness")
                self.witness = Witness(wdir, actor="zeus")
            except Exception:     # noqa: BLE001 - journaling is optional
                self.witness = None

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
        # No SO_REUSEADDR here: on Windows it permits double-binds, so
        # two concurrent self-verification runs could silently share a
        # port and clients would cross-connect. A collision must fail
        # loudly into the retry below instead.
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
        profile = (rights.ZEUS_DEFAULT_PROFILE
                   if rights is not None else "operator")
        with self._lock:
            self.profiles[cid] = profile
        conn.sendall(json.dumps(
            {"error": None, "result": {
                "hello": "zeus", "version": content.VERSION,
                "profile": profile,
                "profiles": sorted(rights.ZEUS_PROFILES)
                if rights is not None else ["operator"],
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
                cmd = str(msg.get("cmd"))
                if rights is not None and cmd == "assume":
                    newp = str((msg.get("args") or {}).get("profile", ""))
                    with self._lock:
                        cur = self.profiles.get(cid, profile)
                        allowed = rights.can_narrow(
                            rights.ZEUS_PROFILES.get(cur),
                            rights.ZEUS_PROFILES.get(newp))
                        if allowed:
                            self.profiles[cid] = newp
                    if allowed:
                        self._send(conn, result={"assumed": newp})
                    else:
                        self._send(
                            conn,
                            error=f"right_denied: cannot escalate "
                                  f"{cur} -> {newp}")
                    continue
                resp = self.handle(cmd, msg.get("args") or {}, cid=cid)
                self._send(conn, **resp)
                if cmd == "close":
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
                self.profiles.pop(cid, None)

    def handle(self, cmd, args, cid=None):
        cmd = str(cmd)
        if cmd == "close":
            return {"error": None, "result": {"bye": True}}
        method = getattr(self.sdk, cmd, None)
        if cmd not in ZeusSDK._VALID or not callable(method):
            return {"error": f"unknown command: {cmd}", "result": None}
        if rights is not None and cid is not None:
            with self._lock:
                pname = self.profiles.get(
                    cid, rights.ZEUS_DEFAULT_PROFILE)
            allowed = rights.ZEUS_PROFILES.get(pname)
            if allowed is not None and cmd not in allowed:
                return {"error": f"right_denied: profile '{pname}' "
                                 f"may not '{cmd}'", "result": None}
        args = args if isinstance(args, dict) else {}
        try:
            result = method(**args)
            error = None
        except KeyError as exc:
            result, error = None, str(exc.args[0] if exc.args else exc)
        except (ValueError, TypeError) as exc:
            result, error = None, str(exc)
        except Exception as exc:             # noqa: BLE001 - wire face
            result, error = None, f"internal error: {exc!r}"
        if self.witness is not None and rights is not None \
                and cmd in rights.ZEUS_MUTATING:
            try:
                self.witness.record(cmd, list(args.values()),
                                    ok=error is None, error=error,
                                    tick=self.kernel.tick_count)
            except Exception:                # noqa: BLE001 - optional
                pass
        return {"error": error, "result": result}

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
