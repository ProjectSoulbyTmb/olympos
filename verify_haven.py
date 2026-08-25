#!/usr/bin/env python3
"""verify_haven - offline-safe gate for the HAVEN shared knowledge base.

    python verify_haven.py

Checks: cumulative builds, exactly three consumers with provisioned
tokens, loopback-bind refusal, token enforcement (strangers get 403),
FTS search quality, source-drift detection. Exit code = verdict.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HAVEN = os.path.join(HERE, "haven")
sys.path.insert(0, HAVEN)

PASS, FAIL = [], []


def check(name):
    def wrap(fn):
        def run():
            try:
                fn()
                PASS.append(name)
                print("  ok   %s" % name)
            except Exception as exc:  # noqa: BLE001
                FAIL.append((name, str(exc)))
                print("  FAIL %s: %s" % (name, exc))
        run.__name__ = fn.__name__
        CHECKS.append(run)
        return run
    return wrap


CHECKS = []


@check("cumulative build upserts without losing tokens or topics")
def check_cumulative_build():
    import sqlite3
    import build_haven_db as b
    tmp = tempfile.mkdtemp(prefix="haven-")
    db = os.path.join(tmp, "haven.db")
    try:
        assert b.main(["--repo", HERE, "--out", db]) == 0
        conn = sqlite3.connect(db)
        n1 = conn.execute("SELECT count(*) FROM topics").fetchone()[0]
        tok1 = conn.execute(
            "SELECT token_sha256 FROM consumers WHERE name='venus'")\
            .fetchone()[0]
        assert n1 >= 8, "curriculum suspiciously thin: %d" % n1
        # rebuild: same tokens, no dupes
        assert b.main(["--repo", HERE, "--out", db]) == 0
        conn2 = sqlite3.connect(db)
        n2 = conn2.execute("SELECT count(*) FROM topics").fetchone()[0]
        tok2 = conn2.execute(
            "SELECT token_sha256 FROM consumers WHERE name='venus'")\
            .fetchone()[0]
        assert n1 == n2, "rebuild duplicated topics (%d -> %d)" % (n1, n2)
        assert tok1 == tok2, "rebuild rotated tokens without --rotate"
        # operator addition lands and survives another rebuild
        note = os.path.join(tmp, "note.md")
        with open(note, "w", encoding="utf-8") as fh:
            fh.write("future additions live here")
        assert b.main(["--repo", HERE, "--out", db,
                       "--add", "studio-suite", "Future feature probe",
                       "--body-file", note,
                       "--keywords", "probe"]) == 0
        assert b.main(["--repo", HERE, "--out", db]) == 0
        conn3 = sqlite3.connect(db)
        still = conn3.execute(
            "SELECT count(*) FROM topics WHERE title="
            "'Future feature probe'").fetchone()[0]
        assert still == 1, "operator addition lost on rebuild"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check("exactly three consumers, all tokens provisioned on disk")
def check_consumers_provisioned():
    import sqlite3
    import build_haven_db as b
    tmp = tempfile.mkdtemp(prefix="haven-cons-")
    db = os.path.join(tmp, "haven.db")
    try:
        b.main(["--repo", HERE, "--out", db])
        conn = sqlite3.connect(db)
        names = [r[0] for r in conn.execute(
            "SELECT name FROM consumers ORDER BY name")]
        assert names == ["aphrodite", "riley", "venus"], names
        for name in b.CONSUMERS:
            p = b._find_token(HERE, name)
            assert p, "%s has no token file" % name
            h = hashlib.sha256(
                open(p, "rb").read().strip()).hexdigest()
            row = conn.execute(
                "SELECT enabled FROM consumers WHERE token_sha256=?",
                (h,)).fetchone()
            assert row and row[0] == 1, "%s token not enabled" % name
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check("server enforces tokens + answers learners; refuses wide bind")
def check_server_enforcement():
    import build_haven_db as b
    tmp = tempfile.mkdtemp(prefix="haven-srv-")
    db = os.path.join(tmp, "haven.db")
    try:
        b.main(["--repo", HERE, "--out", db])
        venus_tok = open(b._find_token(HERE, "venus"), "rb").read()\
            .strip().decode()
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, os.path.join(HAVEN, "server.py"),
             "--port", str(port), "--db", db],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            base = "http://127.0.0.1:%d" % port
            _wait_ready(base + "/health", auth=venus_tok)
            # stranger rejected
            code, body = _get(base + "/search?q=studio", auth="wrong")
            assert code == 403, (code, body)
            code, body = _get(base + "/topics")
            assert code == 403, "missing token accepted"
            # learner welcomed
            code, body = _get(base + "/health", auth=venus_tok)
            assert body["ok"] and body["you"] == "venus"
            assert set(body["consumers"]) == \
                {"venus", "aphrodite", "riley"}
            code, body = _get(base + "/search?q=controlnet+roadmap",
                              auth=venus_tok)
            assert body["ok"] and len(body["hits"]) >= 1, body
            tid = body["hits"][0]["id"]
            code, body = _get(base + "/topic/%d" % tid, auth=venus_tok)
            assert body["ok"] and len(body["topic"]["body_md"]) > 50
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        # wide bind refused at startup
        r = subprocess.run(
            [sys.executable, os.path.join(HAVEN, "server.py"),
             "--host", "0.0.0.0", "--port", str(_free_port()),
             "--db", db], capture_output=True, text=True, timeout=30)
        assert r.returncode != 0 and "loopback" in (
            r.stderr + r.stdout).lower(), "wide bind was allowed"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check("source drift is detectable via stored hashes")
def check_source_drift():
    import build_haven_db as b
    tmp_repo = tempfile.mkdtemp(prefix="haven-src-")
    try:
        # minimal fake repo: one source doc the corpus reads
        docs = os.path.join(tmp_repo, "docs", "plans")
        os.makedirs(docs)
        src = os.path.join(docs, "note.md")
        open(src, "w", encoding="utf-8").write("v1 truth")
        card = b.card("t", "drift probe", "body", "kw",
                      os.path.relpath(src, tmp_repo), repo=tmp_repo)
        assert card["hash"] == hashlib.sha256(
            b"v1 truth").hexdigest()
        open(src, "w", encoding="utf-8").write("v2 drifted")
        card2 = b.card("t", "drift probe", "body", "kw",
                       os.path.relpath(src, tmp_repo), repo=tmp_repo)
        assert card2["hash"] != card["hash"], \
            "identical hash across changed source - drift undetectable"
    finally:
        shutil.rmtree(tmp_repo, ignore_errors=True)


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait_ready(url, auth=None, timeout=20):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url)
            if auth:
                req.add_header("X-Haven-Token", auth)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return
        except urllib.error.HTTPError as exc:
            last = exc
        except OSError as exc:
            last = exc
        time.sleep(0.25)
    raise AssertionError("server never ready: %s" % last)


def _get(url, auth=None):
    req = urllib.request.Request(url)
    if auth:
        req.add_header("X-Haven-Token", auth)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


if __name__ == "__main__":
    print("== verify_haven ==")
    print("-- %d checks --" % len(CHECKS))
    for fn in CHECKS:
        fn()
    print("== %d pass / %d fail ==" % (len(PASS), len(FAIL)))
    if FAIL:
        for name, why in FAIL:
            print("   FAILED: %s - %s" % (name, why[:300]))
        sys.exit(1)
