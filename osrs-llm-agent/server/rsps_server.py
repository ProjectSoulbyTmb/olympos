import json
import os
import random
import socket
import threading
import time
from collections import deque

from game.world import World
from game.sdk import GameSDK
from game.livewatch import LiveStream

DEFAULT_PORT = 43590
MAX_LINE_BYTES = 65536
MAX_SESSIONS = 32
MAX_ACTIONS_PER_SECOND = 100
MAX_INT_ARG = 10 ** 6
PORT_ATTEMPTS = 10
CHAT_HISTORY = 60
AUTOSAVE_EVERY_TICKS = 240


class Session:
    def __init__(self, name, uim, tick_budget, seed, channel=None):
        self.name = name
        self.world = World(seed=seed, tick_budget=tick_budget, uim=uim)
        self.sdk = GameSDK(self.world)
        self.channel = channel
        self.chat_cursor = 0
        self.state_tick = None
        self.state_bytes = b""
        self.last_saved_tick = -1
        # Bounded chat feed; cross-thread appends go through GameServer._lock.
        self.chat_log = deque(maxlen=CHAT_HISTORY)


class GameServer:
    """Authoritative server for the local RSPS engine.

    Each logged-in character gets its own instanced World; one connection
    is one session. Clients speak a JSON-lines protocol:
      {"cmd": "login", "name": "...", "uim": false, "budget": 3000,
       "channel": "main"}
      {"cmd": "action", "call": "chop", "args": []}
      {"cmd": "state"}
      {"cmd": "chat", "text": "hello"}
      {"cmd": "close"}

    Sessions that pass the same `channel` see each other's presence in
    state payloads ("players") and share a chat feed piggybacked on
    every response. Snapshots persist to server/saves/ and resume by
    name on re-login (pass "fresh": true to start over).

    This is an original protocol for an original engine - it models OSRS
    mechanics but is not interoperable with the official game client.
    """

    def __init__(self, host="127.0.0.1", port=DEFAULT_PORT,
                 default_budget=3000, live_poll_s=15.0):
        self.host = host
        self.port = port
        self.default_budget = default_budget
        self.sessions = {}
        self.saves_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "saves")
        os.makedirs(self.saves_dir, exist_ok=True)
        self.channels = {}
        self._lock = threading.Lock()
        self._conn_counters = {}
        self._sock = None
        self._thread = None
        self.running = False
        # live stream: cached snapshots, version bumps on every change
        self.live_poll_s = live_poll_s
        self._live_stream = LiveStream()
        self._live_lock = threading.Lock()
        self._live_cache = {"version": 0,
                            "files": {},     # name -> {"mtime", "meta"}
                            "data": {}}      # name -> full payload
        self._live_thread = None

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
        self._live_thread = threading.Thread(target=self._live_loop,
                                             daemon=True)
        self._live_thread.start()

    def _live_loop(self):
        """Background poller: folds updater snapshots into the live
        cache, bumping `version` on every observed change."""
        while self.running:
            try:
                for change in self._live_stream.poll():
                    name = change["file"].replace(".json", "")
                    data = change["data"]
                    meta = {"mtime": change["mtime"]}
                    if name == "ge_prices":
                        meta["fetched"] = data.get("fetched")
                        meta["items"] = len(data.get("items", {}))
                    elif name == "game_updates":
                        meta["tracked"] = len(data.get("updates", []))
                        latest = (data.get("updates") or [{}])[0]
                        meta["latest_title"] = latest.get("title", "")
                    with self._live_lock:
                        self._live_cache["data"][name] = data
                        self._live_cache["files"][name] = meta
                        self._live_cache["version"] += 1
                    log = f"live: {name} updated -> v{self._live_cache['version']}"
                    print(f"[{time.strftime('%H:%M:%S')}] {log}")
            except Exception:
                pass
            time.sleep(self.live_poll_s)

    def live_summary(self, items=None):
        """Compact live payload; optional per-item GE price lookup."""
        with self._live_lock:
            snap = {"version": self._live_cache["version"],
                    "files": json.loads(json.dumps(
                        self._live_cache["files"]))}
        prices = self._live_stream.latest("ge_prices.json") or {}
        wanted = []
        if items:
            table = prices.get("items", {})
            for it in items:
                entry = table.get(it)
                if entry:
                    wanted.append({"item": it, "high": entry.get("high"),
                                   "low": entry.get("low"),
                                   "limit": entry.get("limit")})
        snap["prices"] = wanted
        return snap

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
        bound = False
        for attempt in range(PORT_ATTEMPTS):
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(0.3)
            busy = probe.connect_ex(
                (self.host if self.host != "0.0.0.0" else "127.0.0.1",
                 self.port + attempt)) == 0
            probe.close()
            if busy:
                continue
            try:
                self._sock.bind((self.host, self.port + attempt))
                if attempt:
                    print("[rsps] port %d busy, bound to %d"
                          % (self.port, self.port + attempt))
                    self.port += attempt
                bound = True
                break
            except OSError:
                self._sock.close()
                self._sock = socket.socket(socket.AF_INET,
                                           socket.SOCK_STREAM)
                self._sock.setsockopt(socket.SOL_SOCKET,
                                      socket.SO_REUSEADDR, 1)
                continue
        assert bound, "no free port found"
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
        with self._lock:
            full = len(self.sessions) >= MAX_SESSIONS
        if full:
            conn.sendall(b'{"ok": false, "error": "server full"}\n')
            conn.close()
            return
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sess = None
        self._conn_counters[id(conn)] = {"window": time.time(),
                                         "count": 0}
        f = conn.makefile("r")
        try:
            for raw_line in f:
                if len(raw_line) > MAX_LINE_BYTES:
                    continue
                line = raw_line.strip()
                if not line:
                    continue
                bucket = self._conn_counters.get(id(conn))
                now = time.time()
                if now - bucket["window"] > 1:
                    bucket["window"] = now
                    bucket["count"] = 0
                bucket["count"] += 1
                if bucket["count"] > MAX_ACTIONS_PER_SECOND:
                    resp = {"ok": False,
                            "error": "rate limit exceeded; slow down"}
                    conn.sendall((json.dumps(resp) + "\n").encode())
                    continue
                try:
                    req = json.loads(line)
                except json.JSONDecodeError as e:
                    resp = {"ok": False, "error": f"bad request: {e}"}
                    conn.sendall((json.dumps(resp) + "\n").encode())
                    continue
                # Hyperion-style cycle watchdog: slow handlers are visible.
                t0 = time.perf_counter()
                cmd = req.get("cmd")
                if cmd == "login":
                    name = str(req.get("name") or
                               f"player_{random.randint(100, 999)}")
                    channel = str(req.get("channel") or "").strip() or None
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
                                seed=random.randint(0, 2 ** 31 - 1),
                                channel=channel)
                            resumed, note = self._try_resume(sess, req)
                            self.sessions[name] = sess
                            if channel:
                                room = self.channels.setdefault(channel,
                                                                deque())
                                for other in room:
                                    o = self.sessions.get(other)
                                    if o:
                                        o.world.note(
                                            f"{name} entered the world")
                                room.append(name)
                            resp = {"ok": True, "name": name,
                                    "resumed": resumed,
                                    "state": sess.world.state()}
                            if note:
                                resp["note"] = note
                elif sess is None:
                    resp = {"ok": False, "error": "not logged in"}
                elif cmd == "state":
                    if sess.channel:
                        st = sess.world.state()
                        st["players"] = self._presence(sess)
                        resp = {"ok": True, "state": st}
                    else:
                        conn.sendall(GameServer._state_bytes(sess))
                        continue
                elif cmd == "docs":
                    from game.knowledge import render_markdown
                    resp = {"ok": True, "docs": render_markdown()}
                elif cmd == "live":
                    resp = {"ok": True,
                            "live": self.live_summary(req.get("items"))}
                elif cmd == "chat":
                    text = str(req.get("text", "")).strip()[:200]
                    if not text:
                        resp = {"ok": False, "error": "empty chat"}
                    else:
                        self._broadcast_chat(sess, text)
                        resp = {"ok": True}
                elif cmd == "action":
                    resp = self._run_action(sess, req)
                elif cmd == "close":
                    self._persist(sess)
                    resp = {"ok": True}
                    conn.sendall((json.dumps(resp) + "\n").encode())
                    break
                else:
                    resp = {"ok": False, "error": f"unknown cmd '{cmd}'"}
                if sess is not None:
                    resp["chat"] = self._drain_chat(sess)
                    players = self._presence(sess)
                    if players:
                        st = resp.get("state")
                        if isinstance(st, dict):
                            st["players"] = players
                    if sess.world.tick - sess.last_saved_tick \
                            >= AUTOSAVE_EVERY_TICKS:
                        self._persist(sess)
                conn.sendall((json.dumps(resp) + "\n").encode())
        except (ConnectionError, OSError):
            pass
        finally:
            self._conn_counters.pop(id(conn), None)
            if sess is not None:
                with self._lock:
                    self.sessions.pop(sess.name, None)
                self._leave_channel(sess)
                self._persist(sess)
            try:
                conn.close()
            except OSError:
                pass

    # ---------- channels / chat / persistence ----------

    def _save_path(self, name):
        safe = "".join(c for c in name
                       if c.isalnum() or c in "-_")[:40] or "player"
        return os.path.join(self.saves_dir, f"{safe}.json")

    def _try_resume(self, sess, req):
        path = self._save_path(sess.name)
        if req.get("fresh") or not os.path.exists(path):
            return False, None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                snap = json.load(fh)
            sess.world.load_snapshot(snap)
            sess.last_saved_tick = sess.world.tick
            return True, f"resumed {sess.name} (tick {sess.world.tick})"
        except Exception as exc:
            sess.world.reset()
            return False, f"resume failed ({exc}); fresh start"

    def _persist(self, sess):
        try:
            snap = sess.world.save()
            sess.last_saved_tick = sess.world.tick
            tmp = self._save_path(sess.name) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(snap, fh)
            os.replace(tmp, self._save_path(sess.name))
        except OSError:
            pass

    def _broadcast_chat(self, sess, text):
        line = {"from": sess.name, "text": text,
                "t": sess.world.tick}
        targets = [s for s in self.sessions.values()
                   if s.channel and s.channel == sess.channel]
        for target in targets:
            target.chat_log = getattr(target, "chat_log", deque())
            target.chat_log.append(line)

    def _drain_chat(self, sess):
        log = getattr(sess, "chat_log", None)
        if not log:
            return []
        out = list(log)
        log.clear()
        return out

    def _presence(self, sess):
        if not sess.channel:
            return []
        players = []
        for other in self.channels.get(sess.channel, ()):
            if other == sess.name:
                continue
            o = self.sessions.get(other)
            if o is not None:
                players.append({"name": o.name,
                                "pos": list(o.world.pos)})
        return players

    def _leave_channel(self, sess):
        channel = sess.channel
        if not channel:
            return
        room = self.channels.get(channel)
        if room and sess.name in room:
            room.remove(sess.name)
            for other in room:
                o = self.sessions.get(other)
                if o:
                    o.world.note(f"{sess.name} left the world")
                    o.chat_log = getattr(o, "chat_log", deque())
                    o.chat_log.append({"from": "system",
                                       "text": f"{sess.name} left",
                                       "t": o.world.tick})

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
        args = list(req.get("args", []))
        for a in args:
            if isinstance(a, bool):
                continue
            if isinstance(a, int) and abs(a) > MAX_INT_ARG:
                return {"ok": False,
                        "error": "numeric argument out of range"}
            if isinstance(a, str) and len(a) > 200:
                return {"ok": False, "error": "string argument too long"}
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
