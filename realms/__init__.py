"""REALM registry: one declarative home for realm endpoints.

Adding a realm becomes a data entry plus its engine - dashboards and
runners read ports from here instead of hardcoding them. Missing file
or name falls back to caller-supplied defaults, so nothing breaks.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(HERE, "registry.json")

_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            with open(REGISTRY_PATH, encoding="utf-8") as fh:
                _cache = json.load(fh).get("realms", [])
        except (OSError, ValueError):
            _cache = []
    return _cache


def all_realms():
    return [dict(r) for r in _load()]


def realm(name):
    for r in _load():
        if r.get("name") == name:
            return dict(r)
    return None


def port(name, default=None):
    r = realm(name)
    return int(r["port"]) if r and "port" in r else default
