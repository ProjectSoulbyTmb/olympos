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
TRADE_TIMEOUT_S = 60.0


class TradeSession:
    """Two-player item/coin exchange. Offers are staged per side and
    validated against live inventories at execution time under the
    server lock, so items can never be duplicated."""

    def __init__(self, a, b):
        self.parties = (a, b)
        self.offers = {a: {"items": {}, "coins": 0},
                       b: {"items": {}, "coins": 0}}
        self.confirmed = {a: False, b: False}
        self.created = time.time()

    def other(self, name):
        return self.parties[1] if self.parties[0] == name \
            else self.parties[0]

    def view(self, name):
        me, them = self.offers[name], self.offers[self.other(name)]
        return {"my_offer": dict(me["items"]),
                "my_coins": me["coins"],
                "their_offer": dict(them["items"]),
                "their_coins": them["coins"],
                "i_confirmed": self.confirmed[name],
                "they_confirmed": self.confirmed[self.other(name)],
                "with": self.other(name)}


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
        self.notices = deque(maxlen=20)


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
        self.trades = {}          # player name -> TradeSession
        self.trade_invites = {}   # invitee name -> inviter name
        self.started = time.time()
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
                elif cmd == "status":
                    with self._lock:
                        resp = {"ok": True, "status": {
                            "uptime_s": round(time.time() - self.started,
                                              1),
                            "players": {n: {"channel": s.channel,
                                            "tick": s.world.tick}
                                        for n, s in
                                        self.sessions.items()},
                            "channels": sorted(self.channels),
                            "trades_active": len(self.trades),
                        }}
                elif cmd == "trade_offer":
                    target = str(req.get("target", "")).strip()
                    resp = self._trade_offer(sess, target)
                elif cmd == "trade_accept":
                    resp = self._trade_accept_invite(sess)
                elif cmd == "trade_decline":
                    self.trade_invites.pop(sess.name, None)
                    resp = {"ok": True}
                elif cmd in ("trade_add", "trade_remove",
                             "trade_add_coins", "trade_confirm",
                             "trade_cancel"):
                    resp = self._trade_cmd(sess, cmd, req)
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
                    notices = self._drain_notices(sess)
                    if notices:
                        resp["notices"] = notices
                    players = self._presence(sess)
                    if players:
                        st = resp.get("state")
                        if isinstance(st, dict):
                            st["players"] = players
                    trade = self._trade_view(sess)
                    if trade:
                        resp["trade"] = trade
                    if sess.world.tick - sess.last_saved_tick \
                            >= AUTOSAVE_EVERY_TICKS:
                        self._persist(sess)
                conn.sendall((json.dumps(resp) + "\n").encode())
                dt = time.perf_counter() - t0
                if dt > 0.5:
                    print("[%s] watchdog: '%s' took %.2fs"
                          % (time.strftime("%H:%M:%S"),
                             req.get("cmd", "?"), dt))
        except (ConnectionError, OSError):
            pass
        finally:
            self._conn_counters.pop(id(conn), None)
            if sess is not None:
                with self._lock:
                    self.sessions.pop(sess.name, None)
                self._leave_channel(sess)
                self._cleanup_disconnect(sess)
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
        # Single-writer rule (RuneSource): cross-session effects are
        # serialized on the server lock, never raced from IO threads.
        with self._lock:
            targets = [self.sessions[n]
                       for n in self.channels.get(sess.channel or (), ())
                       if n != sess.name and n in self.sessions]
            for target in targets:
                target.chat_log.append(line)

    def _drain_chat(self, sess):
        with self._lock:
            log = sess.chat_log
            out = list(log)
            log.clear()
        return out

    def _presence(self, sess):
        if not sess.channel:
            return []
        players = []
        with self._lock:
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
        with self._lock:
            room = self.channels.get(channel)
            if room and sess.name in room:
                room.remove(sess.name)
                for other in room:
                    o = self.sessions.get(other)
                    if o:
                        o.world.note(f"{sess.name} left the world")
                        o.chat_log.append({"from": "system",
                                           "text": f"{sess.name} left",
                                           "t": o.world.tick})

    # ---------- trading ----------

    def _trade_offer(self, sess, target):
        with self._lock:
            if not target or target == sess.name:
                return {"ok": False, "error": "bad trade target"}
            if sess.name in self.trades:
                return {"ok": False, "error": "already in a trade"}
            if sess.name in self.trade_invites:
                return {"ok": False,
                        "error": "you have a pending invite - "
                                 "accept or decline it first"}
            other = self.sessions.get(target)
            if other is None:
                return {"ok": False, "error": f"'{target}' is offline"}
            if other.name in self.trades \
                    or other.name in self.trade_invites:
                return {"ok": False,
                        "error": f"{target} is busy trading"}
            self.trade_invites[other.name] = sess.name
            self._push_notice(other, {"type": "trade_invite",
                                      "from": sess.name})
            return {"ok": True,
                    "result": f"trade invite sent to {target}"}

    def _trade_accept_invite(self, sess):
        with self._lock:
            inviter = self.trade_invites.pop(sess.name, None)
            if not inviter:
                return {"ok": False, "error": "no pending trade invite"}
            other = self.sessions.get(inviter)
            if other is None:
                return {"ok": False, "error": "inviter went offline"}
            ts = TradeSession(sess.name, other.name)
            self.trades[sess.name] = ts
            self.trades[other.name] = ts
            self._push_notice(other, {"type": "trade_open",
                                      "with": sess.name})
            return {"ok": True, "result": ts.view(sess.name)}

    def _trade_cmd(self, sess, cmd, req):
        with self._lock:
            ts = self.trades.get(sess.name)
            if ts is None:
                return {"ok": False, "error": "not in a trade"}
            if time.time() - ts.created > TRADE_TIMEOUT_S * 12:
                self._cancel_trade(ts, "timed out")
                return {"ok": False, "error": "trade timed out"}
            mine = ts.offers[sess.name]
            if cmd == "trade_add":
                item = str(req.get("item", ""))
                n = max(1, int(req.get("n", 1)))
                have = sess.world.inventory.get(item, 0)
                staged = mine["items"].get(item, 0)
                if have - staged < n:
                    return {"ok": False,
                            "error": f"you only have {have - staged} "
                                     f"free {item}"}
                mine["items"][item] = staged + n
                ts.confirmed = {p: False for p in ts.parties}
            elif cmd == "trade_remove":
                item = str(req.get("item", ""))
                staged = mine["items"].get(item, 0)
                n = int(req.get("n") or staged)
                left = staged - min(n, staged)
                if left > 0:
                    mine["items"][item] = left
                else:
                    mine["items"].pop(item, None)
                ts.confirmed = {p: False for p in ts.parties}
            elif cmd == "trade_add_coins":
                n = max(0, min(int(req.get("n", 0)),
                               MAX_INT_ARG))
                if n > sess.world.coins:
                    return {"ok": False,
                            "error": f"you only have "
                                     f"{sess.world.coins} coins"}
                mine["coins"] = n
                ts.confirmed = {p: False for p in ts.parties}
            elif cmd == "trade_confirm":
                ts.confirmed[sess.name] = True
                if all(ts.confirmed.values()):
                    return self._execute_trade(ts)
            elif cmd == "trade_cancel":
                self._cancel_trade(ts, f"{sess.name} cancelled")
                return {"ok": True, "result": "trade cancelled"}
            return {"ok": True}

    def _execute_trade(self, ts):
        """Both confirmed: re-validate ownership live, then swap."""
        a_name, b_name = ts.parties
        a, b = self.sessions[a_name], self.sessions[b_name]
        for side, giver in ((a_name, a.world), (b_name, b.world)):
            offer = ts.offers[side]
            if offer["coins"] > giver.coins or \
                    any(giver.inventory.get(i, 0) < n for i, n
                        in offer["items"].items()):
                self._cancel_trade(ts, "offer no longer valid - aborted")
                return {"ok": False, "error": "trade aborted"}
        for side, giver, taker in ((a_name, a.world, b.world),
                                   (b_name, b.world, a.world)):
            offer = ts.offers[side]
            for item, n in offer["items"].items():
                giver.inventory[item] -= n
                if giver.inventory[item] <= 0:
                    del giver.inventory[item]
                taker.inv_add(item, n)
            if offer["coins"]:
                giver.coins -= offer["coins"]
                taker.coins += offer["coins"]
        summary = "; ".join(
            f"{name}: " + (", ".join(f"{i} x{n}" for i, n in
                                     ts.offers[name]["items"].items())
                           or "-") +
            (f" +{ts.offers[name]['coins']}c"
             if ts.offers[name]["coins"] else "")
            for name in ts.parties)
        for s in (a, b):
            s.world.note(f"trade complete with {ts.other(s.name)}")
        self._end_trade(ts)
        self._push_notice(a, {"type": "trade_done"})
        self._push_notice(b, {"type": "trade_done"})
        return {"ok": True, "result": f"traded! {summary}"}

    def _cancel_trade(self, ts, reason):
        for name in ts.parties:
            s = self.sessions.get(name)
            if s:
                s.world.note(f"trade cancelled ({reason})")
                self._push_notice(s, {"type": "trade_cancelled"})
            self.trades.pop(name, None)

    def _end_trade(self, ts):
        for name in ts.parties:
            self.trades.pop(name, None)

    def _trade_view(self, sess):
        ts = self.trades.get(sess.name)
        return ts.view(sess.name) if ts else None

    def _push_notice(self, sess, notice):
        sess.notices.append(notice)

    def _drain_notices(self, sess):
        if not sess.notices:
            return []
        out = list(sess.notices)
        sess.notices.clear()
        return out

    def _cleanup_disconnect(self, sess):
        ts = self.trades.pop(sess.name, None)
        if ts:
            other = ts.other(sess.name)
            self.trades.pop(other, None)
            o = self.sessions.get(other)
            if o:
                o.world.note("trade cancelled (partner disconnected)")
                self._push_notice(o, {"type": "trade_cancelled"})
        self.trade_invites.pop(sess.name, None)
        stale = [invitee for invitee, src in self.trade_invites.items()
                 if src == sess.name]
        for invitee in stale:
            self.trade_invites.pop(invitee, None)

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
