import json
import socket


class RspsError(Exception):
    pass


class RemoteGameSDK:
    """Drop-in replacement for GameSDK that executes every action on a
    remote GameServer session. Strategies written against the local SDK
    run unchanged over the wire."""

    def __init__(self, host="127.0.0.1", port=43590, name="player",
                 uim=False, budget=3000, timeout=15):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f = self.sock.makefile("r")
        resp = self._request({"cmd": "login", "name": name, "uim": uim,
                              "budget": budget})
        if not resp.get("ok"):
            raise RspsError(resp.get("error", "login failed"))
        self.name = resp["name"]
        self._state = resp.get("state")

    def _request(self, payload):
        self.sock.sendall((json.dumps(payload) + "\n").encode())
        line = self.f.readline()
        if not line:
            raise ConnectionError("server closed the connection")
        return json.loads(line)

    def _call(self, call, *args):
        resp = self._request({"cmd": "action", "call": call,
                              "args": list(args)})
        self._state = resp.get("state", self._state)
        if not resp.get("ok"):
            raise RspsError(resp.get("error", "action failed"))
        return resp.get("result")

    def state(self):
        resp = self._request({"cmd": "state"})
        if not resp.get("ok"):
            raise RspsError(resp.get("error"))
        self._state = resp["state"]
        return self._state

    def docs(self):
        resp = self._request({"cmd": "docs"})
        if not resp.get("ok"):
            raise RspsError(resp.get("error"))
        return resp["docs"]

    def skills(self):
        return {s: v["level"] for s, v in self.state()["skills"].items()}

    def inventory(self):
        inv = {}
        for part in str(self.state().get("inventory", "")).split(","):
            part = part.strip()
            if not part or part == "(empty)":
                continue
            name, _, count = part.rpartition(" x")
            inv[name] = int(count)
        return inv

    def coins(self):
        return self.state()["coins"]

    def ticks_left(self):
        return self.state()["ticks_left"]

    def log(self):
        return list(self.state().get("events", []))

    def quest_status(self):
        return dict(self.state().get("quests", {}))

    def move_to(self, x, y):
        return self._call("move_to", int(x), int(y))

    def walk(self, place_name):
        return self._call("walk", place_name)

    def chop(self):
        return self._call("chop")

    def mine(self):
        return self._call("mine")

    def fish(self):
        return self._call("fish")

    def cook(self, raw_item=None):
        return self._call("cook", raw_item)

    def light_fire(self):
        return self._call("light_fire")

    def smelt(self, bar):
        return self._call("smelt", bar)

    def talk_quest(self, quest=None):
        return self._call("talk_quest", quest)

    def deposit_all(self):
        return self._call("deposit_all")

    def deposit(self, item, n=None):
        return self._call("deposit", item, n)

    def withdraw(self, item, n=None):
        return self._call("withdraw", item, n)

    def sell(self, item, n=None):
        return self._call("sell", item, n)

    def buy(self, item, n=None):
        args = [item] + ([int(n)] if n else [])
        return self._call("buy", *args)

    def drop(self, item, n=None):
        return self._call("drop", item, n)

    def wait(self, ticks=1):
        return self._call("wait", ticks)

    def set_run(self, on):
        return self._call("set_run", bool(on))

    def live(self, items=None):
        """Live updater stream: version + optional GE price lookups."""
        payload = {"cmd": "live"}
        if items:
            payload["items"] = list(items)
        resp = self._request(payload)
        if not resp.get("ok"):
            raise RspsError(resp.get("error", "live failed"))
        return resp["live"]

    def npcs(self):
        return self._call("npcs")

    def attack(self, npc_name):
        return self._call("attack", npc_name)

    def eat(self, item):
        return self._call("eat", item)

    def set_combat_style(self, style):
        return self._call("set_combat_style", style)

    def shop_prices(self):
        return self._call("shop_prices")

    def shop_stock(self):
        return self._call("shop_stock")

    def close(self):
        try:
            self.sock.sendall((json.dumps({"cmd": "close"}) + "\n").encode())
            self.sock.close()
        except OSError:
            pass
