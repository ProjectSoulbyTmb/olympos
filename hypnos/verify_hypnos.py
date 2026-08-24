"""HYPNOS verifier - the silent organ's contract, checked.

Every check runs in a throwaway workspace with its own post root;
the live data/post, queue and audit are never touched.
Exit 0 = all green.

    python hypnos/verify_hypnos.py
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_PARENT = os.path.dirname(HERE)
sys.path.insert(0, ROOT_PARENT)

from hypnos import content                    # noqa: E402
from hypnos.actions import execute            # noqa: E402
from hypnos.kernel import Breaker, Kernel, sandbox  # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def submit(post, payload, frm="operator"):
    return post.send(content.ORGAN, "task", payload, frm=frm)


def results_from(post, organ):
    return [l for l in post.read(organ)
            if l.get("kind") == "task-result"]


# --------------------------------------------------------------- actions

@check
def verbs_roundtrip_in_one_task():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        target = os.path.join("sub", "hello.txt")
        submit(k.post, {
            "label": "roundtrip",
            "on_error": "continue",
            "actions": [
                {"do": "write_file", "path": target,
                 "text": "sleep well\n"},
                {"do": "append_file", "path": target, "text": "again\n"},
                {"do": "mkdir", "path": "sub/deeper"},
                {"do": "copy", "src": target, "dst": "sub/copy.txt"},
                {"do": "move", "src": "sub/copy.txt",
                 "dst": "sub/deeper/moved.txt"},
                {"do": "run",
                 "argv": [sys.executable, "-c", "print('ran-ok')"],
                 "timeout_s": 30},
                {"do": "mail", "to": "gaia", "kind": "hello",
                 "payload": {"from-task": "roundtrip"}},
                {"do": "broadcast", "topic": "hypnos-test",
                 "kind": "ping", "payload": {"n": 1}},
            ]})
        s = k.tick()
        assert s["claimed"] == 1 and s["ran"] == 1, s
        p = os.path.join(content.WORKSPACE, target)
        with open(p, "r", encoding="utf-8") as fh:
            assert fh.read() == "sleep well\nagain\n"
        assert os.path.exists(
            os.path.join(content.WORKSPACE, "sub", "deeper", "moved.txt"))
        gaia_mail = k.post.read("gaia")
        assert len(gaia_mail) == 1 and \
            gaia_mail[0]["payload"]["from-task"] == "roundtrip", gaia_mail
        topic = k.post.tail("hypnos-test")
        assert topic and topic[-1]["payload"]["n"] == 1, topic
        res = results_from(k.post, "operator")
        assert len(res) == 1 and res[0]["payload"]["ok"], res


@check
def run_reports_exit_code_stdout_stderr():
    out = execute({"do": "run",
                   "argv": [sys.executable, "-c",
                            "import sys; print('out'); "
                            "sys.stderr.write('err\\n'); "
                            "sys.exit(3)"]})
    assert out["exit_code"] == 3 and not out["ok"], out
    assert "out" in out["stdout"] and "err" in out["stderr"], out


@check
def runaway_run_is_killed_by_timeout():
    started = time.time()
    out = execute({"do": "run",
                   "argv": [sys.executable, "-c", "import time; "
                            "time.sleep(60)"],
                   "timeout_s": 1})
    assert out["timed_out"] and not out["ok"], out
    assert time.time() - started < 15, "kill took too long"


@check
def unknown_verb_fails_without_raising():
    out = execute({"do": "teleport", "where": "asgard"})
    assert not out["ok"] and "unknown verb" in out["error"], out


@check
def delete_needs_expensive_consent_for_dirs():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        d = os.path.join(content.WORKSPACE, "grove")
        os.makedirs(os.path.join(d, "inner"))
        bad = execute({"do": "delete", "path": "grove"})
        assert not bad["ok"], bad
        good = execute({"do": "delete", "path": "grove",
                        "recursive": True})
        assert good["ok"] and not os.path.exists(d), (good, d)


@check
def escapes_are_refused():
    outside = tempfile.mkdtemp(prefix="hypnos-outside-")
    try:
        rel = execute({"do": "write_file", "path": "../escape.txt",
                       "text": "no"})
        assert not rel["ok"] and "outside allowed roots" in rel["error"]
        sneaky = execute({"do": "write_file",
                          "path": os.path.join("sub", "..", "..", "..",
                                               "escape2.txt"),
                          "text": "no"})
        assert not sneaky["ok"], sneaky
        absu = execute({"do": "write_file",
                        "path": os.path.join(outside, "x.txt"),
                        "text": "no"})
        assert not absu["ok"], absu
        assert not os.listdir(outside), "something escaped!"
    finally:
        shutil.rmtree(outside, ignore_errors=True)


# ----------------------------------------------------------- mail engine

@check
def letter_roundtrip_replies_to_sender():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        lid = submit(k.post, {"task": "greet", "actions": [
            {"do": "write_file", "path": "made.txt", "text": "hi"}]})
        s = k.tick()
        assert s["claimed"] == 1 and s["ran"] == 1, s
        res = results_from(k.post, "operator")
        assert len(res) == 1, res
        assert res[0]["payload"]["task"].endswith(lid.split("-")[-1]) \
            or res[0]["payload"]["ok"], res[0]["payload"]
        assert os.path.exists(
            os.path.join(content.WORKSPACE, "made.txt"))
        rec = k.post.tail(content.TOPIC)
        assert rec and rec[-1]["kind"] == "task-done", rec


@check
def batch_of_letters_drains_fifo():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        for i in range(4):
            submit(k.post, {"task": "t%d" % i, "actions": [
                {"do": "write_file", "path": "f%d.txt" % i,
                 "text": str(i)}]})
        s = k.tick()
        assert s["claimed"] == 4 and s["ran"] == 4, s
        made = sorted(f for f in os.listdir(content.WORKSPACE)
                      if f.startswith("f"))
        assert made == ["f0.txt", "f1.txt", "f2.txt", "f3.txt"], made


@check
def corrupt_letter_is_quarantined_not_fatal():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        submit(k.post, {"actions": [{"do": "mkdir", "path": "still-here"}]})
        inbox = os.path.join(os.environ["RATATOSK_ROOT"],
                             content.ORGAN, "inbox")
        with open(os.path.join(inbox, "garbage.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{not json")
        s = k.tick()
        assert s["claimed"] == 1, s
        seen = os.path.join(os.environ["RATATOSK_ROOT"],
                            content.ORGAN, "seen")
        assert any(f.startswith("corrupt-") for f in os.listdir(seen))


@check
def invalid_task_letter_gets_failure_reply():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        submit(k.post, {"actions": "not-a-list"})
        submit(k.post, {"actions": [{"do": "write_file"}] * 999})
        k.tick()
        res = results_from(k.post, "operator")
        assert len(res) == 2 and all(not r["payload"]["ok"]
                                     for r in res), res


# ------------------------------------------------------------ queue engine

@check
def crash_leftover_claims_auto_resume():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        # simulate a process dying right after claiming
        job = {"v": 1, "id": "orphan-1", "task": "orphan",
               "label": "died mid-run",
               "actions": [{"do": "write_file", "path": "rescued.txt",
                            "text": "saved"}],
               "on_error": "stop", "reply_to": "operator",
               "src": "mail", "attempts": 1, "max_attempts": 1,
               "next_epoch": 0, "enqueued_epoch": 0}
        from hypnos.kernel import _atomic_json
        _atomic_json(os.path.join(content.QUEUE_DIR, "orphan-1.json"),
                     job)
        before = k.resumed
        s = k.tick()
        assert s["ran"] == 1 and k.resumed == before + 1, (s, k.resumed)
        assert os.path.exists(
            os.path.join(content.WORKSPACE, "rescued.txt"))
        res = results_from(k.post, "operator")
        assert len(res) == 1 and res[0]["payload"]["ok"], res
        assert not glob.glob(os.path.join(content.QUEUE_DIR, "*.json"))


@check
def failed_task_retries_with_backoff_then_finalizes():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        submit(k.post, {"task": "flaky", "retry": True, "actions": [
            {"do": "run", "argv": [sys.executable, "-c",
                                   "raise SystemExit(2)"]}]})
        s1 = k.tick()
        assert s1["retries"] == 1, s1
        claims = glob.glob(os.path.join(content.QUEUE_DIR, "*.json"))
        assert len(claims) == 1, claims          # kept for another try
        for _ in range(content.RETRY_MAX_ATTEMPTS - 1):
            job = json.load(open(claims[0], encoding="utf-8"))
            job["next_epoch"] = 0               # backoff elapses
            json.dump(job, open(claims[0], "w", encoding="utf-8"))
            k.tick()
        assert not glob.glob(
            os.path.join(content.QUEUE_DIR, "*.json")), "claim stuck"
        assert k.tasks_failed == 1, k.tasks_failed
        res = results_from(k.post, "operator")
        assert len(res) == 1 and not res[0]["payload"]["ok"], res
        rec = k.post.tail(content.TOPIC)
        assert rec[-1]["kind"] == "task-failed", rec


@check
def duplicate_letter_enqueues_once():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        payload = {"task": "dupe", "actions":
                   [{"do": "write_file", "path": "once.txt", "text": "1"}]}
        submit(k.post, dict(payload))
        submit(k.post, dict(payload))
        s = k.tick()
        assert s["claimed"] == 1 and s["ran"] == 1, s
        text = open(os.path.join(content.WORKSPACE, "once.txt"),
                    encoding="utf-8").read()
        assert text == "1", text


@check
def on_error_policy_controls_chaining():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        submit(k.post, {"on_error": "stop", "actions": [
            {"do": "delete", "path": "missing.file"},
            {"do": "write_file", "path": "never.txt", "text": "x"}]})
        submit(k.post, {"on_error": "continue", "actions": [
            {"do": "delete", "path": "missing.file"},
            {"do": "write_file", "path": "always.txt", "text": "y"}]})
        k.tick()
        assert not os.path.exists(
            os.path.join(content.WORKSPACE, "never.txt"))
        assert os.path.exists(
            os.path.join(content.WORKSPACE, "always.txt"))


# ------------------------------------------------------------ sweep engine

@check
def dropin_files_become_work_and_archive_results():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        os.makedirs(content.DROPIN_DIR, exist_ok=True)
        drop = os.path.join(content.DROPIN_DIR, "sweep-me.task.json")
        with open(drop, "w", encoding="utf-8") as fh:
            json.dump({"task": "sweep", "reply_to": None, "actions": [
                {"do": "write_file", "path": "swept.txt",
                 "text": "drop"}]}, fh)
        s = k.tick()
        assert s["dropins"] == 1 and s["ran"] == 1, s
        assert not os.path.exists(drop), "drop-in not consumed"
        assert os.path.exists(
            os.path.join(content.WORKSPACE, "swept.txt"))
        done = os.listdir(content.DROPIN_DONE)
        results = [f for f in done if f.endswith(".result.json")]
        assert len(results) == 1, done
        assert "sweep-me.task.json" in done, done  # original archived


@check
def corrupt_dropin_parked_not_fatal():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        os.makedirs(content.DROPIN_DIR, exist_ok=True)
        with open(os.path.join(content.DROPIN_DIR, "bad.task.json"),
                  "w", encoding="utf-8") as fh:
            fh.write("[[[")
        s = k.tick()
        assert s["dropins"] == 0, s
        failed = os.listdir(content.DROPIN_FAILED)
        assert any(f.startswith("corrupt-") for f in failed), failed


# -------------------------------------------------------- build + hygiene

@check
def build_engine_feeds_the_live_system():
    saved_gates, saved_min = content.BUILD_GATES, \
        content.BUILD_MIN_INTERVAL_S
    try:
        with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
            content.BUILD_ENABLED = True      # sandbox disables by default
            content.BUILD_GATES = [
                {"name": "selfcheck",
                 "argv": [sys.executable, "-c", "print('gate-ok')"],
                 "timeout_s": 60}]
            content.BUILD_MIN_INTERVAL_S = 0
            submit(k.post, {"actions": [{"do": "mkdir", "path": "b"}]})
            s = k.tick()
            assert s["built"], s
            report = json.load(open(
                os.path.join(content.DATA_DIR, "build.json"),
                encoding="utf-8"))
            assert report["ok"] and report["gates"][0]["ok"], report
            assert "gate-ok" in report["gates"][0]["tail"], report
            rec = k.post.tail(content.TOPIC)
            assert rec[-1]["kind"] == "build" and rec[-1]["payload"][
                "ok"], rec
    finally:
        content.BUILD_GATES = saved_gates
        content.BUILD_MIN_INTERVAL_S = saved_min


@check
def failing_gate_publishes_build_failed():
    saved_gates, saved_min = content.BUILD_GATES, \
        content.BUILD_MIN_INTERVAL_S
    try:
        with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
            content.BUILD_ENABLED = True
            content.BUILD_GATES = [
                {"name": "broken",
                 "argv": [sys.executable, "-c", "raise SystemExit(1)"],
                 "timeout_s": 60}]
            content.BUILD_MIN_INTERVAL_S = 0
            submit(k.post, {"actions": [{"do": "mkdir", "path": "b"}]})
            s = k.tick()
            assert s["built"], s
            rec = k.post.tail(content.TOPIC)
            assert rec[-1]["kind"] == "build-failed", rec
            assert not json.load(open(
                os.path.join(content.DATA_DIR, "build.json"),
                encoding="utf-8"))["ok"]
    finally:
        content.BUILD_GATES = saved_gates
        content.BUILD_MIN_INTERVAL_S = saved_min


@check
def maintenance_prunes_archives():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        for i in range(6):
            with open(os.path.join(content.DROPIN_DONE,
                                   "old%d.result.json" % i), "w") as fh:
                fh.write("{}")
        saved_keep = content.DROPIN_KEEP
        try:
            content.DROPIN_KEEP = 2
            k._maintain()
            left = os.listdir(content.DROPIN_DONE)
            assert len(left) <= 2, left
        finally:
            content.DROPIN_KEEP = saved_keep


@check
def audit_rotates_before_unbounded_growth():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        saved_max = content.AUDIT_MAX_BYTES
        try:
            content.AUDIT_MAX_BYTES = 500
            for i in range(20):
                k.audit("spam", i=i, pad="x" * 80)
            assert k._rotate_audit(), "rotation did not trigger"
            assert os.path.exists(content.AUDIT_PATH + ".1.jsonl")
            k.audit("post-rotate")          # current file exists again
            assert os.path.getsize(content.AUDIT_PATH) < \
                os.path.getsize(content.AUDIT_PATH + ".1.jsonl")
        finally:
            content.AUDIT_MAX_BYTES = saved_max


@check
def breaker_trips_then_self_revives():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        b = Breaker("test-phase", k)

        def boom():
            raise RuntimeError("probe")

        for _ in range(content.SUBSYSTEM_FAIL_LIMIT):
            b.run(boom)
        assert b.tripped and b.cool_ticks_left > 0
        for _ in range(b.cool_ticks_left):
            b.run(lambda: "idle")
        assert not b.tripped, "breaker never revived"
        assert b.run(lambda: "alive") == "alive"


@check
def state_and_heartbeat_stay_fresh():
    with sandbox(tempfile.mkdtemp(prefix="hypnos-v-")) as k:
        k.tick()
        snap = json.load(open(content.STATE_PATH, encoding="utf-8"))
        assert snap["ticks"] >= 1, snap
        age = k.post.heartbeat_age(content.ORGAN)
        assert age is not None and age < 30, age


# ------------------------------------------------------------- gate runner

def main():
    passed = 0
    failed = []
    for fn in CHECKS:
        label = fn.__name__.replace("_", " ")
        try:
            fn()
            passed += 1
            print("[ok]   %s" % label)
        except Exception as exc:              # noqa: BLE001 - gate reports all
            failed.append((fn.__name__, repr(exc)))
            print("[FAIL] %s -> %r" % (label, exc))
    print("-" * 56)
    print("HYPNOS VERIFY: %d/%d checks passed" % (passed, len(CHECKS)))
    if failed:
        for name, err in failed:
            print("  %s: %s" % (name, err))
        return 1
    print("the sleeper keeps its contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
