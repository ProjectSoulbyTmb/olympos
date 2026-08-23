"""Registry of permitted external data sources with policy-gated pulls."""
import json
import os
import time

SOURCES = {
    "ge_prices": {
        "url": "https://prices.runescape.wiki/api/v1/osrs/latest",
        "desc": "Grand Exchange latest prices"},
    "runelite_gameupdate": {
        "url": "https://api.runelite.net/runelite/gameupdate",
        "desc": "RuneLite view of the current OSRS game revision"},
}


def pull(root, policy, name, log=None):
    if name not in SOURCES:
        return {"ok": False, "error": f"unknown source '{name}' "
                f"(known: {', '.join(SOURCES)})"}
    from mind.net.policy import guarded_urlopen
    src = SOURCES[name]
    try:
        raw = guarded_urlopen(policy, src["url"], timeout=30)
        data = json.loads(raw.decode())
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    out_dir = os.path.join(root, "knowledge", "live")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{name}.json")
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"fetched": time.time(), "data": data}, f)
    os.replace(tmp, out)
    if log:
        log(f"pulled {name} -> knowledge/live/{name}.json "
            f"({len(raw)} bytes)")
    return {"ok": True, "bytes": len(raw), "path": rel_path(out)}


def rel_path(p):
    return os.path.join(*p.split(os.sep)[-2:])


def pull_all(root, policy, log=None):
    results = {}
    for name in SOURCES:
        results[name] = pull(root, policy, name, log=log)
        time.sleep(0.6)
    return results


def revision_from_runelite(root):
    path = os.path.join(root, "knowledge", "live", "runelite_gameupdate.json")
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        data = payload.get("data") or {}
        return {"revision": data.get("revision"),
                "update_id": data.get("id"),
                "ts": data.get("date") or payload.get("fetched")}
    except (OSError, json.JSONDecodeError):
        return None
