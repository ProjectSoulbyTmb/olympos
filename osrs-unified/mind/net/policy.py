"""MIND network policy - every outbound request and listener bind passes
through here. The allowlist file is the 'design privilege': edit it to grant
more of the network."""
import json
import os
import threading
import time

DEFAULT_POLICY = {
    "outbound_allow": [
        {"host": "127.0.0.1", "port": "*"},
        {"host": "localhost", "port": "*"},
        {"host": "prices.runescape.wiki", "port": 443},
        {"host": "oldschool.runescape.wiki", "port": 443},
        {"host": "api.runelite.net", "port": 443},
        {"host": "api.weird.gay", "port": 443},
    ],
    "listener_allow": [
        {"host": "127.0.0.1", "port": [5731, 43594]},
        {"host": "*", "port": 0},
    ],
    "rate_limit_min_interval_s": {"*": 0.5},
    "max_response_bytes": 20_000_000,
}


class NetPolicy:
    def __init__(self, root):
        self.path = os.path.join(root, "mind", "net_policy.json")
        self._lock = threading.Lock()
        self._last_call = {}
        self.config = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict) and "outbound_allow" in cfg:
                return cfg
        except (OSError, json.JSONDecodeError):
            pass
        return json.loads(json.dumps(DEFAULT_POLICY))

    def save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=1)
            os.replace(tmp, self.path)

    def _match(self, rules, host, port):
        for rule in rules:
            if rule["host"] not in ("*", host):
                continue
            rp = rule.get("port", "*")
            if rp == "*" or rp == port or (
                    isinstance(rp, list) and port in rp):
                return True
        return False

    @staticmethod
    def _resolve(host):
        if host in ("localhost", "127.0.0.1", "::1"):
            return "127.0.0.1"
        return host

    def check_outbound(self, host, port):
        host = self._resolve(host)
        try:
            port = int(port)
        except (TypeError, ValueError):
            return False, f"bad port {port!r}"
        if not self._match(self.config["outbound_allow"], host, port):
            return False, f"outbound {host}:{port} not in allowlist"
        interval = self.config.get("rate_limit_min_interval_s", {}).get(
            "*", 0.5)
        with self._lock:
            last = self._last_call.get((host, port), 0.0)
            wait = time.time() - last
            if wait < interval:
                return False, (f"rate limited {host}:{port}, retry in "
                               f"{interval - wait:.1f}s")
            self._last_call[(host, port)] = time.time()
        return True, "ok"

    def check_listener(self, host, port):
        try:
            port = int(port)
        except (TypeError, ValueError):
            return False, f"bad port {port!r}"
        if not self._match(self.config["listener_allow"], host, port):
            return False, f"listening on {host}:{port} not allowed"
        return True, "ok"

    def allow_outbound(self, host, port=443):
        self.config["outbound_allow"].append({"host": host, "port": port})
        self.save()

    def allow_listener(self, host, port):
        self.config["listener_allow"].append({"host": host, "port": port})
        self.save()

    def deny_outbound(self, host, port=None):
        kept = []
        for rule in self.config["outbound_allow"]:
            if rule["host"] == host and (port is None
                                         or rule.get("port") == port):
                continue
            kept.append(rule)
        self.config["outbound_allow"] = kept
        self.save()


def guarded_urlopen(policy, req_or_url, timeout=30):
    """urllib opener that enforces the policy before any socket leaves."""
    import urllib.request
    url = getattr(req_or_url, "full_url", None) or str(req_or_url)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    ok, reason = policy.check_outbound(parsed.hostname, port)
    if not ok:
        raise PermissionError(f"MIND net policy denied: {reason}")
    max_bytes = policy.config.get("max_response_bytes", 20_000_000)
    with urllib.request.urlopen(req_or_url, timeout=timeout) as resp:
        return resp.read(max_bytes + 1)[:max_bytes]
