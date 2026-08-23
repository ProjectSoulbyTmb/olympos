import json
import os
import subprocess
import sys
import time

CANONICAL_XP_HEAD = [0, 83, 174, 276, 388, 512, 650, 801, 969, 1154,
                     1358, 1584, 1833, 2107, 2411, 2746, 3115, 3523,
                     3973, 4470]
TICK_SECONDS = 0.6


def refresh_knowledge(root, state, max_age_hours=48):
    digest = os.path.join(root, "knowledge", "digest.md")
    if os.path.exists(digest):
        age_h = (time.time() - os.path.getmtime(digest)) / 3600
        if age_h < max_age_hours:
            return {"refreshed": False, "age_hours": round(age_h, 1)}
    proc = subprocess.run(
        [sys.executable, os.path.join(root, "tools", "update_knowledge.py")],
        cwd=root, capture_output=True, text=True, errors="replace",
        timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
    ok = proc.returncode == 0
    state.log("knowledge", "refresh", f"ok={ok}")
    return {"refreshed": True, "ok": ok}


def _fetch_latest_update():
    import urllib.request
    url = ("https://oldschool.runescape.wiki/api.php?action=query"
           "&list=search&srsearch=intitle%3A%22Update%22&srnamespace=0"
           "&srlimit=5&format=json")
    req = urllib.request.Request(
        url, headers={"User-Agent": "osrs-unified-mind/1.1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    hits = data.get("query", {}).get("search", [])
    return [{"title": h["title"]} for h in hits[:5]]


def _load_world(root):
    import importlib
    expected = os.path.abspath(os.path.join(root, "game", "world.py"))
    import game.world as W
    if os.path.abspath(W.__file__) != expected:
        for name in [m for m in sys.modules
                     if m == "game" or m.startswith("game.")]:
            del sys.modules[name]
        sys.path.insert(0, root)
        try:
            W = importlib.import_module("game.world")
        finally:
            try:
                sys.path.remove(root)
            except ValueError:
                pass
        if os.path.abspath(W.__file__) != expected:
            raise RuntimeError(f"cannot probe world for {root}")
    return W


def revision_status(root, fetch=True):
    """Compare sim ground truth to canonical OSRS constants and track the
    latest upstream game update. Offline-safe (fetch failures degrade)."""
    findings = []
    W = _load_world(root)
    xp_head = list(W.XP_TABLE)[:len(CANONICAL_XP_HEAD)]
    if xp_head != CANONICAL_XP_HEAD:
        diffs = [(i, a, b) for i, (a, b) in
                 enumerate(zip(xp_head, CANONICAL_XP_HEAD)) if a != b]
        findings.append({"severity": "critical", "area": "parity",
                         "message": f"XP table drifts from OSRS truth "
                                    f"at entries {diffs[:3]}"})
    for tier in ("iron_axe", "steel_axe", "iron_pickaxe"):
        if tier not in getattr(W, "SHOP_PRICES", {}):
            findings.append({"severity": "medium", "area": "parity",
                             "message": f"shop missing {tier} - tool "
                                        f"progression incomplete"})

    latest_path = os.path.join(root, "runs", "revision_status.json")
    prev_title = None
    if os.path.exists(latest_path):
        try:
            with open(latest_path, encoding="utf-8") as f:
                prev_title = json.load(f).get("latest_update_title")
        except (OSError, json.JSONDecodeError):
            pass

    updates = []
    fetched = False
    if fetch:
        try:
            updates = _fetch_latest_update()
            fetched = True
        except Exception as e:
            findings.append({"severity": "low", "area": "revision",
                             "message": f"upstream fetch offline ({e})"})
    else:
        try:
            with open(os.path.join(root, "knowledge", "live",
                                   "game_updates.json"),
                      encoding="utf-8") as f:
                gu = json.load(f)
            updates = [{"title": u["title"]}
                       for u in gu.get("updates", [])[:5]]
            fetched = True
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    latest_title = updates[0]["title"] if updates else None
    new_update = bool(latest_title and prev_title
                      and latest_title != prev_title)
    if new_update:
        findings.append({"severity": "low", "area": "revision",
                         "message": f"new upstream update detected: "
                                    f"'{latest_title}' (was '{prev_title}') "
                                    f"- review knowledge digest"})
    status = {"checked": time.time(),
              "fetched": fetched,
              "xp_parity_ok": not any(f["area"] == "parity" for f in findings),
              "latest_update_title": latest_title,
              "previous_update_title": prev_title,
              "updates": updates,
              "findings": findings}
    os.makedirs(os.path.dirname(latest_path), exist_ok=True)
    tmp = latest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=1)
    os.replace(tmp, latest_path)
    return status


def ensure_digest_injected(kb_docs, root):
    digest = os.path.join(root, "knowledge", "digest.md")
    if os.path.exists(digest) and "ground_truth" not in kb_docs:
        with open(digest, encoding="utf-8") as f:
            kb_docs["ground_truth"] = f.read()
    return kb_docs
