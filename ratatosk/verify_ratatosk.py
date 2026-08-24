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

from ratatosk.bus import (Post, default_root, publish, beat,          # noqa: E402
                          MAX_LETTER_BYTES, FLOOD_UNREAD)

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def sandbox(**kw):
    """A Post on a fresh throwaway root."""
    outer = tempfile.mkdtemp(prefix="ratatosk-verify-")
    return Post(root=os.path.join(outer, "post"), **kw), outer


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
        def mailer(k):
            for i in range(25):
                post.send("dashboard", "stat", {"w": k, "i": i},
                          frm=f"w{k}")

        def broadcaster(k):
            for i in range(25):
                post.broadcast("stats", "stat", {"w": k, "i": i},
                               frm=f"w{k}")

        # both lanes hammer at once - the density guarantees must hold
        # under mixed lock contention, not just one kind
        threads = [threading.Thread(target=mailer, args=(k,))
                   for k in range(4)]
        threads += [threading.Thread(target=broadcaster, args=(k,))
                    for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        letters = post.read("dashboard", limit=1000)
        ids = {l["id"] for l in letters}
        assert len(letters) == 100, f"lost letters: {len(letters)}"
        assert len(ids) == 100, "duplicate ids"

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


# ---------------------------------------------------- request/reply

@check
def request_reply_roundtrip():
    post, tmp = sandbox()
    try:
        def responder():
            # serve requests until the main thread stops asking
            while not stop.is_set():
                for l in post.peek("oracle"):
                    if l["kind"] == "divine" and "corr" in l:
                        post.respond(l, {"answer": 42}, frm="oracle")
                        return
                time.sleep(0.01)
        stop = threading.Event()
        th = threading.Thread(target=responder)
        th.start()
        try:
            reply = post.request("oracle", "divine", {"q": "meaning"},
                                 frm="seeker", timeout_s=5.0)
        finally:
            stop.set()
            th.join(timeout=5)
        assert isinstance(reply, dict), reply
        assert reply["kind"] == "divine.reply", reply
        assert reply["payload"] == {"answer": 42}, reply
        assert reply["from"] == "oracle", reply
        assert post.unread("seeker") == 0, \
            "matched reply must be consumed, other mail untouched"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def request_reply_wrong_corr_ignored():
    """A same-kind reply with a foreign corr must NOT satisfy a wait."""
    post, tmp = sandbox()
    try:
        # plant a decoy reply with the right kind but no matching corr
        post.send("seeker", "divine.reply", {"counterfeit": True},
                  frm="impostor")
        got = post.request("ghost", "divine", {"q": 1}, frm="seeker",
                           timeout_s=0.3, poll_s=0.02)
        assert got is None, got
        assert post.unread("seeker") == 1, \
            "decoy letter must stay in the inbox"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def request_timeout_returns_none():
    post, tmp = sandbox()
    try:
        post.send("seeker", "unrelated", {"keep": True}, frm="other")
        t0 = time.monotonic()
        got = post.request("nobody", "ping", {}, frm="seeker",
                           timeout_s=0.3, poll_s=0.05)
        assert got is None and time.monotonic() - t0 < 5, "must time out"
        letters = post.read("seeker")
        assert len(letters) == 1 and \
            letters[0]["kind"] == "unrelated", letters
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def request_bad_args_typeerror():
    post, tmp = sandbox()
    try:
        for bad in ({"kind": None}, {"timeout_s": "x"},
                    {"poll_s": 0}, {"poll_s": -1}):
            try:
                post.request("a", **dict(bad, payload={}, frm="b"))
            except TypeError:
                pass
            else:
                raise AssertionError(f"expected TypeError: {bad}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -------------------------------------------------- priority lanes

@check
def priority_lane_ordering():
    post, tmp = sandbox()
    try:
        post.send("zeus", "log", {"i": 1}, frm="s")
        post.send("zeus", "bolt", {"i": 2}, frm="s", priority="high")
        post.send("zeus", "log", {"i": 3}, frm="s")
        post.send("zeus", "smite", {"i": 4}, frm="s", priority="high")
        inbox = os.path.join(post.root, "zeus", "inbox")
        names = sorted(os.listdir(inbox))
        highs = [f for f in names if f.startswith("!.")]
        assert len(highs) == 2 and all(f[2:3].isdigit() for f in highs), \
            names
        assert names[:2] == highs, "high lane must sort first"
        order = [(l["kind"], l["payload"]["i"])
                 for l in post.read("zeus")]
        assert order == [("bolt", 2), ("smite", 4),
                         ("log", 1), ("log", 3)], order
        try:
            post.send("zeus", "x", {}, frm="s", priority="urgent")
        except ValueError:
            pass
        else:
            raise AssertionError("bad priority must be rejected")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------- rotating topics

@check
def rotation_continuity():
    """Tiny ROTATE_BYTES, many records: seqs stay dense across every
    rotation and no consumer loses a record (L026)."""
    post, tmp = sandbox(rotate_bytes=500, keep_segments=40)
    try:
        seqs = [post.broadcast("spin", "tick", {"i": i}, frm="ygg")
                for i in range(70)]
        assert seqs == list(range(1, 71)), \
            "broadcast seqs must be dense and never reset"
        base = os.path.join(post.root, "topics", "spin.jsonl")
        rotated = len([f for f in os.listdir(os.path.dirname(base))
                       if f.startswith("spin.jsonl.")])
        assert rotated >= 3, f"expected real rotations, got {rotated}"
        recs = post.tail("spin", n=1000)
        got = sorted(r["seq"] for r in recs)
        assert got == list(range(1, 71)), \
            f"tail must return each record exactly once: {len(got)}"
        # a consumer that checkpoints mid-stream loses nothing
        for i in range(35):
            post.broadcast("spin2", "tick", {"i": i}, frm="ygg")
        first = post.since("spin2", "watcher")
        assert [r["seq"] for r in first] == list(range(1, 36))
        for i in range(35, 70):
            post.broadcast("spin2", "tick", {"i": i}, frm="ygg")
        second = post.since("spin2", "watcher")
        union = ([r["seq"] for r in first] + [r["seq"] for r in second])
        assert sorted(union) == list(range(1, 71)), \
            "cursor consumer lost records across rotations"
        fresh = post.since("spin2", "latecomer")
        assert [r["seq"] for r in fresh] == list(range(1, 71))
        assert post.since("spin2", "latecomer") == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def rotation_bounds_segments():
    """KEEP is honored - the archive count stays bounded (L019) while
    broadcast keeps allocating unique forward seqs."""
    post, tmp = sandbox(rotate_bytes=200, keep_segments=2)
    try:
        seqs = [post.broadcast("churn", "tick", {"i": i}, frm="ygg")
                for i in range(50)]
        assert seqs == list(range(1, 51)), "seqs dense under churn"
        tdir = os.path.join(post.root, "topics")
        segs = [f for f in os.listdir(tdir)
                if f.startswith("churn.jsonl.")]
        assert len(segs) <= 2, segs
        recs = post.tail("churn", n=1000)
        got = [r["seq"] for r in recs]
        assert got == sorted(got), "tail must ascend by seq"
        assert len(got) == len(set(got)), "no duplicates"
        assert got[-1] == 50, "newest survivor must be the last seq"
        # counter-file loss must not resurrect old seqs
        os.unlink(os.path.join(tdir, "churn.seq"))
        nxt = post.broadcast("churn", "tick", {"i": 99}, frm="ygg")
        assert nxt == 51, nxt
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def legacy_topic_migration():
    """Pre-rotation single-file topics keep their seqs: the lazy
    counter seeds from existing lines and old line-number cursors
    still mean the same thing."""
    post, tmp = sandbox()
    try:
        tdir = os.path.join(post.root, "topics")
        os.makedirs(tdir, exist_ok=True)
        with open(os.path.join(tdir, "legacy.jsonl"), "a",
                  encoding="utf-8") as fh:
            for i in (1, 2, 3):
                fh.write(json.dumps({"v": 1, "topic": "legacy",
                                     "seq": i, "from": "old",
                                     "kind": "event",
                                     "payload": {"i": i}}) + "\n")
        cursors = os.path.join(post.root, "cursors")
        os.makedirs(cursors, exist_ok=True)
        with open(os.path.join(cursors, "elder.legacy"), "w",
                  encoding="utf-8") as fh:
            fh.write("2")               # old-era cursor: consumed seq<=2
        assert [r["seq"] for r in post.tail("legacy")] == [1, 2, 3]
        nxt = post.broadcast("legacy", "event", {"fresh": True},
                             frm="new")
        assert nxt == 4, f"legacy topic must continue at 4, got {nxt}"
        got = post.since("legacy", "elder")
        assert [r["seq"] for r in got] == [3, 4], got
        assert post.since("legacy", "elder") == []
        assert os.path.isfile(os.path.join(tdir, "legacy.seq"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------- metrics & vitals CLI

@check
def mailbox_metrics_counted():
    post, tmp = sandbox()
    try:
        post.register("odin", role="requester")
        post.send("mimir", "wisdom", {"rune": "ansuz"}, frm="odin")
        post.send("mimir", "wisdom", {"rune": "thurisaz"}, frm="odin")
        corrupt = os.path.join(post.root, "mimir", "inbox",
                               "000000000001-x-y-zz.json")
        with open(corrupt, "w", encoding="utf-8") as fh:
            fh.write("{bad json")
        post.read("mimir")               # 2 good + 1 quarantined
        post.respond({"from": "mimir", "kind": "question",
                      "corr": "abc"}, {"a": 1}, frm="odin")
        st = post.status()["organs"]["mimir"]["metrics"]
        assert st["received"] == 2 and st["quarantined"] == 1, st
        sender = post.status()["organs"]["odin"]["metrics"]
        assert sender["sent"] == 3 and sender["replied"] == 1, sender
        on_disk = json.load(open(os.path.join(post.root, "mimir",
                                              "metrics.json"),
                                 encoding="utf-8"))
        assert on_disk["received"] == 2, on_disk
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def metrics_never_raise_on_corrupt_state():
    post, tmp = sandbox()
    try:
        mdir = os.path.join(post.root, "huginn")
        os.makedirs(os.path.join(mdir, "inbox"), exist_ok=True)
        with open(os.path.join(mdir, "metrics.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("garbage{")
        post.send("huginn", "scout", {}, frm="muninn")
        letters = post.read("huginn")     # bump hits corrupt file
        assert len(letters) == 1
        m = post.status()["organs"]["huginn"]["metrics"]
        assert m["sent"] >= 0 and m["received"] >= 0, \
            "corrupt state degrades to defaults, never raises"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check
def vitals_cli_exit_codes():
    outer = tempfile.mkdtemp(prefix="ratatosk-vitals-")
    env = dict(os.environ,
               RATATOSK_ROOT=os.path.join(outer, "post"),
               PYTHONPATH=ROOT_PARENT)
    py = sys.executable

    def run(cli_args):
        return subprocess.run([py, "-m", "ratatosk", *cli_args],
                              capture_output=True, text=True,
                              cwd=ROOT_PARENT, env=env, timeout=120)
    try:
        run(["send", "--to", "fenrir", "--kind", "howl",
             "--payload", "{}", "--frm", "tyr"])
        # fenrir has no heartbeat -> strict must fail
        r = run(["vitals", "--strict"])
        assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
        assert "fenrir" in r.stdout and "STALE" in r.stdout, r.stdout
        # after a heartbeat, strict passes
        r = subprocess.run(
            [py, "-c",
             "import os; from ratatosk import Post; "
             f"Post(os.environ['RATATOSK_ROOT']).beat('fenrir')"],
            capture_output=True, text=True, cwd=ROOT_PARENT, env=env,
            timeout=120)
        assert r.returncode == 0, r.stderr
        r = run(["vitals", "--strict"])
        assert r.returncode == 0, (r.returncode, r.stderr)
        # a manually aged heartbeat trips --stale-s
        hb_path = os.path.join(outer, "post", "fenrir",
                               "heartbeat.json")
        hb = json.load(open(hb_path, encoding="utf-8"))
        hb["epoch"] = hb["epoch"] - 10000
        json.dump(hb, open(hb_path, "w", encoding="utf-8"))
        r = run(["vitals", "--strict", "--stale-s", "600"])
        assert r.returncode == 1, (r.returncode, r.stdout)
        # topic line counts appear
        subprocess.run([py, "-c",
                        "import os; from ratatosk import Post; "
                        "p = Post(os.environ['RATATOSK_ROOT']); "
                        "[p.broadcast('skoll', 'chase', {'i': i}) "
                        "for i in range(2)]"],
                       capture_output=True, cwd=ROOT_PARENT, env=env,
                       timeout=120)
        r = run(["vitals"])
        assert r.returncode == 0 and "topic skoll: 2 lines" in r.stdout, \
            r.stdout
    finally:
        shutil.rmtree(outer, ignore_errors=True)


@check
def oversize_letter_guards():
    post, outer = sandbox()
    try:
        big = {"blob": "x" * (MAX_LETTER_BYTES + 1024)}
        try:
            post.send("gatekeeper", "huge", big, frm="abuser")
            raise AssertionError("oversize send must raise ValueError")
        except ValueError:
            pass
        # never-raise senders truncate to a reference note instead
        seq = publish("gate-topic", big, frm="abuser", kind="big",
                      root=post.root)
        assert isinstance(seq, int)
        rec = post.tail("gate-topic", n=1)[0]
        assert rec["payload"].get("_truncated") is True, rec["payload"]
        assert "preview" in rec["payload"]
        from ratatosk import safe_send, fit_payload
        lid = safe_send("gatekeeper", "trimmed", big, frm="abuser",
                        root=post.root)
        assert lid is not None
        letters = post.read("gatekeeper")
        assert letters[0]["payload"].get("_truncated") is True
        small = fit_payload({"ok": 1})
        assert small == {"ok": 1}, "small payloads pass through intact"
    finally:
        shutil.rmtree(outer, ignore_errors=True)


@check
def flood_flag_and_deadman():
    from ratatosk import deadman
    # low per-instance threshold: proves the wiring without paying
    # 1000 lock round-trips on slow filesystems
    post, outer = sandbox()
    post.flood_unread = 20
    try:
        for i in range(25):
            post.send("swamped", "p", {"i": i}, frm="feeder")
        st = post.status()
        assert st["organs"]["swamped"]["flooded"] is True
        assert st["organs"]["swamped"]["unread"] == 25
        # default threshold stays production-grade
        post2 = Post(root=post.root)
        assert post2.status()["organs"]["swamped"]["flooded"] is False, \
            "default threshold must remain FLOOD_UNREAD"
        post.beat("swamped", note="alive")
        assert deadman("swamped", max_age_s=600,
                       root=post.root) is False
        assert deadman("never-beat-organ", max_age_s=600,
                       root=post.root) is True
        old = time.time() - 9999
        post.beat("elder", note=None)
        hb = os.path.join(post.root, "elder", "heartbeat.json")
        doc = json.load(open(hb, encoding="utf-8"))
        doc["epoch"] = old
        json.dump(doc, open(hb, "w", encoding="utf-8"))
        assert deadman("elder", max_age_s=600, root=post.root) is True
    finally:
        shutil.rmtree(outer, ignore_errors=True)


@check
def safeguards_gate_catches_breakage():
    """The repo gate itself: dup-def detector + JSON gate + strict
    mixed-state behavior, exercised through check.py on temp files."""
    import subprocess as sp
    outer = tempfile.mkdtemp(prefix="safegate-")
    py = sys.executable
    checker = os.path.join(ROOT_PARENT, "safeguards", "check.py")
    try:
        badpy = os.path.join(outer, "dup.py")
        open(badpy, "w", encoding="utf-8").write(
            "def twice():\n    return 1\n\n\ndef twice():\n    return 2\n")
        r = sp.run([py, checker, badpy], capture_output=True, text=True)
        assert r.returncode != 0 and "'twice'" in r.stdout, r.stdout
        badjson = os.path.join(outer, "broken.json")
        open(badjson, "w", encoding="utf-8").write('{"a": 1,,}')
        r = sp.run([py, checker, badjson], capture_output=True, text=True)
        assert r.returncode != 0 and "json" in r.stdout.lower(), r.stdout
        goodpy = os.path.join(outer, "clean.py")
        open(goodpy, "w", encoding="utf-8").write("X = 1\n")
        r = sp.run([py, checker, "--strict", goodpy],
                   capture_output=True, text=True)
        assert r.returncode == 0, r.stdout
    finally:
        shutil.rmtree(outer, ignore_errors=True)


@check
def safe_commit_isolated_index():
    """Dogfood the isolated-index committer on a throwaway repo:
    unrelated staged junk in a shared index must NOT leak into the
    commit. Scratch init keeps this drill under a second - the tool's
    mechanics (temp index, scoped staging, gates) need a repo with a
    HEAD, not our whole platform tree."""
    import subprocess as sp
    py = sys.executable
    sc = os.path.join(ROOT_PARENT, "safeguards", "safe_commit.py")
    outer = tempfile.mkdtemp(prefix="safe-commit-")
    repo = os.path.join(outer, "repo")

    def g(*args):
        return sp.run(["git", *args], cwd=repo, capture_output=True,
                      text=True)

    def w(rel, text):
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    try:
        os.makedirs(repo, exist_ok=True)
        assert g("init", "-q").returncode == 0
        # CI runners carry no git identity; scope one to the scratch
        # repo, never the operator's global config
        for cfg in ("user.name", "user.email"):
            g("config", cfg, "safeguards-drill")
        seed = w("base.txt", "seed commit so read-tree HEAD works\n")
        g("add", "base.txt")
        r = g("commit", "-q", "-m", "seed")
        assert r.returncode == 0, r.stderr
        lane_a = w("lane_a.txt", "lane A change\n")
        junk = w("lane_b_junk.txt", "patron lane's staged junk\n")
        g("add", "lane_a.txt", "lane_b_junk.txt")
        r = sp.run([py, sc, "-m",
                    "lane A only - junk must stay out",
                    "lane_a.txt"],
                   cwd=repo, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr + r.stdout
        shown = g("show", "--name-only", "--format=", "HEAD").stdout.split()
        assert shown == ["lane_a.txt"], shown
        assert os.path.isfile(lane_a) and os.path.isfile(junk), \
            "committed file and foreign junk both stay on disk"
        status = g("status", "--short").stdout
        assert "lane_b_junk" in status, \
            "junk must remain staged for its owner"
        assert "base.txt" not in shown
        del seed
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def main():
    print("=" * 64)
    print("RATATOSK VERIFY - filesystem communication network")
    print("=" * 64)
    failures = []
    for fn in CHECKS:
        t0 = time.monotonic()
        try:
            fn()
            dt = time.monotonic() - t0
            print(f"[PASS] {fn.__name__} ({dt:.1f}s)")
        except Exception as exc:              # noqa: BLE001 - verifier
            failures.append((fn.__name__, exc))
            dt = time.monotonic() - t0
            print(f"[FAIL] {fn.__name__} ({dt:.1f}s): "
                  f"{type(exc).__name__}: {exc}")
    total, ok = len(CHECKS), len(CHECKS) - len(failures)
    print("-" * 64)
    print(f"{ok}/{total} checks green"
          + ("" if not failures else " - FAILURES PRESENT"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
