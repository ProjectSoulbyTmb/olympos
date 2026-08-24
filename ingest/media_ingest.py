"""media_ingest - multi-source adult media harvester for APHRODITE libraries.

Adapters: dbnaked.com (categories/models/channels, pictures+tube),
pornpics.com (query search, photos), babesource.com (search, photos).

Design constraints (house rules):
- stdlib only, offline-safe parsers (verify suite runs with zero network)
- polite crawling: per-host delays, retry+backoff, Referer pinning
- resumable: existing non-empty files are skipped; catalogs merged
- bounded: every source has caps; nothing auto-expands beyond config

Usage:
  python tools/media_ingest.py --discover            # resolve sources -> catalogs
  python tools/media_ingest.py --download            # download pending files
  python tools/media_ingest.py --download --only goth
  python tools/media_ingest.py --launch              # detached background run

Filters:
  --hd-only           tube scenes without HD markers are skipped
  --no-female-filter  disable best-effort tag blacklist (default enabled)
"""
import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

APP = "media_ingest"
VERSION = "1.0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

REFERERS = {
    "i.dbnaked.com": "https://dbnaked.com/",
    "i-cdn.dbnaked.com": "https://dbnaked.com/",
    "flv.dbnaked.com": "https://dbnaked.com/",
    "dbnaked.com": None,
    "www.pornpics.com": "https://www.pornpics.com/",
    "cdni.pornpics.com": "https://www.pornpics.com/",
    "imagefap.com": "https://www.imagefap.com/",
    "cdnc.imagefap.com": "https://www.imagefap.com/",
    "babesource.com": "https://babesource.com/",
    "media.babesource.com": "https://babesource.com/",
}

HOST_DELAYS = {
    "dbnaked.com": 1.1,
    "i.dbnaked.com": 0.45,
    "i-cdn.dbnaked.com": 0.45,
    "flv.dbnaked.com": 0.8,
    "www.pornpics.com": 1.6,
    "cdni.pornpics.com": 0.5,
    "imagefap.com": 1.4,
    "cdnc.imagefap.com": 0.5,
    "babesource.com": 1.2,
    "media.babesource.com": 0.6,
}

FEMALE_BLACKLIST = re.compile(
    r"shemale|tranny|ladyboy|transsexual|\bgay\b|\bts\b|"
    r"crossdress|sissy|\bmale\s?(strip|dom|sub)\b", re.I)

MEDIA_EXT = re.compile(r"\.(jpe?g|png|gif|webp|mp4|m3u8|webm)$", re.I)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sanitize(name, maxlen=80):
    name = re.sub(r"[^\w.\- ]+", "_", name).strip(" ._")
    return name[:maxlen] or "item"


class Fetcher:
    def __init__(self, delay_scale=1.0):
        self.delay_scale = delay_scale
        self._last = {}

    def _throttle(self, host):
        base = HOST_DELAYS.get(host, 1.0) * self.delay_scale
        wait = base + random.uniform(0, base * 0.35)
        now = time.monotonic()
        elapsed = now - self._last.get(host, 0.0)
        if elapsed < wait:
            time.sleep(wait - elapsed)
        self._last[host] = time.monotonic()

    def headers(self, url, extra=None):
        host = urllib.parse.urlsplit(url).netloc
        h = {"User-Agent": UA}
        ref = REFERERS.get(host)
        if ref:
            h["Referer"] = ref
        if extra:
            h.update(extra)
        return h

    def get(self, url, binary=False, extra=None, retries=3):
        last_err = None
        for attempt in range(retries):
            host = urllib.parse.urlsplit(url).netloc
            self._throttle(host)
            try:
                req = urllib.request.Request(url, headers=self.headers(url, extra))
                with urllib.request.urlopen(req, timeout=40) as r:
                    data = r.read()
                return data if binary else data.decode("utf-8", "replace")
            except Exception as e:
                last_err = e
                backoff = 2 ** attempt * 2
                log(f"  retry {attempt + 1}/{retries} {type(e).__name__}"
                    f" {str(e)[:60]} sleep {backoff}s :: {url[:90]}")
                time.sleep(backoff)
        raise RuntimeError(f"fetch failed after {retries}: {url} ({last_err})")

    def head_size(self, url):
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers=self.headers(url))
            with urllib.request.urlopen(req, timeout=20) as r:
                return int(r.headers.get("Content-Length") or 0)
        except Exception:
            return 0


def abs_url(base, href):
    return urllib.parse.urljoin(base, href.split("&amp;")[0])


def passes_female_filter(text):
    return not FEMALE_BLACKLIST.search(text or "")


class DbNaked:
    HOST = "https://dbnaked.com"
    KIND_PREFIX = {"pictures": "pictures", "tube": "tube"}

    def __init__(self, f):
        self.f = f

    def discover_categories(self, realms=("general", "bdsm"),
                            media=("pictures", "tube"), pattern=None):
        pat = re.compile(pattern, re.I) if pattern else None
        found = {}
        for realm in realms:
            for med in media:
                url = f"{self.HOST}/{realm}/categories?media={med}"
                try:
                    html = self.f.get(url)
                except RuntimeError as e:
                    log(f"  discover fail {realm}/{med}: {e}")
                    continue
                cats = sorted(set(re.findall(
                    rf'href="(/categories/{med}/{realm}/[^"]+)"', html)))
                for c in cats:
                    if med == "tube" and c.startswith("/categories/pictures/"):
                        continue
                    if med == "pictures" and c.startswith("/categories/tube/"):
                        continue
                    if pat is None or pat.search(c):
                        found[c] = f"{self.HOST}{c}"
        return found

    def walk_listing(self, url, item_regex, max_pages=40):
        seen_pages = set()
        queue = [url]
        items = []
        while queue and len(seen_pages) < max_pages:
            page_url = queue.pop(0)
            norm = re.sub(r"/\d+(/?)$", "", page_url.split("?")[0])
            if norm in seen_pages:
                continue
            seen_pages.add(norm)
            try:
                html = self.f.get(page_url)
            except RuntimeError as e:
                log(f"  listing fail {page_url[:80]}: {e}")
                continue
            for m in re.finditer(item_regex, html):
                link = m.group(1)
                if passes_female_filter(link):
                    items.append(abs_url(page_url, link))
            links = re.findall(r'href="([^"]+)"', html)
            base_sort = page_url.rstrip("/").rsplit("/", 1)[-1]
            for l in links:
                al = abs_url(page_url, l)
                if not al.startswith(self.HOST):
                    continue
                path = urllib.parse.urlsplit(al).path
                if re.search(rf'/(?:{base_sort})/\d+$', path) or \
                   re.search(r"/(?:latest|most-popular|top-rated|most-viewed)/\d+$",
                             path):
                    if al not in queue and passes_female_filter(al):
                        queue.append(al)
        return sorted(set(items))

    def category_items(self, cat_path, kind):
        rx = (rf'href="(/{self.KIND_PREFIX[kind]}/content/[^"#]+?\d_[^"#]+)"')
        return self.walk_listing(f"{self.HOST}{cat_path}", rx)

    def model_items(self, model_path, kind, max_pages=25):
        rx = (rf'href="(/(?:pictures|tube)/content/[^"#]+?\d_[^"#]+)"')
        base = f"{self.HOST}{model_path}/{kind}/latest"
        return self.walk_listing(base, rx, max_pages=max_pages)

    def channel_items(self, domain, realm="bdsm", kind="pictures"):
        url = (f"{self.HOST}/{realm}/channels/{domain}"
               f"?media={kind}&sort=latest")
        rx = rf'href="(/(?:pictures|tube)/content/[^"#]+?\d_[^"#]+)"'
        return [u for u in self.walk_listing(url, rx)
                if f"/{kind}/content/" in u]

    def parse_gallery(self, url):
        html = self.f.get(url)
        title_m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (re.sub(r"\s*@.*$", "", title_m.group(1)).strip()
                 if title_m else sanitize(url.rsplit("/", 1)[-1]))
        og = re.search(r'property="og:image"\s+content="([^"]+)"', html)
        scene_id_m = re.search(r"/(\d+)_", url)
        imgs = []
        if og:
            sample = og.group(1)
            m = re.match(r"(?:(?:https?:))?//([^/]+)/(.+)/(\d+)\.(jpg|webp|png)",
                         sample)
            if m:
                host, dirpath, n, ext = m.groups()
                thumb_host = host.replace("i-cdn.", "i.", 1)
                ids = sorted({int(x) for x in re.findall(
                    rf"//{re.escape(thumb_host)}"
                    rf"/scene/\d+/[a-z0-9]+/(\d+)\.jpg", html)})
                if not ids:
                    ids = list(range(1, 16))
                imgs = [f"https://{host}/{dirpath}/{i}.{ext}" for i in ids]
        if not imgs:
            thumbs = re.findall(
                r'<img[^>]+src="//(i\.dbnaked\.com)/scene/(\d+)/t\d+x\d+/(\d+)\.jpg"',
                html)
            if thumbs:
                host, sid = thumbs[0][0], thumbs[0][1]
                nums = sorted({int(t[2]) for t in thumbs})
                sm = re.match(
                    r".*/content/([a-z]+)/sites/([^/]+)/(.+)", url)
                if sm:
                    cat, site, slug = sm.groups()
                    cdn = host.replace("i.", "i-cdn.", 1)
                    imgs = [f"https://{cdn}/{cat}/{site}/{slug}/{i}.jpg"
                            for i in nums]
        meta = {"title": title, "scene_id": scene_id_m.group(1)
                if scene_id_m else None}
        return imgs, meta

    def parse_scene(self, url):
        html = self.f.get(url)
        title_m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (re.sub(r"\s*[-@].*db[Nn]aked.*$", "", title_m.group(1)).strip()
                 if title_m else sanitize(url.rsplit("/", 1)[-1]))
        norm = html.replace("\\/", "/").replace("\\u0026", "&")
        vids = re.findall(r'"((?:https?:)?//flv\d*\.dbnaked\.com[^"]+\.mp4[^"]*)"',
                          norm)
        hd = bool(re.search(r"\bHD\b|1080p?", html)) or \
            bool(re.search(r"\b720p?\b", html))
        dur = re.search(r'"duration"\s*:\s*(\d+)', html)
        meta = {"title": title, "hd": hd,
                "duration_s": int(dur.group(1)) if dur else None}
        return sorted(set(vids)), meta


class PornPics:
    HOST = "https://www.pornpics.com"

    def __init__(self, f):
        self.f = f

    def query_galleries(self, q, cap=40):
        html = self.f.get(f"{self.HOST}/?q={urllib.parse.quote(q)}")
        gals = list(dict.fromkeys(re.findall(
            r'href="(https://www\.pornpics\.com/galleries/[^"]+)"', html)))
        return gals[:cap]

    def parse_gallery(self, url):
        html = self.f.get(url)
        t = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (re.sub(r"\s*\|.*$", "", t.group(1)).strip()
                 if t else sanitize(url.strip("/").rsplit("/", 1)[-1]))
        rel = re.findall(r"class=['\"]rel-link['\"]\s+href=['\"]([^'\"]+)"
                         r"['\"]", html)
        if not rel:
            rel = re.findall(
                r"href=['\"](https://cdni\.pornpics\.com/[^'\"]+"
                r"\.(?:jpg|png))['\"]", html)
        imgs = [abs_url(url, u) for u in dict.fromkeys(rel)]
        return imgs, {"title": title}


class ImageFap:
    HOST = "https://www.imagefap.com"

    def __init__(self, f):
        self.f = f

    def search_galleries(self, search, pages=5, perpage=10):
        gals = []
        for p in range(pages):
            url = (f"{self.HOST}/gallery.php?type=1&userid=&gen=0&search="
                   f"{urllib.parse.quote(search)}&page={p}&perpage={perpage}")
            try:
                html = self.f.get(url)
            except RuntimeError:
                break
            found = re.findall(r'href="(/gallery\.php\?gid=\d+)"', html)
            new = [f"{self.HOST}{g}" for g in dict.fromkeys(found)
                   if f"{self.HOST}{g}" not in gals]
            gals.extend(new)
            if not new:
                break
        return gals

    def parse_gallery(self, url):
        html = self.f.get(url)
        t = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (re.sub(r"\s*(?:Porn Pics|@.*)*$", "", t.group(1)).strip()
                 if t else sanitize(url))
        photo_links = list(dict.fromkeys(
            re.findall(r'href="(/photo/\d+/[^"]*)"', html)))
        fulls = []
        if photo_links:
            p1 = self.f.get(self.HOST + photo_links[0].split("?")[0])
            norm = p1.replace("\\/", "/")
            fulls = list(dict.fromkeys(re.findall(
                r'"(https://cdnc\.imagefap\.com/images/full/[^"]+)"', norm)))
            if len(fulls) < len(photo_links):
                seen_ids = {re.search(r"/(\d+)\.jpg", u).group(1)
                            for u in fulls}
                for pl in photo_links[1:]:
                    pid = re.search(r"/photo/(\d+)/", pl).group(1)
                    if pid in seen_ids:
                        continue
                    if len(fulls) >= len(photo_links):
                        break
                    try:
                        pp = self.f.get(self.HOST +
                                        pl.split("?")[0]).replace("\\/", "/")
                    except RuntimeError:
                        continue
                    more = re.findall(
                        r'"(https://cdnc\.imagefap\.com/images/full/[^"]+)"',
                        pp)
                    for u in more:
                        mid = re.search(r"/(\d+)\.jpg", u).group(1)
                        if mid not in seen_ids:
                            seen_ids.add(mid)
                            fulls.append(u)
        return fulls, {"title": title}


class BabeSource:
    HOST = "https://babesource.com"

    def __init__(self, f):
        self.f = f

    def search_galleries(self, term, cap=120):
        html = self.f.get(f"{self.HOST}/?s={urllib.parse.quote(term)}")
        gals = list(dict.fromkeys(re.findall(
            r'href="(https://babesource\.com/galleries/[^"]+)"', html)))
        return gals[:cap]

    def parse_gallery(self, url):
        html = self.f.get(url)
        t = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (t.group(1).strip() if t else
                 sanitize(url.strip("/").rsplit("/", 1)[-1]))
        imgs = list(dict.fromkeys(re.findall(
            r'"((?:https?://)?(?:media\.)?babesource\.com/media/galleries/'
            r'[^"]+\.(?:jpg|webp|png))"', html)))
        imgs = [("https:" if u.startswith("//") else "") + u for u in imgs]
        return imgs, {"title": title}


SEED_SOURCES = [
    {"name": "bdsm-gothic", "adapter": "dbnaked_category",
     "path": "/categories/pictures/bdsm/Gothic", "kind": "pictures"},
    {"name": "dbnaked-tattoo-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/general/Tattoo", "kind": "pictures"},
    {"name": "dbnaked-tattoo-alt-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/bdsm/Tattoo", "kind": "pictures"},
    {"name": "dbnaked-alt-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/bdsm/Alternative", "kind": "pictures"},
    {"name": "dbnaked-punk-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/general/Punk", "kind": "pictures"},
    {"name": "dbnaked-feet-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/general/Foot_Fetish", "kind": "pictures"},
    {"name": "dbnaked-footjob-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/general/Footjob", "kind": "pictures"},
    {"name": "dbnaked-feet-bdsm-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/bdsm/Foot_Fetish", "kind": "pictures"},
    {"name": "dbnaked-feet-tube", "adapter": "dbnaked_category",
     "path": "/categories/tube/general/Foot_Fetish", "kind": "tube"},
    {"name": "dbnaked-footjob-tube", "adapter": "dbnaked_category",
     "path": "/categories/tube/general/Footjob", "kind": "tube"},
    {"name": "dbnaked-tattoo-tube", "adapter": "dbnaked_category",
     "path": "/categories/tube/general/Tattoo", "kind": "tube"},
    {"name": "dbnaked-riley-reid-pics", "adapter": "dbnaked_model",
     "path": "/models/general/R/riley-reid", "kind": "pictures"},
    {"name": "dbnaked-riley-reid-tube", "adapter": "dbnaked_model",
     "path": "/models/general/R/riley-reid", "kind": "tube"},
    {"name": "dbnaked-piper-perri-pics", "adapter": "dbnaked_model",
     "path": "/models/general/P/Piper-Perri", "kind": "pictures"},
    {"name": "dbnaked-piper-perri-tube", "adapter": "dbnaked_model",
     "path": "/models/general/P/Piper-Perri", "kind": "tube"},
    {"name": "burningangel-pics", "adapter": "dbnaked_channel",
     "domain": "burningangel.com", "realm": "bdsm", "kind": "pictures"},
    {"name": "burningangel-tube", "adapter": "dbnaked_channel",
     "domain": "burningangel.com", "realm": "bdsm", "kind": "tube"},
    {"name": "pornpics-goth", "adapter": "pornpics_query", "queries":
        ["goth", "gothic", "alt girl", "emo"]},
    {"name": "pornpics-tattoo", "adapter": "pornpics_query",
     "queries": ["tattooed", "tattoo", "pierced", "inked"]},
    {"name": "pornpics-feet", "adapter": "pornpics_query",
     "queries": ["feet", "foot fetish", "foot worship", "barefoot"]},
    {"name": "imagefap-goth-feet", "adapter": "imagefap_search",
     "search": "goth feet", "pages": 8},
    {"name": "imagefap-goth-tattoo", "adapter": "imagefap_search",
     "search": "goth tattoo", "pages": 8},
    {"name": "imagefap-tattooed-feet", "adapter": "imagefap_search",
     "search": "tattooed feet", "pages": 8},
    {"name": "babesource-goth", "adapter": "babesource_search",
     "queries": ["goth", "gothic", "emo"]},
    {"name": "babesource-tattoo", "adapter": "babesource_search",
     "queries": ["tattoo", "tattooed", "pierced", "inked"]},
    {"name": "babesource-feet", "adapter": "babesource_search",
     "queries": ["feet", "foot fetish", "barefoot"]},
]

AESTHETIC_PATTERN = (r"foot|feet|tattoo|goth|punk|/alt$|alt/|ink|"
                     r"pierc|emo")
DYNAMIC_CAP = 12


def discover_dynamic_sources(fetcher, known_paths):
    dn = DbNaked(fetcher)
    found = dn.discover_categories(realms=("general", "bdsm"),
                                   media=("pictures", "tube"),
                                   pattern=AESTHETIC_PATTERN)
    specs = []
    for path in sorted(found):
        if path in known_paths:
            continue
        kind = "tube" if "/tube/" in path else "pictures"
        slug = (path.replace("/categories/", "")
                .strip("/").replace("/", "-").lower())
        slug = re.sub(r"[^a-z0-9\-]+", "-", slug)
        specs.append({"name": f"auto-{slug}", "adapter": "dbnaked_category",
                      "path": path, "kind": kind, "dynamic": True})
        if len(specs) >= DYNAMIC_CAP:
            break
    return specs


def enumerate_source(src, fetcher, female_filter=True):
    ad = DbNaked(fetcher)
    pp = PornPics(fetcher)
    bs = BabeSource(fetcher)
    entries = []
    a = src["adapter"]
    try:
        if a == "dbnaked_category":
            items = ad.category_items(src["path"], src["kind"])
        elif a == "dbnaked_model":
            items = ad.model_items(src["path"], src["kind"])
        elif a == "dbnaked_channel":
            items = ad.channel_items(src["domain"], src.get("realm", "bdsm"),
                                     src["kind"])
        elif a == "pornpics_query":
            items = []
            for q in src["queries"]:
                items += pp.query_galleries(q)
            items = sorted(set(items))
        elif a == "imagefap_search":
            items = ImageFap(fetcher).search_galleries(
                src["search"], pages=src.get("pages", 5))
        elif a == "babesource_search":
            items = []
            for q in src["queries"]:
                items += bs.search_galleries(q)
            items = sorted(set(items))
        else:
            raise ValueError(a)
    except RuntimeError as e:
        log(f"  ENUM FAIL {src['name']}: {e}")
        return entries
    for item_url in items:
        slug = sanitize(item_url.rstrip("/").rsplit("/", 1)[-1])
        entry = {"url": item_url, "slug": slug,
                 "kind": src.get("kind", "pictures")}
        if female_filter and not passes_female_filter(item_url):
            entry["skipped"] = "female-filter"
        entries.append(entry)
    log(f"  {src['name']}: {len(entries)} items "
        f"({sum(1 for e in entries if e.get('skipped'))} filtered)")
    return entries


def materialize_entry(entry, fetcher, hd_only=True):
    kind = entry["kind"]
    url = entry["url"]
    if "dbnaked.com" in url:
        ad = DbNaked(fetcher)
        if kind == "tube" or "/tube/content/" in url:
            files, meta = ad.parse_scene(url)
            if hd_only and not meta.get("hd"):
                return [], meta, "not-hd"
        else:
            files, meta = ad.parse_gallery(url)
    elif "pornpics.com" in url:
        files, meta = PornPics(fetcher).parse_gallery(url)
    elif "imagefap.com" in url:
        files, meta = ImageFap(fetcher).parse_gallery(url)
    elif "babesource.com" in url:
        files, meta = BabeSource(fetcher).parse_gallery(url)
    else:
        return [], {}, "unknown-host"
    return files, meta, None


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def cmd_discover(args):
    fetcher = Fetcher(delay_scale=args.speed)
    master = load_json(args.catalog, {"v": VERSION, "sources": {}})
    if not args.no_discover_extra:
        known_paths = {s.get("path") for s in SEED_SOURCES if s.get("path")}
        for info in master["sources"].values():
            spath = load_json(os.path.join(info["dir"], "_source.json"),
                              None)
            if spath and spath["spec"].get("path"):
                known_paths.add(spath["spec"]["path"])
        extra = discover_dynamic_sources(fetcher, known_paths)
        for spec in extra:
            log(f"dynamic source discovered: {spec['name']} -> "
                f"{spec['path']}")
        sources = list(SEED_SOURCES) + extra
    else:
        sources = list(SEED_SOURCES)
    for src in sources:
        if args.only and args.only.lower() not in src["name"].lower():
            continue
        log(f"source {src['name']} [{src['adapter']}]")
        sdir = os.path.join(args.out, src["name"])
        os.makedirs(sdir, exist_ok=True)
        spath = os.path.join(sdir, "_source.json")
        scat = load_json(spath, {"name": src["name"], "spec": src,
                                 "items": []})
        known = {e["url"]: e for e in scat["items"]}
        entries = enumerate_source(src, fetcher,
                                   female_filter=not args.no_female_filter)
        for e in entries:
            old = known.get(e["url"])
            if old and old.get("files") is not None:
                e["files"] = old["files"]
                e["meta"] = old.get("meta")
                e["state"] = old.get("state")
                e["folder"] = old.get("folder")
            known[e["url"]] = e
        scat["items"] = list(known.values())
        scat["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_json(spath, scat)
        master["sources"][src["name"]] = {
            "dir": sdir, "items": len(scat["items"]),
            "materialized": sum(1 for e in scat["items"]
                                if e.get("files")),
            "updated_at": scat["updated_at"]}
        save_json(args.catalog, master)
    log(f"master catalog: {args.catalog}")
    total_items = sum(v["items"] for v in master["sources"].values())
    total_mat = sum(v["materialized"] for v in master["sources"].values())
    log(f"totals: {len(master['sources'])} sources, {total_items} items,"
        f" {total_mat} materialized")


def cmd_download(args):
    fetcher = Fetcher(delay_scale=args.speed)
    master = load_json(args.catalog, {"v": VERSION, "sources": {}})
    dl_root = args.out
    stats = {"files": 0, "bytes": 0, "skip": 0, "fail": 0,
             "filtered": 0}
    for name, info in sorted(master["sources"].items()):
        if args.only and args.only.lower() not in name.lower():
            continue
        spath = os.path.join(info["dir"], "_source.json")
        scat = load_json(spath, None)
        if not scat:
            continue
        log(f"== {name} ==")
        for e in scat["items"]:
            if e.get("skipped"):
                stats["filtered"] += 1
                continue
            if e.get("files") is None:
                files, meta, why = materialize_entry(
                    e, fetcher, hd_only=args.hd_only)
                if why == "not-hd":
                    e["state"] = "not-hd"
                    continue
                if why or not files:
                    e["state"] = why or "no-files"
                    continue
                e["files"] = [{"url": u, "file": None, "bytes": 0,
                               "done": False} for u in files]
                e["meta"] = meta
            if not e.get("folder"):
                e["folder"] = sanitize(e.get("meta", {}).get("title")
                                       or e["slug"])
            if args.dry_run:
                for fe in e["files"]:
                    if not fe["done"]:
                        stats["files"] += 1
                        stats["bytes"] += fe["bytes"] or 0
                continue
            folder = os.path.join(info["dir"], e["folder"])
            os.makedirs(folder, exist_ok=True)
            for i, fe in enumerate(e["files"], 1):
                target = fe["file"] or os.path.join(
                    folder, f"{e['slug']}_{i:03d}" +
                    os.path.splitext(urllib.parse.urlsplit(fe["url"]).path)[1])
                fe["file"] = target
                if os.path.exists(target) and os.path.getsize(target) > 0:
                    fe["done"] = True
                    stats["skip"] += 1
                    continue
                try:
                    data = fetcher.get(fe["url"], binary=True)
                    tmp = target + ".part"
                    with open(tmp, "wb") as fh:
                        fh.write(data)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(tmp, target)
                    fe["done"] = True
                    fe["bytes"] = len(data)
                    stats["files"] += 1
                    stats["bytes"] += len(data)
                except Exception as ex:
                    stats["fail"] += 1
                    log(f"  DL FAIL {fe['url'][:80]}: {ex}")
            save_json(spath, scat)
        save_json(spath, scat)
    log(f"download summary: +{stats['files']} files "
        f"({stats['bytes'] / 1e6:.1f} MB), {stats['skip']} resumed-skips,"
        f" {stats['fail']} failures, {stats['filtered']} filtered")


def cmd_launch(args):
    py = sys.executable
    script = os.path.abspath(__file__)
    logdir = os.path.dirname(args.catalog)
    logf = os.path.join(logdir, "ingest.log")
    cmd = [py, "-u", script,
           "--discover", "--download",
           "--out", args.out, "--catalog", args.catalog]
    if not args.hd_only:
        cmd.append("--include-non-hd")
    if args.only:
        cmd += ["--only", args.only]
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    import subprocess
    logh = open(logf, "ab", buffering=0)
    try:
        logh.write(f"\n=== run started {datetime.now().isoformat()} ===\n"
                   .encode())
        subprocess.Popen(cmd, stdout=logh, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL,
                         creationflags=0x00000008 | 0x00000200,
                         close_fds=False, env=env, cwd=logdir)
    finally:
        logh.close()
    bat = os.path.join(logdir, "run_ingest.bat")
    with open(bat, "w", encoding="utf-8") as fh:
        fh.write("@echo off\r\nrem manual re-run entry point\r\n"
                 f'"{py}" -u "{script}" --discover --download '
                 f'--out "{args.out}" --catalog "{args.catalog}" '
                 f'{"--hd-only " if args.hd_only else "--include-non-hd "}'
                 f'{("--only " + args.only + " ") if args.only else ""}'
                 f'>> "{logf}" 2>&1\r\n')
    log(f"detached pid launched\nlog: {logf}\nmanual rerun: {bat}")


def main(argv=None):
    p = argparse.ArgumentParser(prog=APP)
    p.add_argument("--out", default=r"D:\new")
    p.add_argument("--catalog",
                   default=os.path.join(r"D:\new", "_ingest_catalog.json"))
    p.add_argument("--discover", action="store_true")
    p.add_argument("--download", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--launch", action="store_true")
    p.add_argument("--hd-only", action="store_true", default=True)
    p.add_argument("--include-non-hd", dest="hd_only",
                   action="store_false")
    p.add_argument("--no-female-filter", action="store_true")
    p.add_argument("--no-discover-extra", action="store_true")
    p.add_argument("--only", default=None)
    p.add_argument("--speed", type=float, default=1.0)
    args = p.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    ran = False
    if args.discover:
        cmd_discover(args)
        ran = True
    if args.download:
        cmd_download(args)
        ran = True
    if args.launch:
        cmd_launch(args)
        ran = True
    if not ran:
        p.print_help()


if __name__ == "__main__":
    main()

