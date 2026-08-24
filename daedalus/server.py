"""DAEDALUS authoritative server - the workshop's wire face.

JSON-lines on 127.0.0.1:43905. NORN rights: watchers observe builds,
operators submit and steer them.
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

from daedalus.kernel import Workshop
from daedalus import content

try:
    import norn.rights as rights
except ImportError:                 # pragma: no cover
    rights = None
try:
    from norn.witness import Witness
except ImportError:                 # pragma: no cover
    Witness = None


class DaedalusServer:
    def __init__(self, host=None, port=None, workshop=None):
        self.host = host or content.SERVER_HOST
        self.port = content.SERVER_PORT if port is None else port
        self.ws = workshop or Workshop()
        self.sessions = {}
        self.profiles = {}
        self._lock = threading.Lock()
        self._next_conn = 0
        self._sock = None
        self._thread = None
        self.running = False
        self.witness = None
        if Witness is not None:
            try:
                wdir = os.environ.get("NORN_WITNESS_DIR") or os.path.join(
                    ROOT, "data", "witness")
                self.witness = Witness(wdir, actor="daedalus")
            except Exception:     # noqa: BLE001
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
                    getattr(rights, "DAEDALUS_DEFAULT_PROFILE",
                            "operator") if rights else "operator")
            threading.Thread(target=self._client_loop,
                             args=(conn, cid), daemon=True).start()

    def _deny(self, conn):
        try:
            conn.sendall(json.dumps(
                {"error": "server full", "result": None})
                .encode("utf-8") + b"\n")
        finally:
            conn.close()

    def _client_loop(self, conn, cid):
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
                resp = self.handle(msg.get("cmd"),
                                   msg.get("args") or {}, cid=cid)
                self._send(conn, **resp)
                if str(msg.get("cmd")) == "close":
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
        method = getattr(self, f"api_{cmd}", None)
        if method is None:
            return {"error": f"unknown command: {cmd}", "result": None}
        if rights is not None and cid is not None:
            pname = self.profiles.get(cid, "operator")
            allowed = rights.DAEDALUS_PROFILES.get(pname)
            if allowed is not None and cmd not in allowed:
                return {"error": f"right_denied: profile '{pname}' "
                                 f"may not '{cmd}'", "result": None}
        args = args if isinstance(args, dict) else {}
        mutating = cmd not in ("status", "builds", "blueprints", "close")
        result, error = None, None
        try:
            result = method(**args)
        except KeyError as exc:
            error = str(exc.args[0] if exc.args else exc)
        except (ValueError, TypeError) as exc:
            error = str(exc)
        except Exception as exc:          # noqa: BLE001 - wire face
            error = f"internal error: {exc!r}"
        if mutating and self.witness is not None:
            try:
                self.witness.record(cmd, list(args.values()),
                                    ok=error is None, error=error)
            except Exception:             # noqa: BLE001
                pass
        return {"error": error, "result": result}

    # ---- api surface (also the rights table source of truth) ----

    def api_status(self):
        return self.ws.status()

    def api_builds(self):
        return {"queue": [j["id"] for j in list(self.ws.queue)],
                "history": list(self.ws.history)[-20:]}

    def api_blueprints(self):
        from daedalus import blueprints as bp
        return {"available": bp.blueprint_names(),
                **{k: v["description"]
                   for k, v in bp.BLUEPRINTS.items()}}

    def api_build(self, spec):
        job = self.ws.submit(spec)
        r = self.ws.build_next()
        return {"submitted": job, "outcome": r}

    def api_lane_drain(self, max_jobs=8):
        """Drive the queue (used by the daemon loop + tests)."""
        done = []
        for _ in range(int(max_jobs)):
            r = self.ws.build_next()
            if r is None:
                break
            done.append(r)
        findings = self.ws.warden.patrol()
        return {"drained": len(done), "results": done,
                "warden_findings": findings}

    def api_fleet_drain(self, max_jobs=None):
        """Parallel drain: every free lane weaves simultaneously."""
        r = self.ws.drain_parallel(max_jobs)
        findings = self.ws.warden.patrol()
        return {"drained": r["drained"], "results": r["results"],
                "warden_findings": findings}

    def api_pump_start(self):
        return {"running": self.ws.pump_start()}

    def api_pump_stop(self):
        stopped = self.ws.pump_stop()
        return {"was_running": stopped, "running": self.ws.pump_running()}

    def api_pump_status(self):
        return {"running": self.ws.pump_running(),
                "queued": len(self.ws.queue),
                "lanes_busy": self.ws.fleet.busy_count()}

    @staticmethod
    def _send(conn, error=None, result=None):
        try:
            conn.sendall(json.dumps({"error": error, "result": result},
                                    separators=(",", ":"),
                                    default=str).encode("utf-8") + b"\n")
        except OSError:
            pass


def main():
    server = DaedalusServer()
    server.start_async()
    print(f"[daedalus] workshop on {server.host}:{server.port}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.running = False


if __name__ == "__main__":
    main()
