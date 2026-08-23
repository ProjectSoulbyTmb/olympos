"""Live Grand Exchange price lookups for the OSRS Lab engine.

Reads the snapshot written by osrs_updater.py. Never required for
gameplay - when data is missing or stale, every call degrades to None.
"""
import json
import os

_LIVE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "knowledge", "live")
STALE_AFTER = 24 * 3600


def _load(live_dir=None):
    d = live_dir or _LIVE
    path = os.path.join(d, "ge_prices.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def ge_price(item_name, live_dir=None):
    """-> {"high": n, "low": n, "limit": n} or None if unknown/stale."""
    snap = _load(live_dir)
    if not snap:
        return None
    import time
    if time.time() - snap.get("fetched", 0) > STALE_AFTER:
        return None
    return snap.get("items", {}).get(item_name)


def ge_margin(item_name, live_dir=None):
    """-> high-low spread in coins, or None."""
    p = ge_price(item_name, live_dir)
    if not p or p.get("high") is None or p.get("low") is None:
        return None
    return int(p["high"]) - int(p["low"])
