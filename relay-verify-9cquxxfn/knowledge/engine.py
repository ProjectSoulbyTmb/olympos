"""Knowledge engine - inverted-index search over the fleet's corpus.

Pure standard library. Indexes every markdown document under
knowledge/ (including this library/) plus rendered entries from
knowledge/lessons.json and product databases discovered by
convention (webstudio/ today, more tomorrow), then answers TF-IDF
ranked queries with sentence snippets. The index self-invalidates on
corpus changes, so agents never serve stale results.

CLI:
    python knowledge/engine.py rebuild
    python knowledge/engine.py stats
    python knowledge/engine.py dbs
    python knowledge/engine.py search "worktree protocol" --top 3

Library API:
    from knowledge.engine import search          # auto-builds/caches
    hits = search("confirmation gate re-arm", top=3)
"""

import hashlib
import json
import math
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(HERE, "library")
LESSONS_PATH = os.path.join(HERE, "lessons.json")

# Product databases self-register by convention: any subdirectory
# knowledge/<product>/ containing <product>.json with a non-empty
# top-level "entries" list is indexed automatically - markdown topic
# files alongside it too. Dropping the directory is the whole act of
# onboarding; no code change, no spec edit, no manual rebuild.
_DB_SKIP_DIRS = {"library", "proposals", "__pycache__"}
_INDEX_PATH = os.path.join(HERE, ".index.json")

# Bump whenever indexing BEHAVIOR changes (parsing, fields, prefixes):
# folds into the corpus signature so caches built by older code are
# always invalidated - a signature alone cannot vouch for content.
_ENGINE_VERSION = "2"

_SNIPPET_DF = {}
_SNIPPET_N = 1

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "these", "those", "as", "at", "by", "from", "into", "if", "then",
    "than", "so", "do", "does", "did", "not", "no", "but", "can", "will",
    "would", "should", "may", "might", "must", "have", "has", "had",
    "you", "your", "we", "our", "they", "their", "them", "he", "she",
    "his", "her", "i", "me", "my", "when", "where", "which", "who",
    "what", "why", "how", "all", "any", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "only", "own", "same",
    "too", "very", "just", "also", "one", "two", "per", "via", "use",
}


def _tokens(text):
    return [t for t in _TOKEN_RE.findall(text.lower())
            if t not in _STOPWORDS]


def discover_dbs():
    """Find every convention-conforming product DB under knowledge/.

    Returns deterministic [{"dir", "file", "prefix"}] specs. A DB must
    be a subdirectory holding <dirname>.json whose parsed form is an
    object with a non-empty "entries" list. Doc-id prefix defaults to
    the directory name and may be overridden by a top-level "prefix"
    field (e.g. "ws" for webstudio) - useful for compact ids like
    WS-001. Anything malformed is skipped silently here -
    verify_knowledge.py reports shape problems as gate failures so
    authors see them.
    """
    dbs = []
    try:
        names = sorted(os.listdir(HERE))
    except OSError:
        return dbs
    for name in names:
        if name in _DB_SKIP_DIRS or name.startswith("."):
            continue
        path = os.path.join(HERE, name)
        if not os.path.isdir(path):
            continue
        db_file = name + ".json"
        db_path = os.path.join(path, db_file)
        if not os.path.isfile(db_path):
            continue
        try:
            with open(db_path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("entries"), list) \
                and data["entries"]:
            prefix = str(data.get("prefix") or "").strip().lower()
            if not prefix:
                prefix = re.sub(r"[^a-z0-9]+", "-",
                                name.lower()).strip("-")
            if prefix and re.match(r"^[a-z][a-z0-9-]*$", prefix):
                dbs.append({"dir": name, "file": db_file,
                            "list_key": "entries", "prefix": prefix})
    return dbs


def _docs():
    """Yield {id,title,body} for every corpus document."""
    for fname in sorted(os.listdir(LIBRARY_DIR)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(LIBRARY_DIR, fname)
        with open(path, "r", encoding="utf-8") as fh:
            body = fh.read()
        title = fname[:-3]
        first = body.splitlines()[0].lstrip("# ").strip() if body else ""
        if first:
            title = first
        yield {"id": "lib:" + fname, "title": title,
               "body": body, "path": path}
    if os.path.isfile(LESSONS_PATH):
        try:
            with open(LESSONS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for lesson in data.get("lessons", []):
                body = (f"{lesson.get('title', '')}\n"
                        f"category: {lesson.get('category', '')}\n"
                        f"{lesson.get('lesson', '')}\n"
                        f"tags: {' '.join(lesson.get('tags', []))}")
                yield {"id": "lesson:" + lesson.get("id", "?"),
                       "title": lesson.get("title", lesson.get("id", "?")),
                       "body": body,
                       "path": LESSONS_PATH}
        except (OSError, ValueError):
            pass
    for spec in discover_dbs():
        db_dir = os.path.join(HERE, spec["dir"])
        # prose topic files, same treatment as library docs
        for fname in sorted(os.listdir(db_dir)):
            if not fname.endswith(".md"):
                continue
            path = os.path.join(db_dir, fname)
            with open(path, "r", encoding="utf-8") as fh:
                body = fh.read()
            title = fname[:-3]
            first = body.splitlines()[0].lstrip("# ").strip() \
                if body else ""
            if first:
                title = first
            yield {"id": spec["prefix"] + "-doc:" + fname,
                   "title": title, "body": body, "path": path}
        # machine-readable entries rendered into searchable documents
        db_path = os.path.join(db_dir, spec["file"])
        try:
            with open(db_path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for entry in data.get(spec["list_key"], []):
            eid = str(entry.get("id", "?"))
            tags = entry.get("tags", [])
            sources = entry.get("sources", [])
            body = (f"{entry.get('title', '')}\n"
                    f"category: {entry.get('category', '')}\n"
                    f"{entry.get('summary', '')}\n"
                    f"{entry.get('details', '')}\n"
                    f"tags: {' '.join(tags)}\n"
                    f"sources: {' '.join(sources)}")
            yield {"id": f"{spec['prefix']}:{eid}",
                   "title": entry.get("title", eid),
                   "body": body,
                   "path": db_path}


def _corpus_signature():
    """Stable fingerprint of every md/json file feeding the corpus.

    Excludes the index itself. Any add/edit/delete flips the hash, and
    _load_or_build rebuilds instead of serving stale results - this is
    what makes new product DBs wire themselves in with no manual
    `rebuild` step.
    """
    parts = []
    for dirpath, dirnames, filenames in os.walk(HERE):
        dirnames[:] = sorted(d for d in dirnames
                             if d != "__pycache__" and not d.startswith("."))
        for fname in sorted(filenames):
            if not fname.endswith((".md", ".json")):
                continue
            path = os.path.join(dirpath, fname)
            if os.path.abspath(path) == os.path.abspath(_INDEX_PATH):
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            parts.append("%s|%d|%d" % (os.path.relpath(path, HERE),
                                       st.st_mtime_ns, st.st_size))
    return hashlib.sha1(
        (_ENGINE_VERSION + "\n" + "\n".join(parts)).encode("utf-8")
    ).hexdigest()


def build_index():
    postings = {}
    doclen = {}
    docs = []
    for doc in _docs():
        did = doc["id"]
        docs.append({"id": did, "title": doc["title"],
                     "path": os.path.relpath(doc["path"], HERE),
                     "body": doc["body"]})
        title_tokens = _tokens(doc["title"])
        tokens = title_tokens * 3 + _tokens(doc["body"])
        doclen[did] = len(tokens)
        counts = {}
        for tok in tokens:
            counts[tok] = counts.get(tok, 0) + 1
        for term, tf in counts.items():
            postings.setdefault(term, {})[did] = tf
    return {"docs": docs, "postings": postings, "doclen": doclen,
            "signature": _corpus_signature()}


def _load_or_build(rebuild=False):
    if not rebuild and os.path.isfile(_INDEX_PATH):
        try:
            with open(_INDEX_PATH, "r", encoding="utf-8") as fh:
                index = json.load(fh)
            if index.get("signature") == _corpus_signature():
                return index
        except (OSError, ValueError):
            pass
    index = build_index()
    try:
        with open(_INDEX_PATH, "w", encoding="utf-8") as fh:
            json.dump(index, fh)
    except OSError:
        pass
    return index


def search(query, top=5, rebuild=False, index=None):
    """TF-IDF ranked search. Returns list of hit dicts with snippets."""
    if index is None:
        index = _load_or_build(rebuild=rebuild)
    q_tokens = [t for t in _tokens(query) if t in index["postings"]]
    if not q_tokens:
        return []
    global _SNIPPET_DF, _SNIPPET_N
    n_docs = max(1, len(index["docs"]))
    _SNIPPET_DF = {t: len(index["postings"][t]) for t in q_tokens}
    _SNIPPET_N = n_docs
    scores = {}
    for term in q_tokens:
        idf = math.log(n_docs / len(index["postings"][term]))
        for did, tf in index["postings"][term].items():
            length = index["doclen"].get(did) or 1
            scores[did] = scores.get(did, 0.0) + (tf / length) * idf
    titles = {d["id"]: d for d in index["docs"]}
    hits = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    out = []
    for did, score in hits:
        meta = titles.get(did, {})
        out.append({"doc": did, "title": meta.get("title", did),
                    "score": round(score, 4),
                    "snippet": _snippet(meta.get("path", ""), q_tokens,
                                        body=meta.get("body", ""))})
    return out


def _snippet(path, terms, width=240, body=""):
    if body:
        text = body
    else:
        if path and not os.path.isabs(path):
            path = os.path.join(HERE, path)
        try:
            with open(path, "r", encoding="utf-8",
                      errors="replace") as fh:
                text = fh.read()
        except OSError:
            return ""
    # rank lines by rarity-weighted matches; rarity ~ inverse posting size
    def line_score(line):
        lt = set(_tokens(line))
        score = 0
        for t in terms:
            if t not in lt:
                continue
            df = max(1, _SNIPPET_DF.get(t, 1))
            score += math.log((_SNIPPET_N + 1) / df)
        return score
    best_line, best_score = "", float("-inf")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(
                ("{", "}", '"', "[", "]", "tags:", "- ", "|")):
            continue
        s = line_score(stripped)
        if s > best_score:
            best_line, best_score = stripped, s
    if best_score is None or best_score <= 0:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(("{", "}", '"')):
                best_line = stripped
                break
    if not best_line:
        return ""
    clean = re.sub(r"^#+\s*", "", best_line)[:width]
    return clean.encode("ascii", "replace").decode("ascii") + (
        "..." if len(best_line) > width else "")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="knowledge engine")
    ap.add_argument("command", choices=["rebuild", "stats", "dbs",
                                        "search"])
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    opts = ap.parse_args(argv)

    started = time.time()
    if opts.command == "rebuild":
        index = build_index()
        with open(_INDEX_PATH, "w", encoding="utf-8") as fh:
            json.dump(index, fh)
        print(f"indexed {len(index['docs'])} docs, "
              f"{len(index['postings'])} terms "
              f"in {time.time() - started:.2f}s")
        return 0
    if opts.command == "dbs":
        for spec in discover_dbs():
            print(f"{spec['dir']} (prefix {spec['prefix']}:)")
        return 0
    if opts.command == "stats":
        index = _load_or_build()
        print(f"{len(index['docs'])} docs, "
              f"{len(index['postings'])} terms")
        return 0
    if not opts.query:
        print("search requires a query")
        return 2
    hits = search(opts.query, top=opts.top)
    if opts.json:
        print(json.dumps(hits, indent=2))
    elif not hits:
        print("(no matches)")
    else:
        for hit in hits:
            print(f"[{hit['score']:6.3f}] {hit['title']}"
                  f"\n         {hit['snippet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
