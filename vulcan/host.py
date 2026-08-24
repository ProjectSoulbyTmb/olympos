"""Vulcan authoritative server.

One shared World (it is one building); every connection is a dashboard,
automation client or console. JSON-lines protocol:

  -> {"cmd": "state", "args": {}}
  <- {"error": null, "result": {...}}

Every response carries an `error` field (null on success), mirroring
the zeus server contract. An optional background thread auto-ticks the
building at TICK_SECONDS_REAL so hosted runs stay alive on their own.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

_ROOT = os.path.dirname(HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import json
import socket
import threading
import time

import norn.rights as rights
from norn.pulse import Pulse
from rules import RuleEngine
from sdk import VulcanSDK
from world import World

import content


class BuildingServer:
    def __init__(self, host=None, port=None, world=None, auto_tick=True):
        self.host = host or content.SERVER_HOST
        self.port = port or content.SERVER_PORT
        self.world = world if world is not None else World()
        self.engine = RuleEngine(self.world)
        self.sdk = VulcanSDK(self.world, self.engine)
        self.sessions = {}
        self.profiles = {}        # cid -> rights profile name
        self._lock = threading.Lock()
        self._next_conn = 0
        self._sock = None
        self._thread = None
        self._tick_thread = None
        self.running = False
        self.auto_tick = auto_tick
        # NORN pulse: the tick heart is an organ with a latency SLO;
        # sustained breach quarantines it briefly (autonomic pause)
        # instead of letting a wedged building spiral.
        self.world.pulse = Pulse(name="vulcan",
                                 beat_s=content.TICK_SECONDS_REAL)
        self.world.pulse.add_organ(
            "world_tick", self._locked_tick,
            slo_max_ms=content.TICK_SECONDS_REAL * 750.0,
            slo_max_late=5, revive_after=2)
        self.world.pulse.add_organ(
            "post_office", self._post_office_beat, every_beats=10)
        self.witness = None
        try:    # NORN witness: attest every mutating SDK verb
            from norn.witness import Witness
            wdir = os.environ.get("NORN_WITNESS_DIR") or os.path.join(
                _ROOT, "data", "witness")
            self.witness = Witness(wdir, actor="vulcan")
        except Exception:
            self.witness = None

    def _locked_tick(self):
        with self._lock:
            return self.world.tick(rule_engine=self.engine)

    def _post_office_beat(self):
        try:
            from ratatosk import beat
            beat("vulcan", note=f"tick {self.world.tick_count}")
        except Exception:
            pass

    def beat_once(self):
        """One NORN pulse beat (tick + auxiliary organs). Drivable in
        tests without the socket thread."""
        self.world.pulse.beat()

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
        if self.auto_tick:
            self._tick_thread = threading.Thread(target=self._auto_loop,
                                                 daemon=True)
            self._tick_thread.start()

    def _bind(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # No SO_REUSEADDR: on Windows it allows double-binds, which
        # lets concurrent self-verification runs cross-connect. A port
        # collision must fail loudly into the retry loop below.
        last_err = None
        for attempt in range(10):
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
        profile = rights.VULCAN_DEFAULT_PROFILE
        with self._lock:
            self.profiles[cid] = profile
        conn.sendall(json.dumps(
            {"error": None, "result": {
                "hello": "vulcan", "version": content.SAVE_VERSION,
                "profile": profile,
                "profiles": sorted(rights.VULCAN_PROFILES),
                "zones": len(self.world.zones),
                "devices": len(self.world.devices)}}
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
                if cmd == "assume":
                    newp = str((msg.get("args") or {})
                               .get("profile", ""))
                    if newp not in rights.VULCAN_PROFILES:
                        self._send(conn, error=f"unknown profile: {newp}")
                        continue
                    with self._lock:
                        cur = self.profiles.get(cid, profile)
                        allowed = rights.can_narrow(
                            rights.VULCAN_PROFILES.get(cur),
                            rights.VULCAN_PROFILES.get(newp))
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
                resp = self.handle(cmd, msg.get("args") or {},
                                   cid=cid)
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
                self.profiles.pop(cid, None)

    def handle(self, cmd, args, cid=None):
        cmd = str(cmd)
        if cmd == "close":
            return {"error": None, "result": {"bye": True}}
        method = getattr(self.sdk, cmd, None)
        if cmd not in VulcanSDK._VALID or not callable(method):
            return {"error": f"unknown command: {cmd}", "result": None}
        if cid is not None:
            with self._lock:
                pname = self.profiles.get(cid,
                                          rights.VULCAN_DEFAULT_PROFILE)
            allowed = rights.VULCAN_PROFILES.get(pname)
            if allowed is not None and cmd not in allowed:
                try:            # rights events cross the tree
                    from ratatosk import publish
                    publish("vulcan",
                            {"cid": cid, "profile": pname, "cmd": cmd},
                            frm="vulcan", kind="right_denied")
                except Exception:
                    pass
                return {"error": f"right_denied: profile '{pname}' "
                                 f"may not '{cmd}'", "result": None}
        args = args if isinstance(args, dict) else {}
        try:
            with self._lock:
                result = method(**args)
            error = None
        except KeyError as exc:
            result, error = None, str(exc.args[0] if exc.args else exc)
        except (ValueError, TypeError) as exc:
            result, error = None, str(exc)
        except Exception as exc:             # noqa: BLE001 - wire face
            result, error = None, f"internal error: {exc!r}"
        if error is None and cmd in ("stats", "ping"):
            try:            # liveness for the Heimdall vitals panel
                from ratatosk import beat
                beat("vulcan", note=f"{cmd} ok")
            except Exception:
                pass
        if self.witness is not None \
                and cmd not in rights.VULCAN_INFO:
            try:            # every mutation lands in the attestation
                self.witness.record(cmd, list(args.values()),
                                    ok=error is None, error=error,
                                    tick=self.world.tick_count)
            except Exception:
                pass
        return {"error": error, "result": result}

    def _send(self, conn, error=None, result=None):
        try:
            conn.sendall(json.dumps({"error": error, "result": result},
                                    separators=(",", ":"),
                                    default=str).encode("utf-8") + b"\n")
        except OSError:
            pass

    def _auto_loop(self):
        next_at = time.time() + content.TICK_SECONDS_REAL
        while self.running:
            time.sleep(max(0.05, min(0.5, next_at - time.time())))
            if time.time() < next_at:
                continue
            next_at = time.time() + content.TICK_SECONDS_REAL
            try:
                self.beat_once()
            except Exception as exc:
                print(f"[vulcan] tick error: {exc}")


def main():
    server = BuildingServer(auto_tick=True)
    server.start_async()
    actual = server.port
    print(f"[vulcan] hosting building on {server.host}:{actual} "
          f"(auto-tick {content.TICK_SECONDS_REAL}s)")
    print(f"[vulcan] connect: python -m vulcan.cli --connect "
          f"{server.host} {actual}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[vulcan] shutting down")
        server.running = False


if __name__ == "__main__":
    main()
