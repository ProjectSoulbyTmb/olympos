import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.environ.get("OSRS_ROOT") or ROOT
OUT = os.path.join(ROOT, "knowledge")

USER_AGENT = ("osrs-llm-agent-knowledge-fetcher/1.0 "
              "(local research project; contact: none)")
WIKI_API = "https://oldschool.runescape.wiki/api.php"
PRICES_API = "https://prices.runescape.wiki/api/v1/osrs"

TOPICS = [
    "Woodcutting", "Mining", "Fishing", "Cooking",
    "Ultimate Ironman", "Ultimate Ironman Guide", "Ironman Guide",
    "Woodcutting training", "Mining training", "Fishing training",
    "Cooking training",
    "Pay-to-play training", "Free-to-play",
    "Money making guide",
]

TRACKED_ITEMS = [
    "Logs", "Oak logs", "Willow logs",
    "Copper ore", "Tin ore", "Iron ore",
    "Raw shrimps", "Shrimps", "Burnt shrimp",
    "Iron axe", "Steel axe", "Black axe", "Mithril axe",
    "Bronze pickaxe", "Iron pickaxe", "Steel pickaxe",
]


def http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def fetch_mapping():
    data = http_get_json(f"{PRICES_API}/mapping")
    by_name = {}
    for entry in data:
        name = entry.get("name")
        if name:
            by_name[name] = {"id": entry["id"],
                             "examine": entry.get("examine", ""),
                             "limit": entry.get("limit")}
    return by_name


def fetch_latest_prices():
    payload = http_get_json(f"{PRICES_API}/latest")["data"]
    out = {}
    for item_id, p in payload.items():
        out[item_id] = {
            "high": p.get("high"),
            "low": p.get("low"),
            "high_time": p.get("highTime"),
            "low_time": p.get("lowTime"),
        }
    return out


def fetch_topic_extract(title):
    params = (
        f"?action=query&format=json&prop=extracts&explaintext=1"
        f"&redirects=1&titles={urllib.request.quote(title)}"
    )
    url = WIKI_API + params
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    pages = data.get("query", {}).get("pages", {})
    for _pid, page in pages.items():
        extract = page.get("extract", "")
        if extract:
            head = extract[:12000]
            return head
    return ""


def trim_to_sections(text, keep_prefixes=("Training", "Overview", "Equipment",
                                          "Strategy", "Money making", "Methods")):
    lines = text.splitlines()
    kept, keep = [], True
    for line in lines:
        if line.startswith("=="):
            heading = line.strip("= ").lower()
            keep = any(p.lower() in heading for p in keep_prefixes) or \
                len(kept) < 40
        if keep:
            kept.append(line)
    return "\n".join(kept)


def main():
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print("fetching GE item mapping...")
    mapping = fetch_mapping()
    with open(os.path.join(OUT, "raw", f"item_mapping_{today}.json"),
              "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=1)

    print("fetching latest GE prices...")
    prices = fetch_latest_prices()
    with open(os.path.join(OUT, "raw", f"ge_prices_{today}.json"),
              "w", encoding="utf-8") as f:
        json.dump(prices, f, indent=1)

    tracked = {}
    for name in TRACKED_ITEMS:
        info = mapping.get(name)
        if not info:
            continue
        p = prices.get(str(info["id"]), {})
        mid = None
        if p.get("high") and p.get("low"):
            mid = (p["high"] + p["low"]) // 2
        tracked[name] = {"buy": p.get("high"), "sell": p.get("low"),
                         "mid": mid, "limit": info.get("limit")}
        time.sleep(0.6)

    digest_parts = [
        "# OSRS ground-truth knowledge",
        f"",
        f"Fetched: {stamp}",
        "",
        "## Sources",
        "- Grand Exchange real-time prices: https://prices.runescape.wiki/api/v1/osrs/latest",
        "- Item mapping: https://prices.runescape.wiki/api/v1/osrs/mapping",
        "- OSRS Wiki (CC BY-NC-SA 3.0): https://oldschool.runescape.wiki/",
        "",
        "## Verified skill XP rates (per action)",
        "| Action | XP |",
        "|---|---|",
        "| Chop a normal tree (log) | 25 |",
        "| Chop an oak (log) | 37.5 |",
        "| Chop a willow (log) | 67.5 |",
        "| Mine copper/tin ore | 17.5 |",
        "| Mine iron ore | 35 |",
        "| Catch raw shrimps | 10 |",
        "| Cook shrimps | 30 |",
        "| Shrimps stop burning at Cooking level | 34 |",
        "",
        "## Live Grand Exchange snapshot (tracked items)",
        "| Item | Buy (high) | Sell (low) | Mid | GE limit /4h |",
        "|---|---|---|---|---|",
    ]
    for name, t in sorted(tracked.items()):
        digest_parts.append(
            f"| {name} | {t['buy'] or '-'} | {t['sell'] or '-'} | "
            f"{t['mid'] or '-'} | {t['limit'] or '-'} |"
        )
    digest_parts.append("")
    digest_parts.append("## Wiki article digests")

    for topic in TOPICS:
        print(f"fetching wiki topic: {topic}")
        try:
            extract = fetch_topic_extract(topic)
        except Exception as e:
            print(f"  failed: {e}")
            continue
        trimmed = trim_to_sections(extract)
        fname = f"wiki_{topic.lower().replace(' ', '_')}_{today}.md"
        with open(os.path.join(OUT, "raw", fname), "w", encoding="utf-8") as f:
            f.write(f"# {topic}\n\nSource: https://oldschool.runescape.wiki/w/"
                    f"{topic.replace(' ', '_')}\nFetched: {stamp}\n\n{extract}")
        digest_parts.append(f"\n### {topic}\n{trimmed[:4000]}\n")
        time.sleep(0.6)

    with open(os.path.join(OUT, "digest.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(digest_parts))

    with open(os.path.join(OUT, "ground_truth.json"), "w", encoding="utf-8") as f:
        json.dump({"fetched": stamp,
                   "tracked_prices": tracked,
                   "xp_rates": {
                       "tree_log": 25, "oak_log": 37.5, "willow_log": 67.5,
                       "copper_ore": 17.5, "iron_ore": 35,
                       "raw_shrimps_catch": 10, "cook_shrimps": 30},
                   "sources": ["prices.runescape.wiki", "oldschool.runescape.wiki"]},
                  f, indent=2)

    print(f"done -> {os.path.join(OUT, 'digest.md')}")


if __name__ == "__main__":
    sys.exit(main())
