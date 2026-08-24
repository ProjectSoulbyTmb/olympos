"""ATLAS authoritative server - the hypervisor's wire face.

JSON-lines contract, mirroring Zeus/Vulcan:

  -> {"cmd": "exec", "args": {"name": "g1", "argv": ["py", "-c", "1"]}}
  <- {"error": null, "result": {...}}

Capability rights come from NORN: watchers may observe the fleet,
only operators may rent compute. Every mutating call is journalled by
the NORN witness when available.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import json
import socket
import threading
import time
from collections import deque

from atlas.kernel import Hypervisor
from atlas import content

try:
    import norn.rights as rights
except ImportError:                 # pragma: no cover
    rights = None
try:
    from norn.witness import Witness
except ImportError:                 # pragma: no cover
    Witness = None
try:
    import ratatosk
except ImportError:                 # pragma: no cover
    ratatosk = None
try:
    from norn.pulse import Pulse
except ImportError:                 # pragma: no cover
    Pulse = None


class AtlasServer:
    def __init__(self, host=None, port=None, hypervisor=None,
                 auto_reap=True):
        self.host = host or content.SERVER_HOST
        self.port = content.SERVER_PORT if port is None else port
        self.hv = hypervisor or Hypervisor()
        self.sessions = {}
        self.profiles = {}
        self.authed = set()          # reserved for a future capability
        self._cmd_times = {}
        self._lock = threading.Lock()
        self._next_conn = 0
        self._sock = None
        self._thread = None
        self._reap_thread = None
        self.running = False
        self.auto_reap = auto_reap
        self.witness = None
        if Witness is not None:
            try:
                wdir = os.environ.get("NORN_WITNESS_DIR") or os.path.join(
                    ROOT, "data", "witness")
                self.witness = Witness(wdir, actor="atlas")
            except Exception:         # noqa: BLE001
                self.witness = None
        self.pulse = None
        if Pulse is not None:
            self.pulse = Pulse(name="atlas", beat_s=5.0)
            self.pulse.add_organ("reaper", self._reap_beat,
                                 every_beats=content.REAP_EVERY_BEATS)

    def _reap_beat(self):
        reaped = self.hv.reap()
        if reaped and ratatosk is not None:
            try:
                ratatosk.publish("atlas",
                                 {"reaped": reaped},
                                 frm="atlas", kind="reap")
            except Exception:
                pass

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
        if self.auto_reap and self.pulse is not None:
            self._reap_thread = threading.Thread(
                target=self._pulse_loop, daemon=True)
            self._reap_thread.start()

    def _bind(self):
        last_err = None
        for _ in range(10):
            try:
                self._sock = socket.socket(socket.AF_INET,
                                           socket.SOCK_STREAM)
                self._sock.bind((self.host, self.port))
                break
            except OSError as exc:
                last_err = exc
                self._sock.close()
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
                self.profiles[cid] = (
                    rights.ATLAS_DEFAULT_PROFILE
                    if rights is not None else "operator")
                self._cmd_times[cid] = deque()
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

    def _pulse_loop(self):
        while self.running:
            try:
                if self.pulse is not None:
                    self.pulse.beat()
            except Exception as exc:      # noqa: BLE001 - keep alive
                print(f"[atlas] pulse error: {exc}")
            time.sleep(5.0)

    def _client_loop(self, conn, cid):
        profile = (rights.ATLAS_DEFAULT_PROFILE
                   if rights is not None else "operator")
        conn.sendall(json.dumps(
            {"error": None, "result": {
                "hello": "atlas", "version": content.VERSION,
                "profile": profile,
                "guests": len(self.hv.guests),
                "port": content.SERVER_PORT}}
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
                if not self._rate_ok(cid):
                    self._send(conn, error="rate_limited: slow down",
                               result=None)
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
                self._cmd_times.pop(cid, None)
                self.authed.discard(cid)

    def _rate_ok(self, cid):
        now = time.time()
        with self._lock:
            times = self._cmd_times.setdefault(cid, deque())
            window = getattr(content, "RATE_WINDOW_S", 10.0)
            cap = getattr(content, "RATE_MAX_COMMANDS", 240)
            while times and now - times[0] > window:
                times.popleft()
            if len(times) >= cap:
                return False
            times.append(now)
            return True

    def handle(self, cmd, args, cid=None):
        cmd = str(cmd)
        if cmd == "close":
            return {"error": None, "result": {"bye": True}}
        method = getattr(self.sdk(), cmd, None)
        if cmd not in AtlasSDK._VALID or not callable(method):
            return {"error": f"unknown command: {cmd}", "result": None}
        if rights is not None and cid is not None:
            pname = self.profiles.get(cid,
                                      rights.ATLAS_DEFAULT_PROFILE)
            allowed = rights.ATLAS_PROFILES.get(pname)
            if allowed is not None and cmd not in allowed:
                return {"error": f"right_denied: profile '{pname}' "
                                 f"may not '{cmd}'", "result": None}
        args = args if isinstance(args, dict) else {}
        mutating = cmd not in (rights.ATLAS_INFO
                               if rights is not None else set())
        try:
            result = method(**args)
            error = None
        except KeyError as exc:
            result, error = None, str(exc.args[0] if exc.args else exc)
        except (ValueError, TypeError) as exc:
            result, error = None, str(exc)
        except Exception as exc:          # noqa: BLE001 - wire face
            result, error = None, f"internal error: {exc!r}"
        if mutating and self.witness is not None:
            try:
                self.witness.record(cmd, list(args.values()),
                                    ok=error is None, error=error)
            except Exception:             # noqa: BLE001
                pass
        return {"error": error, "result": result}

    def sdk(self):
        """Bind an SDK face onto this server's own hypervisor."""
        if not hasattr(self, "_sdk"):
            self._sdk = AtlasSDK(self.hv)
        return self._sdk

    @staticmethod
    def _send(conn, error=None, result=None):
        try:
            conn.sendall(json.dumps({"error": error, "result": result},
                                    separators=(",", ":"),
                                    default=str).encode("utf-8") + b"\n")
        except OSError:
            pass


class AtlasSDK:
    """In-process facade; identical verb names to the wire."""

    _VALID = {
        "ping", "status", "guests", "create", "exec", "stop",
        "reap", "purge", "close",
    }

    def __init__(self, hv=None):
        self.hv = hv or Hypervisor()

    def ping(self):
        return {"pong": True, "service": "atlas"}

    def status(self):
        return self.hv.status()

    def guests(self):
        return self.hv.listing()

    def create(self, name):
        return self.hv.create(name)

    def exec(self, name, argv, timeout_s=None, cwd=""):
        return self.hv.exec(name, argv, timeout_s=timeout_s, cwd=cwd)

    def stop(self, name):
        return self.hv.stop(name)

    def reap(self):
        return {"reaped": self.hv.reap()}

    def purge(self, name):
        return self.hv.purge(name)

    def close(self):
        return {"bye": True}


def main():
    server = AtlasServer(auto_reap=True)
    server.start_async()
    print(f"[atlas] hosting {len(server.hv.guests)} guest(s) on "
          f"{server.host}:{server.port}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[atlas] shutting down")
        server.running = False


if __name__ == "__main__":
    main()
