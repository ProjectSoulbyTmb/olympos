"""ZEUS SDK - the only surface dashboards/operators see.

Two interchangeable faces:
  ZeusClient   JSON-lines TCP client speaking to a hosted ZeusServer
  ZeusSDK      in-process facade over the Kernel

Both expose identical method names, so any tooling written against one
runs unchanged against the other.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import json
import socket

import content


class ZeusSDK:
    """In-process facade. Raises ValueError/KeyError on bad intents."""

    _VALID = {
        "ping", "status", "diagnose", "events", "repairs", "patrol",
        "baseline_build", "baseline_verify", "procs", "watch_pid",
        "unwatch_pid", "bolt_kill", "quarantine_list",
        "quarantine_restore", "policy_get", "policy_set", "close",
    }

    _EDITABLE_POLICY = {
        "CPU_SOFT_PCT": (int, float), "CPU_HARD_PCT": (int, float),
        "MEM_SOFT_MB": (int, float), "RUNAWAY_SAMPLES": int,
        "CHURN_BURST_THRESHOLD": int,
        "INTEGRITY_EVERY_TICKS": int,
    }

    def __init__(self, kernel):
        self.kernel = kernel

    # ---- info ----

    def ping(self):
        return {"pong": True, "service": "zeus"}

    def status(self):
        return self.kernel.status()

    def diagnose(self):
        return self.kernel.diagnose()

    def events(self, n=20):
        return list(self.kernel.events)[-int(n):]

    def repairs(self, n=20):
        return list(self.kernel.repairs)[-int(n):]

    def patrol(self, n=1):
        last = None
        for _ in range(max(1, min(int(n), 100))):
            last = self.kernel.tick()
        return last

    # ---- integrity ----

    def baseline_build(self):
        result = self.kernel.aegis.build()
        self.kernel.log_event("aegis", "info",
                              f"baseline built: {result['files']} files")
        return result

    def baseline_verify(self, limit=100):
        return self.kernel.aegis.verify(limit=int(limit))

    # ---- processes / enforcement ----

    def procs(self, name=None):
        snap = self.kernel.sentinel.table.sample()
        rows = [info.as_dict() for info in snap.values()]
        if name:
            low = str(name).lower()
            rows = [r for r in rows
                    if low in r["name"].lower()
                    or low in r["exe"].lower()]
        rows.sort(key=lambda r: (-r["cpu_pct"] or 0, r["pid"]))
        return rows[:500]

    def watch_pid(self, pid, name=None):
        pid = int(pid)
        self.kernel.sentinel.pin_pid(pid, name=name)
        self.kernel.log_event("sentinel", "info",
                              f"pinning pid {pid} ({name or 'unnamed'})")
        return {"pinned": pid}

    def unwatch_pid(self, pid):
        removed = self.kernel.sentinel.unpin_pid(int(pid))
        if removed is None:
            raise KeyError(f"not pinned: {pid}")
        return {"unpinned": int(pid)}

    def bolt_kill(self, pid):
        import bolt as bolt_mod
        rec = bolt_mod.discharge(int(pid),
                                 self.kernel.sentinel.last or None)
        self.kernel.record_repair(
            "bolt", f"manual discharge pid {pid}: {rec['detail']}",
            pid=int(pid))
        return rec

    # ---- quarantine ----

    def quarantine_list(self):
        return self.kernel.quarantine.listing()

    def quarantine_restore(self, qid):
        return self.kernel.quarantine.restore(str(qid))

    # ---- tuning ----

    def policy_get(self):
        return {k: getattr(content, k)
                for k in self._EDITABLE_POLICY}

    def policy_set(self, key, value):
        if key not in self._EDITABLE_POLICY:
            raise KeyError(f"unknown policy key: {key}")
        types = self._EDITABLE_POLICY[key]
        type_tuple = types if isinstance(types, tuple) else (types,)
        if not isinstance(value, type_tuple):
            wanted = "/".join(t.__name__ for t in type_tuple)
            raise ValueError(f"{key} wants {wanted}")
        setattr(content, key, type_tuple[0](value))
        return {key: getattr(content, key)}

    def close(self):
        return {"bye": True}


class ZeusClient:
    """Wire client with the same method surface as ZeusSDK."""

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
        for handle in (self._fh, self._sock):
            if handle:
                try:
                    handle.close()
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


CLIENT_METHODS = [m for m in ZeusSDK._VALID]


def wire_client(sdk_like):
    """Assert both faces stay in lockstep (used by verify suite)."""
    missing = [m for m in CLIENT_METHODS if not callable(
        getattr(sdk_like, m, None))]
    return missing
