#!/usr/bin/env python3
"""build_haven_db - compile HAVEN, the cumulative shared knowledge base
for the three sibling kernels: VENUS, APHRODITE, RILEY.

    python build_haven_db.py [--repo ROOT] [--rotate] [--list]
    python build_haven_db.py --add DOMAIN "Title" --body-file note.md

HAVEN is cumulative: rebuilds UPSERT topic cards (unique per
domain+title) and never drops existing knowledge. Future additions land
via --add (operator) or by extending build_corpus() (code).

Access law: exactly three consumers. One capability token per consumer,
stored sha256-hashed in the DB and dropped as plain text into that
kernel's private data dir:

  venus      -> <repo>/assistant/data/haven.token
  aphrodite  -> D:/aphrodite/data/haven.token
  riley      -> D:/riley/data/haven.token

The server refuses any request whose token does not hash to an enabled
consumer row. No other process holds a token, so nothing else can learn
from HAVEN. Tokens persist across rebuilds; only --rotate re-mints.
"""
import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

CONSUMERS = ["venus", "aphrodite", "riley"]

# consumer -> private data dirs (first writable wins)
TOKEN_DIRS = {
    "venus": [os.path.join("assistant", "data")],
    "aphrodite": [os.path.join("D:\\", "aphrodite", "data")],
    "riley": [os.path.join("D:\\", "riley", "data")],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS consumers (
  name TEXT PRIMARY KEY,
  token_sha256 TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  minted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain TEXT NOT NULL,
  title TEXT NOT NULL,
  body_md TEXT NOT NULL,
  keywords TEXT NOT NULL DEFAULT '',
  source_path TEXT,
  source_sha256 TEXT,
  added_at TEXT NOT NULL,
  UNIQUE(domain, title));
CREATE INDEX IF NOT EXISTS idx_topics_domain ON topics(domain);
CREATE VIRTUAL TABLE IF NOT EXISTS topics_fts USING fts5(
  title, body_md, keywords, content='topics', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS topics_ai AFTER INSERT ON topics BEGIN
  INSERT INTO topics_fts(rowid,title,body_md,keywords)
  VALUES(new.id,new.title,new.body_md,new.keywords); END;
CREATE TRIGGER IF NOT EXISTS topics_ad AFTER DELETE ON topics BEGIN
  INSERT INTO topics_fts(topics_fts,rowid,title,body_md,keywords)
  VALUES('delete',old.id,old.title,old.body_md,old.keywords); END;
CREATE TRIGGER IF NOT EXISTS topics_au AFTER UPDATE ON topics BEGIN
  INSERT INTO topics_fts(topics_fts,rowid,title,body_md,keywords)
  VALUES('delete',old.id,old.title,old.body_md,old.keywords);
  INSERT INTO topics_fts(rowid,title,body_md,keywords)
  VALUES(new.id,new.title,new.body_md,new.keywords); END;
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read(repo, rel):
    full = os.path.join(repo, rel)
    with open(full, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def card(domain, title, body, kw="", src_rel=None, repo=None):
    repo = repo or REPO[0]
    src_hash = None
    if src_rel and repo:
        try:
            src_hash = sha256_file(os.path.join(repo, src_rel))
        except OSError:
            pass
    return {"domain": domain, "title": title, "body": body.strip(),
            "kw": (kw or "").lower(), "src": src_rel, "hash": src_hash}


REPO = [None]  # set in main; card() reads it for source hashing


# --------------------------------------------------------------- corpus

def build_corpus():
    """Compile topic cards from LIVE workspace sources."""
    c = []
    add = lambda *a, **k: c.append(card(*a, **k))

    # ---- the studio suite, from its own live README ----
    try:
        txt = _read(REPO[0], os.path.join("riley-studio", "README.md"))
        add("studio-suite", "Riley Studio overview", txt[:6000],
            "riley studio engine api models canvas gallery timeline",
            os.path.join("riley-studio", "README.md"))
    except OSError:
        pass

    try:
        sys.path.insert(0, os.path.join(REPO[0], "riley-studio"))
        from engine import graphs as g
        add("studio-suite", "Generation kinds (engine API)",
            "POST /api/generate {kind,...}. Kinds:\n- "
            + "\n- ".join(sorted(g.BUILDERS))
            + "\nPlus 'upscale' and export_mp4/export_gif (steps spec). "
              "Pass model:<key> and the queue picks the right graph.",
            "generate api kinds workflow graph export upscale",
            os.path.join("riley-studio", "engine", "graphs.py"))
    except Exception:
        pass

    try:
        from engine import models as m
        lines = []
        for k, meta in m.MODELS.items():
            size = sum(f["bytes"] for f in meta["files"])
            gated = any(f["gated"] for f in meta["files"])
            lines.append("- %s (%s): ~%.1f GB%s"
                         % (k, meta["tier"], size / 1e9,
                            ", license-gated pieces" if gated else ""))
        add("studio-suite", "Model tiers & pulls",
            "\n".join(lines) +
            "\nPull: POST /api/models/pull {key}. Gated pieces need a "
            "one-time license acceptance on huggingface.com. VRAM tier "
            "advice: GET /api/models.",
            "models sd15 sdxl flux ltx video vram pull download",
            os.path.join("riley-studio", "engine", "models.py"))
    except Exception:
        pass

    # ---- roadmap ----
    rm_rel = os.path.join("docs", "plans",
                          "riley-studio-studio-grade-roadmap.md")
    try:
        add("roadmap", "Studio-grade roadmap (all phases)",
            _read(REPO[0], rm_rel),
            "roadmap controlnet lora keyframes nvenc provenance "
            "director mode whisper piper",
            rm_rel)
    except OSError:
        pass

    # ---- fleet interop ----
    ports = {"ptah": 43903, "aphrodite": 43904, "daedalus": 43905,
             "riley-product": 43907, "persephone": 43909,
             "harmonia": 43908, "haven": 43910}
    add("fleet", "Loopback port map (siblings)",
        "\n".join("- %s: %d" % kv
                  for kv in sorted(ports.items(), key=lambda x: x[1]))
        + "\nAll services bind 127.0.0.1 only. The riley-studio engine "
          "API is 8288; ComfyUI is 8188.", "ports loopback siblings")

    add("fleet", "Venus teacher packet protocol",
        "Venus publishes JSON packets to %LOCALAPPDATA%/soul/knowledge "
        "(manifest.json lists packet name+sha256). Content policy: "
        "cultural and technical knowledge only - never media "
        "collections. Packets today: goth-corpus, facts, "
        "teachings-index.", "venus teach packets protocol")

    # ---- kernel architecture (shared by all three learners) ----
    add("kernels", "Kernel architecture: registries + heart",
        "Venus (Node, lib/kernel.js), Aphrodite and Riley (Python "
        "kernel.py ports) share one architecture: six registries "
        "(lifecycle, events, services, commands, tasks, jobs) plus the "
        "Heart - fixed-rate pulse, organs beat-phase aligned, "
        "quarantine after repeated failures with auto-revive, energy "
        "states awake/drowsy/asleep, alerters on critical-onset/"
        "persisting. Vitals surface on GET /api/kern. Stdlib only "
        "everywhere.", "kernel heart organs vitals architecture")

    # ---- house laws ----
    add("house-rules", "The loopback law",
        "Local-first: services bind 127.0.0.1 unless the operator "
        "explicitly overrides via env (KINEMA_ALLOW_REMOTE_HOST=1, "
        "RILEY_STUDIO_ALLOW_REMOTE=1). Nothing phones home after "
        "download. Big wheels/models never live on OneDrive-synced "
        "drives - homes are D:\\kinema-ai and D:\\riley-studio-ai.",
        "loopback privacy diskspace local first")

    add("house-rules", "Acceptable use (hard line)",
        "Creative tools run unfiltered models locally, on the "
        "operator: fictional/abstract work, licensed material, own "
        "performances. No face-swap or identity-clone tooling; never "
        "synthesize intimate or deceptive material of real, "
        "identifiable people.", "ethics acceptable-use policy")

    add("house-rules", "Gates discipline",
        "Every realm has an offline-safe verify gate whose exit code is "
        "the verdict. A red gate is fixed, never weakened. Suites "
        "register as HYPNOS build gates; CI runs safeguards/check.py "
        "--all --strict.", "verify gates ci hypnos testing")

    # ---- culture pointer (tiny index card, policy-safe) ----
    try:
        data = json.loads(_read(REPO[0], os.path.join(
            "assistant", "teachings", "goth-corpus.json")))
        topics = data.get("topics", {})
        if isinstance(topics, dict):
            tops = list(topics.keys())[:40]
        elif isinstance(topics, list):
            tops = [t.get("topic", "") if isinstance(t, dict)
                    else str(t) for t in topics][:40]
        else:
            tops = []
        add("culture", "Goth culture corpus (index)",
            "Topics covered: " + ", ".join(filter(None, map(str, tops))),
            "goth culture music fashion history")
    except (OSError, ValueError):
        pass

    # ---- operator-taught cards (haven/teach/*.md) ----
    # File format: first line "# Title", optional second line
    # "keywords: a, b, c", remainder is the body markdown. The domain
    # comes from the filename prefix: <domain>--<slug>.md
    teach_dir = os.path.join(HERE, "teach")
    if os.path.isdir(teach_dir):
        for fn in sorted(os.listdir(teach_dir)):
            if not fn.endswith(".md") or "--" not in fn:
                continue
            domain = fn[:-3].split("--", 1)[0].strip()
            rel = os.path.join("haven", "teach", fn)
            try:
                raw = _read(REPO[0], rel)
            except OSError:
                continue
            lines = raw.splitlines()
            title = fn[:-3].split("--", 1)[1].replace("-", " ").strip()
            kw = ""
            body_start = 0
            if lines and lines[0].startswith("# "):
                title = lines[0][2:].strip()
                body_start = 1
                if len(lines) > 1 and lines[1].lower().startswith(
                        "keywords:"):
                    kw = lines[1].split(":", 1)[1].strip()
                    body_start = 2
            if domain and title and body_start < len(lines):
                add(domain, title,
                    "\n".join(lines[body_start:]).strip(), kw, rel)

    # ---- full technological-expansion curriculum (haven/expansions.py) ----
    from expansions import EXPANSIONS
    for e in EXPANSIONS:
        add(e["domain"], e["title"], e["body_md"], e.get("keywords", ""),
            e.get("source"))

    return c


# ------------------------------------------------------------- storage

def upsert_cards(conn, cards):
    now = _now()
    fresh = 0
    for cd in cards:
        cur = conn.execute(
            "SELECT id, body_md FROM topics WHERE domain=? AND title=?",
            (cd["domain"], cd["title"]))
        row = cur.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO topics(domain,title,body_md,keywords,"
                "source_path,source_sha256,added_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (cd["domain"], cd["title"], cd["body"], cd["kw"],
                 cd["src"], cd["hash"], now))
            fresh += 1
        else:
            conn.execute(
                "UPDATE topics SET body_md=?, keywords=?, "
                "source_path=?, source_sha256=? WHERE id=?",
                (cd["body"], cd["kw"], cd["src"], cd["hash"], row[0]))
    return fresh


def ensure_tokens(conn, repo, rotate=False):
    """Keep every consumer authenticated; self-heal on drift.

    Law: the token FILE is the delivery truth. If a file exists and its
    hash matches the DB row -> keep both. Any other state (missing row,
    missing file, mismatch, or --rotate) mints a fresh token, updates
    the row and rewrites every candidate dir's file.
    """
    report = {}
    for name in CONSUMERS:
        row = conn.execute(
            "SELECT token_sha256 FROM consumers WHERE name=?",
            (name,)).fetchone()
        tok_file = _find_token(repo, name)
        current = None
        if tok_file:
            with open(tok_file, "rb") as fh:
                current = fh.read().strip().decode("ascii", "replace")
        if (not rotate and row and current
                and hashlib.sha256(current.encode()).hexdigest()
                == row[0]):
            report[name] = tok_file
            continue
        tok = secrets.token_hex(24)
        conn.execute(
            "INSERT INTO consumers(name,token_sha256,enabled,minted_at)"
            " VALUES(?,?,1,?) ON CONFLICT(name) DO UPDATE SET "
            "token_sha256=excluded.token_sha256, enabled=1, "
            "minted_at=excluded.minted_at",
            (name, hashlib.sha256(tok.encode()).hexdigest(), _now()))
        written = None
        for d in TOKEN_DIRS[name]:
            d_abs = d if os.path.isabs(d) else os.path.join(repo, d)
            try:
                os.makedirs(d_abs, exist_ok=True)
                p = os.path.join(d_abs, "haven.token")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(tok)
                written = p
            except OSError:
                continue
        report[name] = written
    return report


def _find_token(repo, name):
    for d in TOKEN_DIRS[name]:
        d_abs = d if os.path.isabs(d) else os.path.join(repo, d)
        p = os.path.join(d_abs, "haven.token")
        if os.path.isfile(p):
            return p
    return None


def _hash_file(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read().strip()).hexdigest()


def main(argv=None):
    global REPO
    ap = argparse.ArgumentParser(description="build HAVEN")
    ap.add_argument("--repo", default=os.path.dirname(HERE))
    ap.add_argument("--out", default=None)
    ap.add_argument("--rotate", action="store_true",
                    help="re-mint all consumer tokens")
    ap.add_argument("--no-provision", action="store_true",
                    help="skip token file writes (tests use temp dirs)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--add", nargs=2, metavar=("DOMAIN", "TITLE"),
                    help="append one operator-authored topic")
    ap.add_argument("--body-file")
    ap.add_argument("--keywords", default="")
    args = ap.parse_args(argv)
    REPO[0] = args.repo

    out = args.out or os.path.join(
        os.environ.get("LOCALAPPDATA",
                       os.path.join(os.path.expanduser("~"),
                                    "AppData", "Local")),
        "soul", "haven", "haven.db")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    conn = sqlite3.connect(out)
    conn.executescript(SCHEMA)

    if args.add:
        if not args.body_file:
            ap.error("--add requires --body-file")
        body = open(args.body_file, "r", encoding="utf-8").read()
        upsert_cards(conn, [card(args.add[0], args.add[1], body,
                                 args.keywords)])
        conn.commit()
        print("added: %s / %s" % tuple(args.add))
        return 0

    fresh = upsert_cards(conn, build_corpus())
    tokens = ({name: _find_token(args.repo, name)
               for name in CONSUMERS} if args.no_provision
              else ensure_tokens(conn, args.repo, rotate=args.rotate))
    conn.execute(
        "INSERT INTO meta(key,value) VALUES('consumers',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps(CONSUMERS),))
    conn.execute(
        "INSERT INTO meta(key,value) VALUES('rebuilt_at',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_now(),))
    conn.commit()

    n = conn.execute("SELECT count(*) FROM topics").fetchone()[0]
    domains = [r[0] for r in conn.execute(
        "SELECT DISTINCT domain FROM topics ORDER BY 1")]
    print("HAVEN built: %d topics (%d new/changed) across %s"
          % (n, fresh, ", ".join(domains)))
    print("db: %s" % out)
    ok = True
    if args.no_provision:
        # Provisioning intentionally skipped (tests use temp dbs):
        # token presence is informational here, never part of the verdict.
        for name, path in tokens.items():
            print("token[%s]: %s"
                  % (name, path or "not found (--no-provision)"))
    else:
        for name, path in tokens.items():
            print("token[%s]: %s" % (name, path or "PROVISION FAILED"))
            ok = ok and bool(path)
    if args.list:
        for dom, t in conn.execute(
                "SELECT domain,title FROM topics ORDER BY domain,title"):
            print("  [%s] %s" % (dom, t))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
