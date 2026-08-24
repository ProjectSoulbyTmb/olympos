#!/usr/bin/env python3
"""
Query the godotengine.org knowledge database.

Usage:
    python godot-knowledge-db/query_godot_db.py search "gdscript typed arrays"
    python godot-knowledge-db/query_godot_db.py articles 4.5
    python godot-knowledge-db/query_godot_db.py releases
    python godot-knowledge-db/query_godot_db.py pages
    python godot-knowledge-db/query_godot_db.py sponsors
    python godot-knowledge-db/query_godot_db.py stats

Search runs over an FTS5 index covering page sections and full article
bodies; results carry snippets so you can triage without opening URLs.
"""

import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "godot_knowledge.db")


def open_db(path: str = DB_PATH) -> sqlite3.Connection:
    if not os.path.isfile(path):
        sys.exit(f"no knowledge db at {path}\n"
                 f"build it first:  python godot-knowledge-db/build_godot_db.py")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def fts_escape(q: str) -> str:
    """Turn a raw user query into a safe FTS5 query.

    Default: each whitespace token becomes its own quoted phrase, so
    'typed arrays' means typed AND arrays (predictable recall).
    Exact-phrase mode wraps the whole string as one phrase instead.
    """
    if args_phrase.get("on"):
        return '"' + q.replace('"', '""') + '"'
    return " ".join('"' + t.replace('"', '""') + '"' for t in q.split())


# set by cmd_search before escaping; module-level flag keeps the
# helper signature simple for the verify suite
args_phrase = {"on": False}


def cmd_search(con: sqlite3.Connection, args) -> int:
    args_phrase["on"] = bool(getattr(args, "phrase", False))
    cur = con.execute(
        """
        SELECT source_type, source_title, source_url, heading,
               snippet(knowledge_fts, 4, '[', ']', ' ... ', 14) AS snip,
               bm25(knowledge_fts) AS rank
        FROM knowledge_fts
        WHERE knowledge_fts MATCH ?
        ORDER BY rank LIMIT ?""",
        (fts_escape(args.query), args.limit),
    )
    rows = cur.fetchall()
    if not rows:
        print(f"no matches for {args.query!r}")
        return 1
    for i, r in enumerate(rows, 1):
        head = f"[{r['source_type']}] {r['source_title']}"
        if r["heading"]:
            head += f" :: {r['heading']}"
        print(f"{i:>3}. {head}")
        print(f"      {r['source_url']}")
        print(f"      {r['snip']}")
    return 0


def cmd_articles(con: sqlite3.Connection, args) -> int:
    rows = con.execute(
        """SELECT title, published, author, tags, url FROM articles
           WHERE title LIKE ? OR tags LIKE ?
           ORDER BY published DESC""",
        (f"%{args.filter}%", f"%{args.filter}%"),
    ).fetchall()
    for r in rows:
        print(f"{r['published'] or '????-??-??'}  {r['title']}")
        meta = " / ".join(x for x in (r["author"], r["tags"]) if x)
        if meta:
            print(f"                  {meta[:100]}")
        print(f"                  {r['url']}")
    print(f"-- {len(rows)} article(s)")
    return 0 if rows else 1


def cmd_releases(con: sqlite3.Connection, args) -> int:
    rows = con.execute(
        "SELECT version, suffix, kind, published, title, url FROM releases"
        " ORDER BY published DESC"
    ).fetchall()
    for r in rows:
        v = r["version"] + ((" " + r["suffix"]) if r["suffix"] else "")
        print(f"{r['published'] or '????-??-??'}  Godot {v:<16} [{r['kind']}] {r['title']}")
    print(f"-- {len(rows)} release announcement(s)")
    return 0


def cmd_pages(con: sqlite3.Connection, args) -> int:
    rows = con.execute(
        "SELECT category, title, word_count, url FROM pages ORDER BY category, title"
    ).fetchall()
    for r in rows:
        print(f"[{r['category']:<9}] {r['title']:<60} {r['word_count']:>6} words")
        print(f"             {r['url']}")
    print(f"-- {len(rows)} page(s)")
    return 0


def cmd_sponsors(con: sqlite3.Connection, args) -> int:
    rows = con.execute("SELECT tier, name, url FROM sponsors ORDER BY id").fetchall()
    tier = None
    for r in rows:
        if r["tier"] != tier:
            tier = r["tier"]
            print(f"\n== {tier or '(no tier)'} ==")
        print(f"  {r['name']}" + (f"  <{r['url']}>" if r["url"] else ""))
    print(f"\n-- {len(rows)} sponsor logo(s)")
    return 0


def cmd_stats(con: sqlite3.Connection, args) -> int:
    print("-- table counts (derived from tables, not crawl counters)")
    for tbl in ("pages", "sections", "articles", "links", "releases", "sponsors"):
        n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]  # noqa: S608
        print(f"  {tbl:>10}: {n}")
    print("-- crawl metadata")
    for r in con.execute("SELECT key, value FROM meta ORDER BY key"):
        print(f"  {r['key']:<12}: {r['value']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="full-text search across everything")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--phrase", action="store_true",
                   help="treat the query as one exact phrase")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("articles", help="list articles (optional title/tag filter)")
    p.add_argument("filter", nargs="?", default="")
    p.set_defaults(fn=cmd_articles)

    sub.add_parser("releases", help="list engine release announcements").set_defaults(fn=cmd_releases)
    sub.add_parser("pages", help="list crawled site pages").set_defaults(fn=cmd_pages)
    sub.add_parser("sponsors", help="list sponsors by tier").set_defaults(fn=cmd_sponsors)
    sub.add_parser("stats", help="db statistics and crawl metadata").set_defaults(fn=cmd_stats)

    args = ap.parse_args()
    with open_db() as con:
        return args.fn(con, args)


if __name__ == "__main__":
    sys.exit(main())
