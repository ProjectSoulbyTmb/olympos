#!/usr/bin/env python3
"""server - HAVEN query service. Loopback-only, token-gated.

    python server.py [--port 43910] [--db PATH]

Bind is 127.0.0.1 by law; --host other than loopback refuses to start.
Every request must carry X-Haven-Token whose sha256 matches an enabled
consumer row (venus | aphrodite | riley). Anything else gets 403 and
never sees a single byte of curriculum.

Endpoints (all JSON {"ok":true,...}):
  GET /health            liveness + consumer names + topic count
  GET /topics            domain -> [titles]
  GET /search?q=...      FTS5 ranked matches (id, domain, title, snippet)
  GET /topic/<id>        full card
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def default_db():
    base = os.environ.get("LOCALAPPDATA", os.path.join(
        os.path.expanduser("~"), "AppData", "Local"))
    return os.path.join(base, "soul", "haven", "haven.db")


def make_handler(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    lock = __import__("threading").Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "HAVEN/1"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _json(self, code, payload=None, **extra):
            data = dict(payload or {})
            data.update(extra)
            body = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _consumer(self):
            tok = self.headers.get("X-Haven-Token", "")
            if not tok:
                return None
            h = hashlib.sha256(tok.strip().encode()).hexdigest()
            with lock:
                row = conn.execute(
                    "SELECT name FROM consumers WHERE token_sha256=? "
                    "AND enabled=1", (h,)).fetchone()
            return row[0] if row else None

        def do_GET(self):
            who = self._consumer()
            if who is None:
                return self._json(403, {"ok": False,
                                        "error": "haven: strangers "
                                                 "stay outside"})
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path.rstrip("/") or "/"
            q = urllib.parse.parse_qs(parsed.query)
            try:
                if route == "/health":
                    n = conn.execute(
                        "SELECT count(*) FROM topics").fetchone()[0]
                    consumers = [r[0] for r in conn.execute(
                        "SELECT name FROM consumers WHERE enabled=1 "
                        "ORDER BY name")]
                    return self._json(200, ok=True, service="HAVEN",
                                      topics=n, consumers=consumers,
                                      you=who)
                if route == "/topics":
                    out = {}
                    for dom, title in conn.execute(
                            "SELECT domain,title FROM topics "
                            "ORDER BY domain,title"):
                        out.setdefault(dom, []).append(title)
                    return self._json(200, ok=True, domains=out,
                                      you=who)
                if route == "/search":
                    term = (q.get("q") or [""])[0].strip()
                    if not term:
                        return self._json(400, {
                            "ok": False, "error": "q required"})
                    rows = conn.execute(
                        "SELECT t.id, t.domain, t.title, "
                        "snippet(topics_fts, 1, '>>', '<<', '…', 24) "
                        "FROM topics_fts f JOIN topics t ON t.id=f.rowid "
                        "WHERE topics_fts MATCH ? "
                        "ORDER BY bm25(topics_fts) LIMIT 12",
                        (term,)).fetchall()
                    return self._json(200, ok=True, hits=[
                        {"id": r[0], "domain": r[1], "title": r[2],
                         "snippet": r[3]} for r in rows], you=who)
                m = route.startswith("/topic/")
                if m:
                    tid = int(route.split("/")[-1])
                    row = conn.execute(
                        "SELECT id,domain,title,body_md,keywords,"
                        "source_path,source_sha256,added_at FROM topics "
                        "WHERE id=?", (tid,)).fetchone()
                    if not row:
                        return self._json(404, {"ok": False,
                                                "error": "no such topic"})
                    return self._json(200, ok=True, you=who, topic={
                        "id": row[0], "domain": row[1], "title": row[2],
                        "body_md": row[3], "keywords": row[4],
                        "source_path": row[5], "source_sha256": row[6],
                        "added_at": row[7]})
                return self._json(404, {"ok": False,
                                        "error": "not found"})
            except sqlite3.OperationalError as exc:
                return self._json(400, {"ok": False,
                                        "error": str(exc)})

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="HAVEN service")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=43910)
    ap.add_argument("--db", default=default_db())
    args = ap.parse_args(argv)

    host = args.host.lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("HAVEN binds loopback only - refusing %r"
                         % args.host)
    if not os.path.isfile(args.db):
        raise SystemExit("no HAVEN db at %s - run build_haven_db.py"
                         % args.db)

    httpd = ThreadingHTTPServer((args.host, args.port),
                                make_handler(args.db))
    print("HAVEN on http://%s:%s (db=%s)"
          % (args.host, httpd.server_address[1], args.db), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
