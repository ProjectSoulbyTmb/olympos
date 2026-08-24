"""Vulcan SDK - the ONLY surface strategies/dashboards see.

Two interchangeable faces:
  VulcanSDK    in-process facade over World + RuleEngine
  VulcanClient JSON-lines TCP client speaking to a hosted BuildingServer

Both expose identical method names, so any automation written against
one runs unchanged against the other.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import json
import socket

import content


class VulcanSDK:
    """In-process facade. Raises ValueError/KeyError on bad intents."""

    _VALID = {
        "ping", "state", "zones", "zone", "devices", "device",
        "set_device", "set_hvac", "motion", "contact", "smoke",
        "outside_temp", "scene", "mode", "rules", "add_rule",
        "toggle_rule", "delete_rule", "alerts", "events", "stats",
        "tick", "save", "load",
    }

    def __init__(self, world, rule_engine):
        self.world = world
        self.engine = rule_engine

    # ---- info ----

    def ping(self):
        return {"pong": True, "service": "vulcan"}

    def state(self):
        snap = self.world.snapshot()
        snap["building"]["rules_active"] = sum(
            1 for r in self.engine.rules if r["enabled"])
        return snap

    def zones(self):
        return {n: z.snapshot() for n, z in self.world.zones.items()}

    def zone(self, name):
        if name not in self.world.zones:
            raise KeyError(f"unknown zone: {name}")
        return self.world.zones[name].snapshot()

    def devices(self, zone=None, dtype=None):
        out = []
        for d in self.world.devices.values():
            if zone and d.zone != zone:
                continue
            if dtype and d.type != dtype:
                continue
            out.append(d.snapshot())
        return sorted(out, key=lambda d: d["id"])

    def device(self, dev_id):
        dev = self.world.devices.get(dev_id)
        if dev is None:
            raise KeyError(f"unknown device: {dev_id}")
        return dev.snapshot()

    # ---- control ----

    def set_device(self, dev_id, **changes):
        return self.world.set_device(dev_id, changes)

    def set_hvac(self, zone, mode=None, target=None):
        changes = {}
        if mode is not None:
            changes["mode"] = mode
        if target is not None:
            changes["target"] = target
        if not changes:
            raise ValueError("nothing to set: pass mode and/or target")
        return self.world.set_hvac(zone, changes)

    def motion(self, zone, people=1):
        return self.world.motion(zone, people)

    def contact(self, dev_id, is_open):
        result = self.world.set_contact(dev_id, is_open)
        return result

    def smoke(self, dev_id, active=True):
        return self.world.smoke_alarm(dev_id, active)

    def outside_temp(self, celsius):
        self.world.set_outside_temp(celsius)
        return {"outside_c": self.world.outside_temp}

    def scene(self, name):
        self.world.apply_scene(name)
        return {"scene": name}

    def mode(self, name):
        self.world.set_mode(name)
        return {"mode": self.world.mode}

    # ---- automation ----

    def rules(self):
        return self.engine.list_rules()

    def add_rule(self, spec):
        return {k: v for k, v in self.engine.add_rule(spec).items()
                if not k.startswith("_")}

    def toggle_rule(self, rule_id, enabled=None):
        rule = self.engine.toggle_rule(rule_id, enabled)
        return {"id": rule["id"], "enabled": rule["enabled"]}

    def delete_rule(self, rule_id):
        self.engine.delete_rule(rule_id)
        return {"deleted": rule_id}

    # ---- telemetry / time ----

    def alerts(self, n=20):
        return list(self.world.alerts)[-int(n):]

    def events(self, n=20):
        return list(self.world.events)[-int(n):]

    def stats(self, n=60):
        return list(self.world.stats)[-int(n):]

    def tick(self, n=1):
        results = []
        for _ in range(max(1, min(int(n), 1000))):
            results.append(self.world.tick(rule_engine=self.engine))
        return results[-1]

    def save(self, path):
        self.world.save(path, extra={"automation":
                                     self.engine.export_state()})
        return {"saved": path, "version": content.SAVE_VERSION}

    def load(self, path):
        data = self.world.load(path)
        restored = self.engine.import_state(data.get("automation"))
        return {"loaded": path, "mode": self.world.mode,
                "rules_restored": restored,
                "kwh_total": round(self.world.kwh_total, 3)}


class VulcanClient:
    """Wire client with the same method surface as VulcanSDK."""

    def __init__(self, host=None, port=None, timeout=5.0):
        self.host = host or content.SERVER_HOST
        self.port = port or content.SERVER_PORT
        self.timeout = timeout
        self._sock = None
        self._fh = None

    def connect(self):
        self._sock = socket.create_connection((self.host, self.port),
                                              timeout=self.timeout)
        self._fh = self._sock.makefile("rwb")
        hello = json.loads(self._fh.readline().decode("utf-8"))
        return hello

    def close(self):
        try:
            self._call("close")
        except OSError:
            pass
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def _call(self, cmd, **args):
        if self._fh is None:
            raise ConnectionError("not connected; call connect()")
        payload = json.dumps({"cmd": cmd, "args": args},
                             separators=(",", ":"))
        if len(payload.encode("utf-8")) > content.MAX_LINE_BYTES:
            raise ValueError("request too large")
        self._fh.write(payload.encode("utf-8") + b"\n")
        self._fh.flush()
        line = self._fh.readline()
        if not line:
            raise ConnectionError("server closed connection")
        resp = json.loads(line.decode("utf-8"))
        if resp.get("error"):
            err = resp["error"]
            raise (KeyError(err) if err.startswith("unknown ")
                   else ValueError(err))
        return resp.get("result")

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        def remote(*args, **kwargs):
            if args:
                raise TypeError(f"{name}() takes keyword arguments only")
            return self._call(name, **kwargs)
        return remote


CLIENT_METHODS = [m for m in VulcanSDK._VALID]


def wire_client(sdk_like):
    """Assert both faces stay in lockstep (used by verify suite)."""
    missing = [m for m in CLIENT_METHODS if not callable(
        getattr(sdk_like, m, None))]
    return missing
