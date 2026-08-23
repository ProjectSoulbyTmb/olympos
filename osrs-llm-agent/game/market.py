"""Live Grand Exchange price lookups for the OSRS Lab engine.

Reads the snapshot written by osrs_updater.py. Never required for
gameplay - when data is missing or stale, every call degrades to None.
"""
import json
import os

_LIVE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "knowledge", "live")
STALE_AFTER = 24 * 3600


def _load():
    path = os.path.join(_LIVE, "ge_prices.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def ge_price(item_name):
    """-> {"high": n, "low": n, "limit": n} or None if unknown/stale."""
    snap = _load()
    if not snap:
        return None
    import time
    if time.time() - snap.get("fetched", 0) > STALE_AFTER:
        return None
    return snap.get("items", {}).get(item_name)


def ge_margin(item_name):
    """-> high-low spread in coins, or None."""
    p = ge_price(item_name)
    if not p or p.get("high") is None or p.get("low") is None:
        return None
    return int(p["high"]) - int(p["low"])
