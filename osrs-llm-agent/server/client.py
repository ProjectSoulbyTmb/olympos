import json
import socket


class RspsError(Exception):
    pass


class RemoteGameSDK:
    """Drop-in replacement for GameSDK that executes every action on a
    remote GameServer session. Strategies written against the local SDK
    run unchanged over the wire."""

    def __init__(self, host="127.0.0.1", port=43590, name="player",
                 uim=False, budget=3000, timeout=15, channel=None,
                 fresh=False):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f = self.sock.makefile("r")
        resp = self._request({"cmd": "login", "name": name, "uim": uim,
                              "budget": budget, "channel": channel,
                              "fresh": fresh})
        if not resp.get("ok"):
            raise RspsError(resp.get("error", "login failed"))
        self.name = resp["name"]
        self.resumed = bool(resp.get("resumed"))
        self._chat = []
        self._state = resp.get("state")

    def chat(self, text):
        resp = self._request({"cmd": "chat", "text": str(text)[:200]})
        if not resp.get("ok"):
            raise RspsError(resp.get("error", "chat failed"))
        return True

    def _drain_chat(self):
        out = list(self._chat)
        self._chat = []
        return out

    def _request(self, payload):
        self.sock.sendall((json.dumps(payload) + "\n").encode())
        line = self.f.readline()
        if not line:
            raise ConnectionError("server closed the connection")
        resp = json.loads(line)
        chat = resp.get("chat")
        if chat:
            self._chat.extend(chat)
        return resp

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

    def skills(self, name=None):
        if name is None:
            return {s: v["level"]
                    for s, v in self.state()["skills"].items()}
        return self._call("skills", name)

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

    def cut_planks(self, log=None):
        return self._call("cut_planks", log)

    def build(self, furniture):
        return self._call("build", furniture)

    def lay_trap(self):
        return self._call("lay_trap")

    def check_trap(self):
        return self._call("check_trap")

    def call(self, name, *args):
        """Generic passthrough for any GameSDK action over the wire."""
        return self._call(name, *args)

    def eat(self, item):
        return self._call("eat", item)

    def cast(self, spell, npc_name):
        return self._call("cast", spell, npc_name)

    def bury_bones(self):
        return self._call("bury_bones")

    def offer_bones(self):
        return self._call("offer_bones")

    def craft_rune(self, rune):
        return self._call("craft_rune", rune)

    def thieve(self, stall):
        return self._call("thieve", stall)

    def run_lap(self):
        return self._call("run_lap")

    def plant(self, seed):
        return self._call("plant", seed)

    def harvest(self):
        return self._call("harvest")

    def make_potion(self, potion):
        return self._call("make_potion", potion)

    def quaff(self, potion):
        return self._call("quaff", potion)

    def fletch(self, log=None):
        return self._call("fletch", log)

    def craft_leather(self, item):
        return self._call("craft_leather", item)

    def assign_slayer(self):
        return self._call("assign_slayer")

    def claim_slayer(self):
        return self._call("claim_slayer")

    def search_chest(self):
        return self._call("search_chest")

    def get_location(self):
        return self._call("get_location")

    def close(self):
        try:
            self.sock.sendall((json.dumps({"cmd": "close"}) + "\n").encode())
            self.sock.close()
        except OSError:
            pass
