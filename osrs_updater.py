"""Continuous updater: keeps OsrsLab current with the live OSRS game.

Stable-by-design:
  - retries each source with exponential backoff
  - atomic snapshot writes + a lockfile so overlapping runs cannot corrupt
  - file logging with size cap
  - config-driven endpoints/interval (updater_config.json)
  - `--status` health report, `--watch N` daemon loop

Data comes from community-authorised sources only:
  - prices.runescape.wiki real-time price API (GE prices + item mapping)
  - oldschool.runescape.wiki MediaWiki API (recent "Update:" pages)

Usage:
  python osrs_updater.py                 # one refresh pass
  python osrs_updater.py --watch 30      # re-refresh every 30 minutes
  python osrs_updater.py --status        # health report, no fetching
  python osrs_updater.py --skip-prices   # news check only

Outputs land in osrs-llm-agent/knowledge/live/. The engine reads these
files opportunistically via game/market.py - stale or missing data never
breaks gameplay.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE_DIR = os.path.join(HERE, "osrs-llm-agent", "knowledge", "live")
CONFIG_PATH = os.path.join(HERE, "updater_config.json")
LOCK_PATH = os.path.join(LIVE_DIR, "updater.lock")
LOG_PATH = os.path.join(LIVE_DIR, "updater.log")
LOG_MAX_BYTES = 512 * 1024

DEFAULT_CONFIG = {
    "user_agent": "OsrsLab local sandbox - knowledge refresher",
    "timeout_s": 15,
    "retries": 3,
    "backoff_s": 2.0,
    "prices_enabled": True,
    "updates_enabled": True,
}

PRICES_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
WIKI_CHANGES_URL = ("https://oldschool.runescape.wiki/api.php"
                    "?action=query&list=recentchanges&rcnamespace=0"
                    "&rctype=new|edit&rclimit=50&format=json")

STALE_AFTER = 24 * 3600


# ------------------------------------------------------------------ infra --

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except Exception:
        pass
    return cfg


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        if os.path.exists(LOG_PATH) and \
                os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


class _Lock:
    """Best-effort single-instance guard for --watch mode."""

    def __init__(self):
        self.held = False

    def __enter__(self):
        try:
            os.makedirs(LIVE_DIR, exist_ok=True)
            if os.path.exists(LOCK_PATH):
                age = time.time() - os.path.getmtime(LOCK_PATH)
                if age < 3600:                      # another run is alive
                    print(f"[lock] updater already ran "
                          f"{int(age)}s ago - aborting", file=sys.stderr)
                    sys.exit(3)
            with open(LOCK_PATH, "w") as fh:
                fh.write(str(os.getpid()))
            self.held = True
        except OSError:
            pass
        return self

    def __exit__(self, *_exc):
        if self.held:
            try:
                os.remove(LOCK_PATH)
            except OSError:
                pass


def _fetch_json(url, cfg=None, timeout=None):
    cfg = cfg or {}
    req = urllib.request.Request(
        url, headers={"User-Agent": cfg.get(
            "user_agent", DEFAULT_CONFIG["user_agent"])})
    t = timeout if timeout is not None else cfg.get("timeout_s", 15)
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.loads(r.read().decode())


def _with_retries(fn, url, cfg, fetcher=None):
    """Exponential backoff around any fetch callable."""
    attempts = int(cfg.get("retries", 3))
    backoff = float(cfg.get("backoff_s", 2.0))
    last = None
    for i in range(attempts):
        try:
            if fetcher is not None:
                return fetcher(url, timeout=cfg.get("timeout_s", 15))
            return fn(url, cfg)
        except Exception as e:                         # noqa: PERF203
            last = e
            if i < attempts - 1:
                delay = backoff * (2 ** i)
                log(f"retry {i + 1}/{attempts - 1} for {url}: {e} "
                    f"(sleep {delay:.0f}s)")
                time.sleep(delay)
    raise last


def _write(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


# ----------------------------------------------------------------- sources --

def fetch_prices(fetcher=None, cfg=None):
    """-> {item_id: {"high": n, "low": n, ...}}"""
    return _with_retries(_fetch_json, PRICES_URL, cfg, fetcher).get("data", {})


def fetch_mapping(fetcher=None, cfg=None):
    """-> [{"id": id, "name": "...", "limit": n, ...}, ...]"""
    return _with_retries(_fetch_json, MAPPING_URL, cfg, fetcher)


def fetch_recent_updates(fetcher=None, cfg=None):
    """-> newest-first [{title, timestamp}] of recent wiki edits."""
    data = _with_retries(_fetch_json, WIKI_CHANGES_URL, cfg, fetcher)
    return [{"title": rc.get("title", ""), "timestamp":
             rc.get("timestamp", "")}
            for rc in data.get("query", {}).get("recentchanges", [])]


def refresh_prices(cfg=None, fetcher=None):
    try:
        prices = fetch_prices(fetcher, cfg)
        mapping = fetch_mapping(fetcher, cfg)
        by_name = {}
        for entry in mapping:
            pid = str(entry.get("id"))
            if pid in prices:
                by_name[entry.get("name", "?")] = {
                    "id": entry.get("id"),
                    "high": prices[pid].get("high"),
                    "low": prices[pid].get("low"),
                    "highTime": prices[pid].get("highTime"),
                    "lowTime": prices[pid].get("lowTime"),
                    "limit": entry.get("limit"),
                }
        _write(os.path.join(LIVE_DIR, "ge_prices.json"), {
            "fetched": time.time(),
            "source": PRICES_URL,
            "items": by_name,
        })
        return len(by_name), None
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def refresh_updates(cfg=None, fetcher=None):
    try:
        updates = fetch_recent_updates(fetcher, cfg)
        path = os.path.join(LIVE_DIR, "game_updates.json")
        prev = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    prev = json.load(fh)
            except Exception:
                prev = {}
        known = {u["title"] for u in prev.get("updates", [])}
        fresh = [u for u in updates if u["title"] not in known]
        _write(path, {"fetched": time.time(), "updates": updates})
        return len(updates), fresh, None
    except Exception as e:
        return 0, [], f"{type(e).__name__}: {e}"


# ------------------------------------------------------------------- runs --

def run_once(skip_prices=False, fetcher=None, cfg=None):
    cfg = cfg or load_config()
    os.makedirs(LIVE_DIR, exist_ok=True)
    status = {"ran_at": time.time(), "errors": []}

    want_prices = (not skip_prices) and cfg.get("prices_enabled", True)
    if want_prices:
        n, err = refresh_prices(cfg, fetcher)
        status["prices_items"] = n
        status["errors"] += ([err] if err else [])
        log(f"[prices] {'ok - ' + str(n) + ' items' if not err else err}")
    elif skip_prices:
        log("[prices] skipped (--skip-prices)")

    if cfg.get("updates_enabled", True):
        n, fresh, err = refresh_updates(cfg, fetcher)
        status["updates_tracked"] = n
        status["errors"] += ([err] if err else [])
        if fresh:
            log("[updates] NEW since last run:")
            for u in fresh[:5]:
                log(f"          - {u['title']}")
            status["new_updates"] = [u["title"] for u in fresh[:10]]
        elif not err:
            log(f"[updates] no new updates ({n} tracked)")
        if err:
            log(f"[updates] {err}")

    _write(os.path.join(LIVE_DIR, "status.json"), status)
    return status


def _age_s(ts):
    return time.time() - ts


def show_status():
    checks = [
        ("status", os.path.join(LIVE_DIR, "status.json"), "ran_at"),
        ("ge_prices", os.path.join(LIVE_DIR, "ge_prices.json"), "fetched"),
        ("game_updates", os.path.join(LIVE_DIR, "game_updates.json"),
         "fetched"),
    ]
    healthy = True
    for name, path, ts_key in checks:
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            age = _age_s(d.get(ts_key, 0))
            extra = ""
            if name == "ge_prices":
                extra = f", {len(d.get('items', {}))} items"
            state = "OK" if age < STALE_AFTER else "STALE"
            healthy &= age < STALE_AFTER
            print(f"{name:<13} {state:>5}  age {_age_str(age)}{extra}")
        except Exception as e:
            healthy = False
            print(f"{name:<13} MISSING ({e})")
    print("overall:", "HEALTHY" if healthy else "UNHEALTHY")
    return 0 if healthy else 1


def _age_str(s):
    if s < 90:
        return f"{int(s)}s"
    if s < 5400:
        return f"{int(s / 60)}m"
    return f"{s / 3600:.1f}h"


def is_fresh(max_age=STALE_AFTER):
    path = os.path.join(LIVE_DIR, "status.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            return _age_s(json.load(fh).get("ran_at", 0)) < max_age
    except Exception:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="OSRS live-data refresher")
    ap.add_argument("--watch", type=float, default=0,
                    help="loop forever, refreshing every N minutes")
    ap.add_argument("--skip-prices", action="store_true")
    ap.add_argument("--status", action="store_true",
                    help="show snapshot health and exit")
    args = ap.parse_args(argv)

    if args.status:
        sys.exit(show_status())

    cfg = load_config()
    if args.watch > 0:
        while True:
            with _Lock():
                try:
                    run_once(skip_prices=args.skip_prices, cfg=cfg)
                except Exception as e:
                    log(f"[watch] pass failed: {e}")
            time.sleep(args.watch * 60)
    else:
        with _Lock():
            run_once(skip_prices=args.skip_prices, cfg=cfg)


if __name__ == "__main__":
    main()
