"""web_search - Riley's advanced multi-engine adult media finder.

Fans one query out across every supported engine and merges the hits:
  dbnaked    model-page guess + bdsm/general category probes (pics+tube)
  pornpics   query search (photo galleries)
  imagefap   gallery search
  babesource gallery search
  eporner    video search (new adapter)

Polite crawling via the shared media_ingest Fetcher (per-host delays,
retry+backoff, Referer pinning). Every engine fails soft: one dead site
never aborts the sweep. Results are scored, deduped, saved to a JSON
report, and can be filtered by media kind.

Usage:
  python ingest/web_search.py "goth feet"
  python ingest/web_search.py "riley reid" --engine all --kind any
  python ingest/web_search.py "tattooed" --engine pornpics,eporner --cap 20
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone

APP = "web_search"
VERSION = "1.0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import media_ingest as mi  # noqa: E402

ENGINES = ["dbnaked", "pornpics", "imagefap", "babesource", "eporner"]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def terms(text):
    return [t for t in re.split(r"\s+", (text or "").lower()) if t]


def slugify(q):
    return re.sub(r"[^a-z0-9-]+", "-", q.lower().strip()).strip("-")


class Eporner:
    HOST = "https://www.eporner.com"

    def __init__(self, f):
        self.f = f

    def search_videos(self, q, cap=30):
        url = f"{self.HOST}/search/{urllib.parse.quote_plus(q)}/"
        html = self.f.get(url)
        links = dict.fromkeys(re.findall(
            r'href="(/video-[A-Za-z0-9]{4,}/[^"#?]+)"', html))
        return [self.HOST + l for l in list(links)[:cap]]


class DbNakedProbe:
    HOST = "https://dbnaked.com"
    ITEM_RX = r'href="(/(?:pictures|tube)/content/[^"#]+?\d_[^"#]+)"'

    def __init__(self, f):
        self.f = f

    def probe(self, path, cap=25):
        html = self.f.get(f"{self.HOST}{path}")
        links = dict.fromkeys(re.findall(self.ITEM_RX, html))
        return [self.HOST + l for l in list(links)[:cap]]

    def candidates(self, q):
        t = slugify(q)
        letter = (q.strip()[:1] or "a").upper()
        cands = []
        if t:
            cands.append(("model-pics",
                          f"/models/general/{letter}/{t}", "pictures"))
            cands.append(("model-tube",
                          f"/models/general/{letter}/{t}", "tube"))
        for realm in ("bdsm", "general"):
            u = t.replace("-", "_")
            cands.append((f"cat-{realm}-pics",
                          f"/categories/pictures/{realm}/{u}", "pictures"))
            cands.append((f"cat-{realm}-tube",
                          f"/categories/tube/{realm}/{u}", "tube"))
        return cands


def score(url, words):
    hay = urllib.parse.urlsplit(url).path.lower().replace("-", " "). \
        replace("_", " ")
    hit = sum(1 for w in words if w in hay)
    res = 2 if re.search(r"/(2160|1440|1080)|\bhd\b|4k", hay) else 0
    kind = 1 if "/tube/" in hay or "/video-" in hay else 0
    return hit * 10 + res + kind


def run_dbnaked(fetcher, q, kind, cap):
    dn = DbNakedProbe(fetcher)
    found, errors = [], []
    seen_media = set()
    for label, path, media in dn.candidates(q):
        if media in seen_media or (kind != "any" and media != kind):
            continue
        try:
            items = dn.probe(path, cap=cap)
        except Exception as e:
            errors.append(f"{label}: {type(e).__name__}")
            continue
        if items:
            seen_media.add(media)
            found += items
    return sorted(set(found)), errors


def run_pornpics(fetcher, q, kind, cap):
    if kind == "tube":
        return [], []
    pp = mi.PornPics(fetcher)
    try:
        return pp.query_galleries(q, cap=cap), []
    except Exception as e:
        return [], [f"{type(e).__name__}"]


def run_imagefap(fetcher, q, kind, cap):
    if kind == "tube":
        return [], []
    im = mi.ImageFap(fetcher)
    pages = max(1, min(5, cap // 10))
    try:
        return im.search_galleries(q, pages=pages), []
    except Exception as e:
        return [], [f"{type(e).__name__}"]


def run_babesource(fetcher, q, kind, cap):
    if kind == "tube":
        return [], []
    bs = mi.BabeSource(fetcher)
    try:
        return bs.search_galleries(q, cap=cap), []
    except Exception as e:
        return [], [f"{type(e).__name__}"]


def run_eporner(fetcher, q, kind, cap):
    if kind == "pictures":
        return [], []
    ep = Eporner(fetcher)
    try:
        return ep.search_videos(q, cap=cap), []
    except Exception as e:
        return [], [f"{type(e).__name__}"]


RUNNERS = {
    "dbnaked": run_dbnaked,
    "pornpics": run_pornpics,
    "imagefap": run_imagefap,
    "babesource": run_babesource,
    "eporner": run_eporner,
}


def sweep(query, engines, kind="any", cap=25, speed=1.0, fetcher=None):
    fetcher = fetcher or mi.Fetcher(delay_scale=speed)
    words = terms(query)
    report = {"app": APP, "v": VERSION,
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "query": query, "kind": kind,
              "engines": {}, "total": 0}
    ranked_all = []
    for name in engines:
        runner = RUNNERS.get(name)
        if not runner:
            continue
        log(f"engine {name}: searching '{query}'")
        try:
            items, errors = runner(fetcher, query, kind, cap)
        except Exception as e:
            items, errors = [], [f"{type(e).__name__}: {e}"]
        scored = sorted(({ "url": u, "score": score(u, words)}
                         for u in set(items)),
                        key=lambda x: -x["score"])
        report["engines"][name] = {"count": len(scored),
                                   "errors": errors,
                                   "items": scored[:cap]}
        ranked_all += scored
        log(f"  {name}: {len(scored)} hits"
            + (f" ({'; '.join(errors)})" if errors else ""))
    deduped = {}
    for s in ranked_all:
        deduped.setdefault(s["url"], s)
    top = sorted(deduped.values(), key=lambda x: -x["score"])[:cap]
    report["total"] = len(deduped)
    report["top"] = top
    for s in top[:12]:
        log(f"  {s['score']:>3}  {s['url'][:90]}")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(prog=APP)
    p.add_argument("query")
    p.add_argument("--engine", default="all",
                   help=f"comma list or 'all' of {ENGINES}")
    p.add_argument("--kind", default="any",
                   choices=["any", "pictures", "tube"])
    p.add_argument("--cap", type=int, default=25,
                   help="max hits kept per engine")
    p.add_argument("--out", default=r"D:\new")
    p.add_argument("--report", default=None)
    p.add_argument("--speed", type=float, default=1.0)
    args = p.parse_args(argv)

    engines = (ENGINES if args.engine == "all"
               else [e.strip().lower() for e in args.engine.split(",")
                     if e.strip()])
    bad = [e for e in engines if e not in ENGINES]
    if bad:
        log(f"unknown engines ignored: {bad}")
        engines = [e for e in engines if e in ENGINES]
    if not engines:
        log("no valid engines")
        return 2

    report = sweep(args.query, engines, kind=args.kind,
                   cap=args.cap, speed=args.speed)
    os.makedirs(args.out, exist_ok=True)
    report_path = args.report or os.path.join(args.out, "_riley_find.json")
    tmp = report_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, report_path)
    log(f"total unique hits: {report['total']} -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
