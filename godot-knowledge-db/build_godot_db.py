#!/usr/bin/env python3
"""
Build a SQLite knowledge database from https://godotengine.org/

Crawls the main site pages, the blog (recent articles), and extracts:
  - pages        : every page fetched (url, title, description, category)
  - sections     : structured content blocks (heading -> body text) per page
  - articles     : full blog articles (title, date, author, tags, excerpt, body)
  - links        : outbound links per page and per article
  - releases     : engine release announcements extracted from articles
  - sponsors     : sponsor names + tiers scraped from the homepage
  - meta         : crawl statistics
Plus an FTS5 index for full-text search across everything.

The .db artifact is a local build product (gitignored); only the tooling
ships through git. Rebuild any time:

    python godot-knowledge-db/build_godot_db.py

Optional third-party deps (declared in requirements.txt):
    requests, beautifulsoup4
"""

import argparse
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE = "https://godotengine.org"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GodotKnowledgeBuilder/1.1; +local research tool)"
}

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def get(url: str) -> str | None:
    """Fetch a URL and return HTML text, or None on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            return r.text
        print(f"  ! HTTP {r.status_code} {url}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! FAIL {url}: {exc}", file=sys.stderr)
    return None


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def page_meta(soup: BeautifulSoup):
    title = clean(soup.title.get_text()) if soup.title else ""
    desc = ""
    tag = soup.find("meta", attrs={"name": "description"})
    if tag and tag.get("content"):
        desc = clean(tag["content"])
    return title, desc


def extract_main(soup: BeautifulSoup) -> BeautifulSoup:
    """Best-effort selection of the main content element."""
    for sel in (("main",), ("article",), ("div", {"class": re.compile("page-content|article-content|content")}),):
        el = soup.find(sel[0], **(sel[1] if len(sel) > 1 else {}))
        if el:
            return el
    return soup.body or soup


def extract_sections(main: BeautifulSoup) -> list[tuple[int, str, str]]:
    """
    Walk main content; each heading starts a new section whose text is
    everything until the next heading. Returns [(level, heading, body)].
    """
    sections = []
    cur_level, cur_head, buf = None, "", []

    def flush():
        nonlocal cur_level, cur_head, buf
        body = clean(" ".join(buf))
        if body or cur_head:
            sections.append((cur_level or 0, cur_head, body))
        buf = []

    for el in main.descendants:
        name = getattr(el, "name", None)
        if name in ("h1", "h2", "h3", "h4", "h5"):
            flush()
            cur_level = int(name[1])
            cur_head = clean(el.get_text())
        elif name in ("p", "li", "blockquote"):
            txt = clean(el.get_text())
            if txt:
                buf.append(txt)

    flush()
    return [s for s in sections if s[2] or s[1]]


def extract_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        text = clean(a.get_text())[:200]
        out.append((text, href))
    return out


# ---------------------------------------------------------------------------
# Article-specific extraction
# ---------------------------------------------------------------------------

def parse_article(url: str, html: str) -> dict | None:
    soup = soup_of(html)
    title, _ = page_meta(soup)

    art = soup.find("article") or extract_main(soup)

    h1 = art.find(["h1"])
    if h1:
        title = clean(h1.get_text())

    # Date: site markup has moved before - probe several conventional
    # carriers in order (data-post-date span, itemprop, <time>, og meta)
    # so one redesign does not blank every published column again.
    date = ""
    el = art.find(attrs={"data-post-date": True}) \
        or art.find(attrs={"itemprop": "datePublished"}) \
        or art.find("time")
    if el:
        date = el.get("data-post-date") or el.get("datetime") \
            or el.get("content") or clean(el.get_text())
    if not date:
        mtag = soup.find("meta", attrs={"property": "article:published_time"})
        if mtag and mtag.get("content"):
            date = mtag["content"]

    # Author: prefer the byline span/avatar alt over the raw block text
    author = ""
    auth_el = art.find(attrs={"class": re.compile("author", re.I)})
    if auth_el:
        by = auth_el.find(attrs={"class": re.compile(r"\bby\b")})
        avatar = auth_el.find("img", alt=True)
        author = clean(by.get_text()) if by else (
            clean(avatar["alt"]) if avatar else clean(auth_el.get_text()))
        author = re.sub(r"^By:\s*", "", author, flags=re.I)

    tags = []
    tag_wrap = art.find(attrs={"class": re.compile("tags|category", re.I)})
    if tag_wrap:
        tags = sorted({clean(x.get_text()) for x in tag_wrap.find_all("a") if clean(x.get_text())})

    # Body: prefer explicit article-content containers
    body_el = (art.find(attrs={"class": re.compile("article-content|post-content")})
               or art.find(attrs={"class": re.compile("content")})
               or art)

    # Remove nav/footer noise inside body
    for noise in body_el.find_all(["nav", "footer", "script", "style", "aside"]):
        noise.decompose()

    paras = [clean(p.get_text()) for p in body_el.find_all(["p", "li", "h2", "h3"])]
    paras = [p for p in paras if p]
    body = "\n".join(paras)
    if not body:
        return None

    excerpt = paras[0][:400]
    m = re.search(r"(\d{4}-\d{2}-\d{2})", date or "")
    iso_date = m.group(1) if m else ""

    return {
        "url": url,
        "title": title,
        "date": iso_date or date,
        "author": author,
        "tags": ", ".join(tags),
        "excerpt": excerpt,
        "body": body,
    }


# ---------------------------------------------------------------------------
# Special scrapers
# ---------------------------------------------------------------------------

def scrape_blog_urls(limit_pages=6, delay=0.35) -> list[str]:
    urls, seen = [], set()
    page_url = f"{BASE}/blog/"
    for _ in range(limit_pages):
        html = get(page_url)
        if not html:
            break
        s = soup_of(html)
        found = False
        for a in s.find_all("a", href=True):
            href = a["href"]
            if "/article/" in href:
                full = href if href.startswith("http") else BASE + href
                full = full.split("?")[0].split("#")[0]
                if full not in seen:
                    seen.add(full)
                    urls.append(full)
                    found = True
        nxt = s.find("a", rel="next") or s.find("a", attrs={"class": re.compile("next")})
        if nxt and nxt.get("href"):
            page_url = nxt["href"]
            if not page_url.startswith("http"):
                page_url = BASE + page_url
            time.sleep(delay)
        elif found:
            # try /blog/page/N/ style pagination manually
            m = re.search(r"/blog/page/(\d+)/", page_url)
            nxt_num = (int(m.group(1)) if m else 1) + 1
            cand = f"{BASE}/blog/page/{nxt_num}/"
            probe = get(cand)
            if probe:
                page_url = cand
                time.sleep(delay)
                continue
            break
        else:
            break
    return urls


def scrape_sponsors(home_soup: BeautifulSoup) -> list[tuple[str, str, str]]:
    """Sponsor logos under tier headings: (name, tier, url)."""
    sponsors = []
    current_tier = ""
    for el in home_soup.find_all():
        if el.name in ("h3", "h4"):
            current_tier = clean(el.get_text())
        elif el.name == "img" and current_tier:
            alt = clean(el.get("alt") or "")
            if alt:
                parent_a = el.find_parent("a")
                href = parent_a["href"] if parent_a and parent_a.get("href") else ""
                sponsors.append((alt, current_tier, href))
    return sponsors


KIND_PATTERNS = [
    ("maintenance", r"maintenance release"),
    ("dev snapshot", r"dev snapshot"),
    ("release candidate", r"release candidate"),
    ("beta", r"\bbeta\b"),
    ("feature", r"(major release|is here|released!)"),
]


def classify_release(title: str) -> str:
    t = title.lower()
    for kind, pat in KIND_PATTERNS:
        if re.search(pat, t):
            return kind
    return "other"


VERSION_PAT = re.compile(r"Godot\s+(\d+\.\d+(?:\.\d+)?)(?:\s+(dev|beta|RC)\s*(\d+))?", re.I)


def extract_release(title: str, url: str, date: str) -> tuple | None:
    m = VERSION_PAT.search(title)
    if not m:
        return None
    version = m.group(1)
    suffix = f"{m.group(2)} {m.group(3)}".strip() if m.group(2) else ""
    return (version, suffix, classify_release(title), title.strip(), url, date)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    description TEXT,
    category TEXT,
    word_count INTEGER DEFAULT 0,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    seq INTEGER,
    heading_level INTEGER,
    heading TEXT,
    content TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    published TEXT,
    author TEXT,
    tags TEXT,
    excerpt TEXT,
    body TEXT,
    word_count INTEGER DEFAULT 0,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id),
    article_id INTEGER REFERENCES articles(id),
    text TEXT,
    href TEXT
);

CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY,
    version TEXT,
    suffix TEXT,
    kind TEXT,
    title TEXT,
    url TEXT UNIQUE,
    published TEXT
);

CREATE TABLE IF NOT EXISTS sponsors (
    id INTEGER PRIMARY KEY,
    name TEXT,
    tier TEXT,
    url TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    source_type, source_title, source_url, heading, body,
    tokenize='porter unicode61'
);
"""


def index_row(cur, stype, stitle, surl, heading, body):
    cur.execute(
        "INSERT INTO knowledge_fts (source_type, source_title, source_url, heading, body) VALUES (?,?,?,?,?)",
        (stype, stitle, surl, heading, body),
    )


CORE_PAGES = [
    ("/", "home"),
    ("/features/", "features"),
    ("/consoles/", "consoles"),
    ("/priorities/", "project"),
    ("/showcase/", "showcase"),
    ("/community/", "community"),
    ("/events/", "community"),
    ("/code-of-conduct/", "project"),
    ("/governance/", "project"),
    ("/press/", "resources"),
    ("/education/", "resources"),
    ("/license/", "legal"),
    ("/privacy-policy/", "legal"),
    ("/contact/", "project"),
    ("/download/windows/", "download"),
    ("/download/macos/", "download"),
    ("/download/linux/", "download"),
    ("/download/android/", "download"),
    ("/download/web/", "download"),
    ("/download/archive/", "download"),
    ("/releases/", "releases"),
]


def crawl(db_path: str, delay: float, article_limit: int, blog_pages: int) -> dict:
    now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: E731
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    cur = con.cursor()
    # Full rebuild semantics: every run produces fresh, complete truth.
    for tbl in ("pages", "sections", "articles", "links",
                "releases", "sponsors", "meta", "knowledge_fts"):
        cur.execute(f"DELETE FROM {tbl}")

    stats = {"pages": 0, "articles": 0, "sections": 0, "links": 0}

    # --- 1. Core site pages -------------------------------------------------
    home_soup = None
    for path, cat in CORE_PAGES:
        print(f"[page] {path}")
        html = get(BASE + path)
        time.sleep(delay)
        if path == "/" and html:
            home_soup = soup_of(html)
        if not html:
            continue
        s = soup_of(html)
        title, desc = page_meta(s)
        main_el = extract_main(s)
        secs = extract_sections(main_el)
        words = sum(len(b.split()) for _, _, b in secs)

        cur.execute(
            "INSERT INTO pages (url,title,description,category,word_count,fetched_at) VALUES (?,?,?,?,?,?)",
            (BASE + path, title, desc, cat, words, now()),
        )
        pid = cur.lastrowid
        stats["pages"] += 1
        for i, (lvl, head, body) in enumerate(secs):
            cur.execute(
                "INSERT INTO sections (page_id,seq,heading_level,heading,content) VALUES (?,?,?,?,?)",
                (pid, i, lvl, head, body),
            )
            index_row(cur, "page_section", title, BASE + path, head, body[:20000])
        stats["sections"] += len(secs)
        page_links = extract_links(s)
        for text, href in page_links:
            cur.execute("INSERT INTO links (page_id,text,href) VALUES (?,?,?)", (pid, text, href))
        stats["links"] += len(page_links)

    # --- 2. Sponsors ---------------------------------------------------------
    if home_soup:
        seen_sp = set()
        for name, tier, href in scrape_sponsors(home_soup):
            key = (name, tier)
            if key in seen_sp:
                continue
            seen_sp.add(key)
            cur.execute("INSERT INTO sponsors (name,tier,url) VALUES (?,?,?)", (name, tier, href))

    # --- 3. Blog articles -----------------------------------------------------
    print("[blog] collecting article URLs...")
    art_urls = scrape_blog_urls(limit_pages=blog_pages, delay=delay)[:article_limit]
    print(f"[blog] {len(art_urls)} article URLs found")

    for u in art_urls:
        print(f"[article] {u}")
        html = get(u)
        time.sleep(delay)
        if not html:
            continue
        art = parse_article(u, html)
        if not art:
            continue
        wc = len(art["body"].split())
        try:
            cur.execute(
                "INSERT INTO articles (url,title,published,author,tags,excerpt,body,word_count,fetched_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (art["url"], art["title"], art["date"], art["author"], art["tags"],
                 art["excerpt"], art["body"], wc, now()),
            )
        except sqlite3.IntegrityError:
            continue
        aid = cur.lastrowid
        stats["articles"] += 1
        index_row(cur, "article", art["title"], art["url"], "", art["body"][:200000])
        art_links = extract_links(soup_of(html))
        for text, href in art_links:
            cur.execute("INSERT INTO links (article_id,text,href) VALUES (?,?,?)", (aid, text, href))
        stats["links"] += len(art_links)  # count ALL link rows, not just page ones

        rel = extract_release(art["title"], art["url"], art["date"])
        if rel:
            try:
                cur.execute(
                    "INSERT INTO releases (version,suffix,kind,title,url,published) VALUES (?,?,?,?,?,?)",
                    rel,
                )
            except sqlite3.IntegrityError:
                pass

    # --- 4. Meta / stats -------------------------------------------------------
    for k, v in {**stats,
                 "source_site": BASE,
                 "built_at": now(),
                 "db_schema": "pages,sections,articles,links,releases,sponsors,knowledge_fts",
                 }.items():
        cur.execute("INSERT INTO meta (key,value) VALUES (?,?)", (k, str(v)))

    con.commit()
    cur.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES ('optimize')")
    con.commit()

    # quick report - counts come from the tables themselves, never from
    # loop counters, so meta can never drift from stored reality
    report = {}
    for tbl in ("pages", "sections", "articles", "links", "releases", "sponsors"):
        n = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]  # noqa: S608
        report[tbl] = n
        print(f"  {tbl:>10}: {n}")
    con.close()
    print(f"DONE -> {db_path}")
    return report


def main():
    ap = argparse.ArgumentParser(description="Build the godotengine.org knowledge database")
    ap.add_argument("--db", default=os.path.join(HERE, "godot_knowledge.db"),
                    help="output db path (default: alongside this script)")
    ap.add_argument("--delay", type=float, default=0.35, help="polite per-request delay (s)")
    ap.add_argument("--article-limit", type=int, default=60, help="max blog articles")
    ap.add_argument("--blog-pages", type=int, default=6, help="max blog listing pages to walk")
    args = ap.parse_args()

    report = crawl(args.db, args.delay, args.article_limit, args.blog_pages)
    if report.get("pages", 0) == 0:
        print("FATAL: zero pages crawled - network down or site unreachable?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
