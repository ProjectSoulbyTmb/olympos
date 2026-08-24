"""Knowledge organ verify gate - corpus, index, and retrieval health.

Run: python knowledge/verify_knowledge.py   (exit 0 = all checks pass)
"""

import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MIN_LIBRARY_DOCS = 10
MIN_CORPUS_DOCS = 30
MIN_DB_ENTRIES = 10


def _load_engine():
    spec = importlib.util.spec_from_file_location(
        "knowledge_engine", os.path.join(HERE, "engine.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_corpus_present():
    lib = os.path.join(HERE, "library")
    docs = [f for f in os.listdir(lib) if f.endswith(".md")]
    if len(docs) < MIN_LIBRARY_DOCS:
        return f"library thin: {len(docs)} docs < {MIN_LIBRARY_DOCS}"
    for fname in docs:
        path = os.path.join(lib, fname)
        with open(path, "r", encoding="utf-8") as fh:
            head = fh.read(400)
        if not head.lstrip().startswith("#"):
            return f"{fname} missing title heading"
    return True


def check_index_builds_deterministic():
    eng = _load_engine()
    a = eng.build_index()
    b = eng.build_index()
    if len(a["docs"]) < MIN_CORPUS_DOCS:
        return f"corpus small: {len(a['docs'])}"
    if sorted(d["id"] for d in a["docs"]) != \
            sorted(d["id"] for d in b["docs"]):
        return "nondeterministic doc set"
    if set(a["postings"]) != set(b["postings"]):
        return "nondeterministic terms"
    if not a["postings"]:
        return "empty postings"
    return True


def check_known_queries_hit():
    eng = _load_engine()
    cases = [
        ("worktree branch writer", "git-multi-writer"),
        ("mcp stdio handshake tools", "mcp-protocol"),
        ("fallback transient rate limit", "llm-integration"),
        ("denied confirmation destructive", "security-grants"),
        ("remediated retry battery", "testing-doctrine"),
    ]
    for query, expect in cases:
        hits = eng.search(query, top=5)
        docs = [h["doc"] for h in hits]
        if not any(expect in d for d in docs):
            return (f"query {query!r} missed {expect}; got {docs[:3]}")
    return True


def check_snippets_and_limits():
    eng = _load_engine()
    hits = eng.search("secret redaction environment", top=2)
    if len(hits) > 2:
        return "top limit ignored"
    for hit in hits:
        snippet = hit.get("snippet", "")
        if any(ch in snippet for ch in "{}\n"):
            return f"structural junk leaked into snippet: {snippet!r}"
    empty = eng.search("zzzqqqxyzzy_no_such_term", top=3)
    if empty:
        return "garbage query returned hits"
    return True


def check_cli_exit_codes():
    import subprocess
    engine = os.path.join(HERE, "engine.py")
    for args, want in ((["stats"], 0), (["search", "zeus"], 0),
                       (["search", ""], 2)):
        proc = subprocess.run([sys.executable, engine] + args,
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != want:
            return (f"cli {args} exit={proc.returncode}, "
                    f"want {want}")
    return True


def _product_dbs():
    eng = _load_engine()
    return eng.discover_dbs()


def check_product_db_shapes():
    """Every discovered product DB must stay machine-trustable: schema,
    unique monotonic ids, real source links, titled prose files."""
    dbs = _product_dbs()
    if not dbs:
        return ("no product DBs found - expected knowledge/<name>/"
                "<name>.json with an 'entries' list")
    for spec in dbs:
        db_dir = os.path.join(HERE, spec["dir"])
        db_path = os.path.join(db_dir, spec["file"])
        try:
            with open(db_path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except ValueError as exc:
            return f"{spec['dir']}: invalid JSON: {exc}"
        entries = data.get("entries")
        if not isinstance(entries, list) or not entries:
            return f"{spec['dir']}: entries missing or empty"
        if len(entries) < MIN_DB_ENTRIES:
            return (f"{spec['dir']}: thin db {len(entries)} "
                    f"< {MIN_DB_ENTRIES}")
        required = ("id", "title", "category", "summary", "details",
                    "sources", "tags")
        prefix = spec["prefix"].upper()
        id_re = re.compile(r"^%s-\d{3,}$" % re.escape(prefix))
        seen = set()
        last_num = 0
        for entry in entries:
            missing = [k for k in required if not entry.get(k)]
            if missing:
                return (f"{spec['dir']}:{entry.get('id', '?')} "
                        f"missing {missing}")
            eid = entry["id"]
            if not isinstance(eid, str) or not id_re.match(eid):
                return (f"{spec['dir']}: bad id shape {eid!r} "
                        f"(want {prefix}-###)")
            num = int(eid.split("-")[1])
            if eid in seen:
                return f"{spec['dir']}: duplicate id {eid}"
            if num <= last_num:
                return (f"{spec['dir']}: ids must grow monotonically: "
                        f"{eid} after {prefix}-{last_num:03d}")
            seen.add(eid)
            last_num = num
            bad = [s for s in entry["sources"]
                   if not isinstance(s, str)
                   or not s.startswith("https://")]
            if bad:
                return f"{spec['dir']}:{eid} non-https sources: {bad[:2]}"
            if not all(isinstance(t, str) and t for t in entry["tags"]):
                return f"{spec['dir']}:{eid} malformed tags"
        for fname in sorted(os.listdir(db_dir)):
            if not fname.endswith(".md"):
                continue
            with open(os.path.join(db_dir, fname), "r",
                      encoding="utf-8") as fh:
                head = fh.read(400)
            if not head.lstrip().startswith("#"):
                return (f"{spec['dir']}/{fname} missing title heading")
    return True


def _entry_query(entry):
    """Deterministic probe query built from an entry's own words."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9]+",
                                   entry.get("title", ""))
             if len(w) > 3][:4]
    for tag in entry.get("tags", []):
        if len(tag) > 3 and tag.lower() not in {w.lower() for w in words}:
            words.append(tag)
        if len(words) >= 5:
            break
    return " ".join(words)


def check_product_db_retrievable():
    """The engine must surface every discovered DB: entry probes built
    from entry text, plus at least one prose doc hit per DB."""
    eng = _load_engine()
    dbs = _product_dbs()
    indexed_ids = {d["id"] for d in eng.build_index()["docs"]}
    for spec in dbs:
        prefix = spec["prefix"]
        db_path = os.path.join(HERE, spec["dir"], spec["file"])
        with open(db_path, "r", encoding="utf-8-sig") as fh:
            entries = json.load(fh)["entries"]
        for probe in (entries[0], entries[-1]):
            query = _entry_query(probe)
            hits = eng.search(query, top=8)
            docs = [h["doc"] for h in hits]
            if f"{prefix}:{probe['id']}" not in docs:
                return (f"{spec['dir']}:{probe['id']} not retrievable "
                        f"via {query!r}; got {docs[:3]}")
        doc_ids = [i for i in indexed_ids
                   if i.startswith(prefix + "-doc:")]
        if not doc_ids:
            return f"{spec['dir']}: prose topic files not indexed"
        sample = sorted(doc_ids)[0]
        stem = sample.split(":", 1)[1]
        with open(os.path.join(HERE, spec["dir"], stem), "r",
                  encoding="utf-8") as fh:
            head = fh.read(400).lstrip().lstrip("#").strip()
        q = _entry_query({"title": head, "tags": []})
        if q and not any(h["doc"].startswith(prefix + "-doc:")
                         for h in eng.search(q, top=8)):
            return (f"{spec['dir']}: prose probe {q!r} surfaced no "
                    f"{prefix}-doc:* hits")
    # concrete regression anchors (webstudio incident corpus)
    for query, expect in (
            ("webstudio mcp checkpoint mutation gate", "ws:WS-009"),
            ("builder share link credential secret", "ws:WS-004")):
        hits = eng.search(query, top=6)
        if not any(d.startswith(expect) for d in
                   (h["doc"] for h in hits)):
            return (f"query {query!r} missed {expect}")
    return True


CHECKS = [
    ("library corpus present with titles", check_corpus_present),
    ("index builds deterministic", check_index_builds_deterministic),
    ("known queries hit expected docs", check_known_queries_hit),
    ("snippets clean + limits honored", check_snippets_and_limits),
    ("cli exit codes", check_cli_exit_codes),
    ("product dbs schema + monotonic ids", check_product_db_shapes),
    ("product dbs retrievable via engine", check_product_db_retrievable),
]


def main():
    passed = 0
    failures = []
    for name, fn in CHECKS:
        try:
            result = fn()
        except Exception as exc:      # noqa: BLE001 - gates report
            result = f"raised {type(exc).__name__}: {exc}"
        if result is True:
            passed += 1
            print("[ok]   %s" % name)
        else:
            failures.append(name)
            print("[FAIL] %s -> %s" % (name, result))
    total = len(CHECKS)
    print("\n%d/%d checks passed" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
