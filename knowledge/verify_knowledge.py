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
WEBSTUDIO_DIR = os.path.join(HERE, "webstudio")
WEBSTUDIO_DB = os.path.join(WEBSTUDIO_DIR, "webstudio.json")
MIN_WEBSTUDIO_ENTRIES = 20
_ID_RE = re.compile(r"^WS-\d{3,}$")


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


def check_webstudio_db_shape():
    """External-product DBs must stay machine-trustable: schema, unique
    monotonic ids, real source links."""
    if not os.path.isfile(WEBSTUDIO_DB):
        return "webstudio/webstudio.json missing"
    try:
        with open(WEBSTUDIO_DB, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        return f"invalid JSON: {exc}"
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return "entries missing or empty"
    if len(entries) < MIN_WEBSTUDIO_ENTRIES:
        return (f"thin db: {len(entries)} < {MIN_WEBSTUDIO_ENTRIES}")
    required = ("id", "title", "category", "summary", "details",
                "sources", "tags")
    seen = set()
    last_num = 0
    for entry in entries:
        missing = [k for k in required if not entry.get(k)]
        if missing:
            return f"{entry.get('id', '?')} missing {missing}"
        eid = entry["id"]
        if not _ID_RE.match(eid):
            return f"bad id shape: {eid!r} (want WS-###)"
        num = int(eid.split("-")[1])
        if eid in seen:
            return f"duplicate id: {eid}"
        if num <= last_num:
            return (f"ids must grow monotonically: "
                    f"{eid} after WS-{last_num:03d}")
        seen.add(eid)
        last_num = num
        bad = [s for s in entry["sources"]
               if not isinstance(s, str) or not s.startswith("https://")]
        if bad:
            return f"{eid} non-https sources: {bad[:2]}"
        if not all(isinstance(t, str) and t for t in entry["tags"]):
            return f"{eid} malformed tags"
    for doc in sorted(os.listdir(WEBSTUDIO_DIR)):
        if doc.endswith(".md"):
            with open(os.path.join(WEBSTUDIO_DIR, doc), "r",
                      encoding="utf-8") as fh:
                head = fh.read(400)
            if not head.lstrip().startswith("#"):
                return f"webstudio/{doc} missing title heading"
    return True


def check_webstudio_retrievable():
    """The engine must surface webstudio entries for agent queries."""
    eng = _load_engine()
    cases = [
        ("webstudio mcp checkpoint mutation gate", "ws:WS-009"),
        ("builder share link credential secret", "ws:WS-004"),
        ("static export limitations remix", "ws:WS-021"),
    ]
    for query, expect in cases:
        hits = eng.search(query, top=6)
        docs = [h["doc"] for h in hits]
        if not any(d.startswith(expect) for d in docs):
            return (f"query {query!r} missed {expect}; got {docs[:3]}")
    stats_cases = [
        ("vision verification screenshots preview", "ws-doc:playbooks.md"),
        ("self-host export static remix docker",
         "ws-doc:publishing-hosting.md"),
    ]
    for query, expect in stats_cases:
        hits = eng.search(query, top=5)
        docs = [h["doc"] for h in hits]
        if not any(d.startswith(expect) for d in docs):
            return (f"prose query {query!r} missed {expect}; "
                    f"got {docs[:3]}")
    return True


CHECKS = [
    ("library corpus present with titles", check_corpus_present),
    ("index builds deterministic", check_index_builds_deterministic),
    ("known queries hit expected docs", check_known_queries_hit),
    ("snippets clean + limits honored", check_snippets_and_limits),
    ("cli exit codes", check_cli_exit_codes),
    ("webstudio db schema + monotonic ids", check_webstudio_db_shape),
    ("webstudio corpus retrievable", check_webstudio_retrievable),
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
