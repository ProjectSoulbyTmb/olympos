#!/usr/bin/env python3
"""
Verify suite for the GODOT KNOWLEDGE DB tool (godot-knowledge-db/).

Hermetic by design: never touches the network (the crawler is a manual,
operator-run tool), so this suite is safe to ride the shared CI gate.
It proves tool integrity always, and data integrity whenever a locally
built godot_knowledge.db artifact exists.

Run:  python godot-knowledge-db/verify_godot_knowledge_db.py
Exit: 0 green, 1 any failure.
"""

import os
import py_compile
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.join(HERE, "build_godot_db.py")
QUERIER = os.path.join(HERE, "query_godot_db.py")
DB_PATH = os.path.join(HERE, "godot_knowledge.db")

EXPECTED_TABLES = ("pages", "sections", "articles",
                   "links", "releases", "sponsors", "meta", "knowledge_fts")

RESULTS = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name))
        print(f"  PASS  {name:<46} {detail}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((False, name))
        print(f"  FAIL  {name:<46} {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# tool integrity (always runs)
# ---------------------------------------------------------------------------

def t_scripts_compile():
    for path in (BUILDER, QUERIER):
        py_compile.compile(path, doraise=True, cfile=os.devnull if os.name != "nt"
                           else os.path.join(tempfile.gettempdir(), "_gkdb.pyc"))
    return "builder + querier compile"


def t_schema_declares_all_tables():
    src = open(BUILDER, encoding="utf-8").read()
    m = re.search(r'SCHEMA\s*=\s*"""(.*?)"""', src, re.S)
    assert m, "SCHEMA block not found in builder"
    schema = m.group(1)
    missing = [t for t in EXPECTED_TABLES if f"CREATE {'VIRTUAL ' if t == 'knowledge_fts' else ''}TABLE IF NOT EXISTS {t}" not in schema]
    assert not missing, f"schema missing tables: {missing}"
    assert "fts5" in schema and "porter unicode61" in schema, "FTS5 index misconfigured"
    # every crawl run must start from clean truth
    assert "DELETE FROM" in src, "builder lost its full-rebuild semantics"
    return f"{len(EXPECTED_TABLES)} tables + fts5(porter)"


def t_release_classifier():
    sys.path.insert(0, HERE)
    import build_godot_db as b  # noqa: E402 - suite-local import

    cases = {
        "Godot 4.5 is here!": ("4.5", "", "feature"),
        "Maintenance release: Godot 4.4.1": ("4.4.1", "", "maintenance"),
        "Dev snapshot: Godot 4.5 dev 6": ("4.5", "dev 6", "dev snapshot"),
        "Godot 4.3 beta 2": ("4.3", "beta 2", "beta"),
        "Release candidate: Godot 4.3 RC 1": ("4.3", "RC 1", "release candidate"),
        "Meet the team: Jane": None,
    }
    for title, want in cases.items():
        got = b.extract_release(title, "https://x", "2026-01-01")
        if want is None:
            assert got is None, f"{title!r} should not parse as release, got {got}"
        else:
            assert got is not None, f"{title!r} should parse"
            ver, suf, kind = got[0], got[1], got[2]
            assert (ver, suf, kind) == want, f"{title!r}: got {(ver, suf, kind)}, want {want}"
    return f"{len(cases)} classifier cases"


def t_fts_query_escaper():
    from query_godot_db import fts_escape, args_phrase  # noqa: E402 - suite-local import
    args_phrase["on"] = False
    assert fts_escape("typed arrays") == '"typed" "arrays"', fts_escape("typed arrays")
    assert fts_escape('he said "hi"') == '"he" "said" """hi"""'
    args_phrase["on"] = True
    assert fts_escape("typed arrays") == '"typed arrays"'
    return "default AND-of-tokens, --phrase mode wraps one phrase"


def t_article_date_carriers():
    """Regression: the site dropped <time> elements once already - every
    conventional date carrier must keep working."""
    import build_godot_db as b  # noqa: E402 - suite-local import

    variants = [
        ('<html><body><article><h1>T</h1>'
         '<span class="date" data-post-date="2026-08-18 12:00:00 +0000">18 August 2026</span>'
         '<div class="article-author"><span class="by">Thaddeus Crews</span></div>'
         '<p>body</p></article></body></html>',
         "2026-08-18", "Thaddeus Crews"),
        ('<html><body><article><h1>T</h1>'
         '<time datetime="2026-01-02">Jan 2</time><p>body</p></article></body></html>',
         "2026-01-02", ""),
        ('<html><head><meta property="article:published_time" content="2025-12-31"></head>'
         '<body><article><h1>T</h1><p>body</p></article></body></html>',
         "2025-12-31", ""),
    ]
    for html, want_date, want_author in variants:
        art = b.parse_article("https://godotengine.org/article/x/", html)
        assert art, "parse_article returned None"
        assert art["date"].startswith(want_date), \
            f"date: expected {want_date}, got {art['date']!r}"
        if want_author:
            assert art["author"] == want_author, \
                f"author: expected {want_author!r}, got {art['author']!r}"
    return "data-post-date / <time> / og-meta all parse"


# ---------------------------------------------------------------------------
# data integrity (only when a local artifact exists)
# ---------------------------------------------------------------------------

def t_db_artifact():
    if not os.path.isfile(DB_PATH):
        return "SKIP: no local artifact (network build is operator-run)" \
               " - tool checks above still prove the gate"
    con = sqlite3.connect(DB_PATH)
    try:
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in EXPECTED_TABLES if t not in names]
        assert not missing, f"artifact missing tables: {missing}"

        counts = {}
        for t in ("pages", "sections", "articles", "links", "releases"):
            counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608
        for t in ("pages", "sections", "articles", "links"):
            assert counts[t] > 0, f"{t} table empty in built artifact"

        # stored meta must agree with table truth (no counter drift)
        meta = dict(con.execute("SELECT key, value FROM meta"))
        for k in ("pages", "articles", "sections", "links"):
            assert k in meta, f"meta missing stat {k}"
            assert int(meta[k]) == counts[k], \
                f"meta[{k}]={meta[k]} disagrees with table count {counts[k]}"

        # provenance: every article comes from the crawled site
        foreign = con.execute(
            "SELECT COUNT(*) FROM articles WHERE url NOT LIKE 'https://godotengine.org/%'"
        ).fetchone()[0]
        assert foreign == 0, f"{foreign} article urls outside source site"

        # release rows parse into engine versions
        bad = [v for (v,) in con.execute("SELECT DISTINCT version FROM releases")
               if not re.fullmatch(r"\d+\.\d+(\.\d+)?", v)]
        assert not bad, f"malformed release versions: {bad[:5]}"

        # the search index actually answers queries
        hits = con.execute(
            "SELECT COUNT(*) FROM knowledge_fts WHERE knowledge_fts MATCH 'godot'"
        ).fetchone()[0]
        assert hits > 0, "FTS index returned zero hits for 'godot'"
        return (f"{counts['pages']}p/{counts['sections']}s/{counts['articles']}a/"
                f"{counts['releases']}rel, fts hits={hits}, meta consistent")
    finally:
        con.close()


def main() -> int:
    print("godot-knowledge-db verify")
    check("scripts compile", t_scripts_compile)
    check("schema declares all tables", t_schema_declares_all_tables)
    check("release classifier", t_release_classifier)
    check("fts escaper", t_fts_query_escaper)
    check("article date carriers", t_article_date_carriers)
    check("db artifact integrity", t_db_artifact)

    red = [n for ok, n in RESULTS if not ok]
    print(f"-- {len(RESULTS) - len(red)}/{len(RESULTS)} green" + (f"; RED: {red}" if red else ""))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
