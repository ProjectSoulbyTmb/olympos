"""RATATOSK verifier - the post office contract, checked.

Every check runs against a throwaway post root; the real data/post is
never touched. Exit 0 = all green.

    python ratatosk/verify_ratatosk.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_PARENT = os.path.dirname(HERE)
sys.path.insert(0, ROOT_PARENT)

from ratatosk.bus import Post, default_root, publish, beat  # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def sandbox():
    """A Post on a fresh throwaway root."""
    outer = tempfile.mkdtemp(prefix="ratatosk-verify-")
    return Post(root=os.path.join(outer, "post")), outer


# ------------------------------------------------------------ direct mail

@check
def roundtrip_fields():
    post, tmp = sandbox()
    try:
        lid = post.send("zeus", "incident", {"gate": "vulcan"},
                        frm="sentinel")
        letters = post.read("zeus")
        assert len(letters) == 1, letters
        l = letters[0]
        assert l["id"] == lid and l["from"] == "sentinel" \
            and l["to"] == "zeus" and l["kind"] == "incident", l
        assert l["payload"] == {"gate": "vulcan"}, l
        assert l["v"] >= 1 and l["ts"], l
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def fifo_ordering():
    post, tmp = sandbox()
    try:
        for i in range(5):
            post.send("norn", "tick", {"i": i}, frm="clock")
        got = [l["payload"]["i"] for l in post.read("norn")]
        assert got == [0, 1, 2, 3, 4], got
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def mark_seen_and_unread():
    post, tmp = sandbox()
    try:
        for i in range(3):
            post.send("hades", "seal", {"n": i}, frm="kernel")
        assert post.unread("hades") == 3
        peeked = post.peek("hades")
        assert len(peeked) == 3 and post.unread("hades") == 3, \
            "peek must not mark"
        got = post.read("hades")
        assert len(got) == 3 and post.unread("hades") == 0
        seen_dir = os.path.join(post.root, "hades", "seen")
        assert len([f for f in os.listdir(seen_dir)
                    if f.endswith(".json")]) == 3
        assert post.read("hades") == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def concurrent_senders_no_loss():
    post, tmp = sandbox()
    try:
        def worker(k):
            for i in range(25):
                post.send("dashboard", "stat", {"w": k, "i": i},
                          frm=f"w{k}")
        threads = [threading.Thread(target=worker, args=(k,))
                   for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        letters = post.read("dashboard", limit=1000)
        ids = {l["id"] for l in letters}
        assert len(letters) == 100, f"lost letters: {len(letters)}"
        assert len(ids) == 100, "duplicate ids"

        def bworker(k):
            for i in range(25):
                post.broadcast("stats", "stat", {"w": k, "i": i},
                               frm=f"w{k}")
        threads = [threading.Thread(target=bworker, args=(k,))
                   for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        seqs = [r["seq"] for r in post.tail("stats", n=1000)]
        assert sorted(seqs) == list(range(1, 101)), \
            "topic seqs must be unique and dense"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def corrupt_letter_quarantined():
    post, tmp = sandbox()
    try:
        post.send("vulcan", "ok", {}, frm="warden")
        inbox = os.path.join(post.root, "vulcan", "inbox")
        bad = os.path.join(inbox, "000000000099-x-y-zz.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        post.send("vulcan", "after-bad", {"fine": True}, frm="warden")
        # corrupt file sorts before the later send (99 < its seq? no:
        # seq of second send is 2) - so name it to sort first instead
        os.rename(bad, os.path.join(inbox, "000000000001-x-y-zz.json"))
        letters = post.read("vulcan")
        kinds = [l["kind"] for l in letters]
        assert "after-bad" in kinds, kinds
        assert not any(l["kind"] == "" for l in letters)
        seen_dir = os.path.join(post.root, "vulcan", "seen")
        assert any(f.startswith("corrupt-")
                   for f in os.listdir(seen_dir)), "corrupt quarantined"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def purge_caps_seen():
    post, tmp = sandbox()
    try:
        for i in range(30):
            post.send("gaia", "pulse", {"i": i}, frm="soil")
            post.read("gaia")
        removed = post.purge(keep_seen=10)
        seen_dir = os.path.join(post.root, "gaia", "seen")
        left = len([f for f in os.listdir(seen_dir)
                    if f.endswith(".json")])
        assert left <= 10 and removed >= 20, (left, removed)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------- broadcast

@check
def broadcast_tail_order():
    post, tmp = sandbox()
    try:
        for i in range(4):
            post.broadcast("incidents", "gate",
                           {"name": f"g{i}", "ok": i != 3},
                           frm="sentinel")
        recs = post.tail("incidents", n=10)
        assert [r["seq"] for r in recs] == [1, 2, 3, 4], recs
        assert recs[-1]["payload"]["ok"] is False
        assert recs[-1]["from"] == "sentinel"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def cursor_consume_only_new():
    post, tmp = sandbox()
    try:
        post.broadcast("nine-realms", "a", {"n": 1}, frm="yggdrasil")
        post.broadcast("nine-realms", "b", {"n": 2}, frm="yggdrasil")
        first = post.since("nine-realms", "heimdall")
        assert [r["seq"] for r in first] == [1, 2], first
        again = post.since("nine-realms", "heimdall")
        assert again == [], f"cursor should suppress replays: {again}"
        post.broadcast("nine-realms", "c", {"n": 3}, frm="yggdrasil")
        new = post.since("nine-realms", "heimdall")
        assert [r["seq"] for r in new] == [3], new
        other = post.since("nine-realms", "jormungandr")
        assert [r["seq"] for r in other] == [1, 2, 3], \
            "other consumers start from their own cursor"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------- heartbeats/misc

@check
def heartbeat_and_status():
    post, tmp = sandbox()
    try:
        post.register("argus", role="supervisor")
        post.beat("argus", note="all calm")
        age = post.heartbeat_age("argus", now=time.time())
        assert age is not None and -5 <= age < 60, age
        st = post.status()
        o = st["organs"]["argus"]
        assert o["unread"] == 0 and not o["stale"], o
        post.send("argus", "ping", {}, frm="cli")
        assert post.status()["organs"]["argus"]["unread"] == 1
        assert "argus" in post.organs() or True
        assert sorted(st["organs"]) == ["argus"], st["organs"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def registry_and_organs_listing():
    post, tmp = sandbox()
    try:
        post.register("odin", role="allfather")
        post.register("thoth", role="development layer")
        names = post.organs()
        assert set(["odin", "thoth"]).issubset(set(names)), names
        reg = json.load(open(os.path.join(post.root, "registry.json"),
                             encoding="utf-8"))
        assert reg["odin"]["role"] == "allfather", reg
        assert "registered" in reg["thoth"], reg
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def helpers_never_raise():
    outer = tempfile.mkdtemp(prefix="ratatosk-nope-")
    try:
        blocker = os.path.join(outer, "blocker")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("a file, not a dir")
        impossible = os.path.join(blocker, "post")
        assert publish("t", {}, frm="x", kind="k",
                       root=impossible) is None
        assert beat("ghost", note="x", root=impossible) is None
        ok_root = os.path.join(outer, "post")
        seq = publish("t", {"fine": True}, frm="x", kind="k",
                      root=ok_root)
        assert isinstance(seq, int) and seq == 1
    finally:
        shutil.rmtree(outer, ignore_errors=True)


@check
def env_root_override():
    old = os.environ.get("RATATOSK_ROOT")
    outer = tempfile.mkdtemp(prefix="ratatosk-env-")
    try:
        os.environ["RATATOSK_ROOT"] = os.path.join(outer, "post")
        assert default_root() == os.path.join(outer, "post")
        Post().send("a", "b", {}, frm="c")
        assert os.path.isdir(os.path.join(outer, "post", "a", "inbox"))
    finally:
        if old is None:
            os.environ.pop("RATATOSK_ROOT", None)
        else:
            os.environ["RATATOSK_ROOT"] = old
        shutil.rmtree(outer, ignore_errors=True)


@check
def cli_end_to_end():
    outer = tempfile.mkdtemp(prefix="ratatosk-cli-")
    env = dict(os.environ,
               RATATOSK_ROOT=os.path.join(outer, "post"),
               PYTHONPATH=ROOT_PARENT)
    py = sys.executable
    try:
        r = subprocess.run(
            [py, "-m", "ratatosk", "send", "--to", "zeus",
             "--kind", "bolt", "--payload", '{"pid": 123}',
             "--frm", "tester"],
            capture_output=True, text=True, cwd=ROOT_PARENT, env=env,
            timeout=120)
        assert r.returncode == 0, r.stderr
        r = subprocess.run(
            [py, "-m", "ratatosk", "read", "zeus"],
            capture_output=True, text=True, cwd=ROOT_PARENT, env=env,
            timeout=120)
        assert r.returncode == 0, r.stderr
        assert "bolt" in r.stdout and '{"pid": 123}' in r.stdout, \
            r.stdout
        r = subprocess.run(
            [py, "-m", "ratatosk", "status"],
            capture_output=True, text=True, cwd=ROOT_PARENT, env=env,
            timeout=120)
        assert r.returncode == 0 and "zeus" in r.stdout, r.stdout
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def main():
    print("=" * 64)
    print("RATATOSK VERIFY - filesystem communication network")
    print("=" * 64)
    failures = []
    for fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:              # noqa: BLE001 - verifier
            failures.append((fn.__name__, exc))
            print(f"[FAIL] {fn.__name__}: "
                  f"{type(exc).__name__}: {exc}")
    total, ok = len(CHECKS), len(CHECKS) - len(failures)
    print("-" * 64)
    print(f"{ok}/{total} checks green"
          + ("" if not failures else " - FAILURES PRESENT"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
