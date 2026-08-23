import json
import random
import socket
import threading

from game.world import World
from game.sdk import GameSDK

DEFAULT_PORT = 43590


class Session:
    def __init__(self, name, uim, tick_budget, seed):
        self.name = name
        self.world = World(seed=seed, tick_budget=tick_budget, uim=uim)
        self.sdk = GameSDK(self.world)
        self.state_tick = None
        self.state_bytes = b""


class GameServer:
    """Authoritative server for the local RSPS engine.

    Each logged-in character gets its own instanced World; one connection
    is one session. Clients speak a JSON-lines protocol:
      {"cmd": "login", "name": "...", "uim": false, "budget": 3000}
      {"cmd": "action", "call": "chop", "args": []}
      {"cmd": "state"}
      {"cmd": "close"}

    This is an original protocol for an original engine - it models OSRS
    mechanics but is not interoperable with the official game client.
    """

    def __init__(self, host="127.0.0.1", port=DEFAULT_PORT,
                 default_budget=3000):
        self.host = host
        self.port = port
        self.default_budget = default_budget
        self.sessions = {}
        self._lock = threading.Lock()
        self._sock = None
        self._thread = None
        self.running = False

    @property
    def player_count(self):
        return len(self.sessions)

    def start_async(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self.serve_forever,
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def serve_forever(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(8)
        self._sock.settimeout(0.5)
        while self.running:
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self.running:
                    break
                raise
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    def _handle(self, conn):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sess = None
        f = conn.makefile("r")
        try:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                except json.JSONDecodeError as e:
                    resp = {"ok": False, "error": f"bad request: {e}"}
                    conn.sendall((json.dumps(resp) + "\n").encode())
                    continue
                cmd = req.get("cmd")
                if cmd == "login":
                    name = str(req.get("name") or
                               f"player_{random.randint(100, 999)}")
                    with self._lock:
                        if name in self.sessions:
                            resp = {"ok": False,
                                    "error": f"name '{name}' already online"}
                        else:
                            sess = Session(
                                name,
                                uim=bool(req.get("uim")),
                                tick_budget=int(req.get(
                                    "budget", self.default_budget)),
                                seed=random.randint(0, 2 ** 31 - 1))
                            self.sessions[name] = sess
                            resp = {"ok": True, "name": name,
                                    "state": sess.world.state()}
                elif sess is None:
                    resp = {"ok": False, "error": "not logged in"}
                elif cmd == "state":
                    conn.sendall(GameServer._state_bytes(sess))
                    continue
                elif cmd == "docs":
                    from game.knowledge import render_markdown
                    resp = {"ok": True, "docs": render_markdown()}
                elif cmd == "action":
                    resp = self._run_action(sess, req)
                elif cmd == "close":
                    resp = {"ok": True}
                    conn.sendall((json.dumps(resp) + "\n").encode())
                    break
                else:
                    resp = {"ok": False, "error": f"unknown cmd '{cmd}'"}
                conn.sendall((json.dumps(resp) + "\n").encode())
        except (ConnectionError, OSError):
            pass
        finally:
            if sess is not None:
                with self._lock:
                    self.sessions.pop(sess.name, None)
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _state_bytes(sess):
        if sess.state_tick != sess.world.tick or sess.state_bytes == b"":
            payload = {"ok": True, "state": sess.world.state()}
            sess.state_bytes = (json.dumps(payload) + "\n").encode()
            sess.state_tick = sess.world.tick
        return sess.state_bytes

    @staticmethod
    def _run_action(sess, req):
        call = str(req.get("call"))
        args = req.get("args", [])
        fn = getattr(sess.sdk, call, None)
        if fn is None or call.startswith("_"):
            return {"ok": False, "error": f"unknown action '{call}'"}
        try:
            result = fn(*args)
            return {"ok": True, "result": result,
                    "state": sess.world.state()}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}",
                    "state": sess.world.state()}
