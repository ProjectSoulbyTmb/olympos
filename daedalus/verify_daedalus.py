"""DAEDALUS gate - the workshop contract, checked end to end.

Spec schema gates, weave/gate/fix convergence (fault injection proves
the retry loop learns), subfleet parallelism + rights on the wire,
warden self-healing, tamper-evident audit. All inside throwaway
ATLAS guests.
"""

import contextlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from daedalus import content                     # noqa: E402
from daedalus.blueprints import BLUEPRINTS       # noqa: E402
from daedalus.kernel import Workshop             # noqa: E402
from daedalus.rules import validate_spec          # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn

@contextlib.contextmanager
def sandbox():
    from atlas.kernel import Hypervisor
    import atlas.content as ac
    outer = tempfile.mkdtemp(prefix="daedalus-verify-")
    saved_d = {f: getattr(content, f) for f in
               ("DATA_DIR", "AUDIT_PATH", "ARTIFACTS_DIR",
                "REPAIR_STATS_PATH", "PLANS_DIR")}
    saved_a = {"GUESTS_DIR": ac.GUESTS_DIR,
               # the hypervisor's audit chain binds atlas's AUDIT_PATH;
               # without this redirect every check verifies the SHARED
               # default trail - including its historical damage - and
               # parallel suites interleave appends into it (the
               # tamper-evidence flake under load)
               "AUDIT_PATH": ac.AUDIT_PATH}
    saved_env = os.environ.get("RATATOSK_ROOT")
    data = os.path.join(outer, "data")
    content.DATA_DIR = data
    content.AUDIT_PATH = os.path.join(data, "audit.jsonl")
    content.ARTIFACTS_DIR = os.path.join(data, "artifacts")
    content.REPAIR_STATS_PATH = os.path.join(data, "repair_stats.json")
    content.PLANS_DIR = os.path.join(data, "plans")
    ac.GUESTS_DIR = os.path.join(outer, "guests")
    ac.AUDIT_PATH = os.path.join(data, "atlas-audit.jsonl")
    os.environ["RATATOSK_ROOT"] = os.path.join(outer, "post")
    os.makedirs(ac.GUESTS_DIR, exist_ok=True)
    try:
        yield Hypervisor()
    finally:
        for f, v in saved_d.items():
            setattr(content, f, v)
        for f, v in saved_a.items():
            setattr(ac, f, v)
        if saved_env is None:
            os.environ.pop("RATATOSK_ROOT", None)
        else:
            os.environ["RATATOSK_ROOT"] = saved_env
        shutil.rmtree(outer, ignore_errors=True)


@check
def spec_schema_gates():
    good = {"blueprint": "jsonl-echo"}
    assert validate_spec(good, BLUEPRINTS.keys()) == []
    issues = validate_spec({"blueprint": "nope"}, BLUEPRINTS.keys())
    assert any("unknown blueprint" in i for i in issues), issues
    issues = validate_spec({"blueprint": 3})
    assert any("'blueprint'" in i for i in issues), issues
    issues = validate_spec({"blueprint": "jsonl-echo",
                            "faults": [1]})
    assert any("strings" in i for i in issues), issues


@check
def clean_build_seals_artifact_first_try():
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        ws.submit({"blueprint": "jsonl-echo", "name": "clean"})
        r = ws.build_next()
        assert r and r["ok"] and r["attempts"] == 1, r
        assert r["artifact_sha256"], r
        arts = os.listdir(content.ARTIFACTS_DIR)
        assert len(arts) == 1, arts


@check
def fault_injection_converges_via_fix_pass():
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        ws.submit({"blueprint": "jsonl-echo", "name": "sick",
                   "faults": ["drop_echo"], "attempts": 3})
        r = ws.build_next()
        assert r["ok"], r
        assert r["fixed"] is True and r["attempts"] >= 2, \
            "fix pass did not run"


@check
def fleet_runs_builds_across_lanes():
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=2)
        for i in range(2):
            ws.submit({"blueprint": "http-health", "name": f"par{i}"})
        a = ws.build_next()
        b = ws.build_next()
        assert a and b and a["ok"] and b["ok"], (a, b)
        snap = ws.fleet.snapshot()
        assert all(l["state"] == "idle" for l in snap), snap
        assert sum(l["ok"] for l in snap) == 2, snap


@check
def warden_quarantines_failing_blueprint():
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        # force a storm: three failed history entries for one design
        for i in range(3):
            ws.history.append({"id": f"h{i}", "blueprint": "cursed",
                               "ok": False})
        findings = ws.warden.patrol()
        assert any(f["kind"] == "storm" for f in findings), findings
        assert not ws.warden.blueprint_available("cursed")
        assert ws.warden.blueprint_available("jsonl-echo")


@check
def wire_rights_watchers_read_only():
    from daedalus.server import DaedalusServer
    with sandbox() as hv:
        srv = DaedalusServer(port=0, workshop=Workshop(
            hypervisor=hv, lanes=1))
        srv.start_async()
        try:
            r = srv.handle("blueprints", {}, cid=1)
            assert r["error"] is None, r
            r = srv.handle("build", {"spec": {
                "blueprint": "jsonl-echo"}}, cid=1)
            assert r["error"] is None, r
            srv.profiles[2] = "watcher"
            r = srv.handle("build", {"spec": {
                "blueprint": "jsonl-echo"}}, cid=2)
            assert "right_denied" in str(r.get("error")), r
            r = srv.handle("status", {}, cid=2)
            assert r["error"] is None, "watcher lost status"
        finally:
            srv.running = False


@check
def audit_trail_is_tamper_evident():
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        ws.submit({"blueprint": "jsonl-echo"})
        ws.build_next()
        # two chains: the workshop's and the atlas lane's, both clean
        ok, count, bad = ws.audit.verify()
        assert ok and count >= 2, (ok, count, bad)
        lok, lcount, lbad = hv.audit.verify()
        assert lok and lcount >= 2, (lok, lcount, lbad)
        lines = open(ws.audit.path, encoding="utf-8").readlines()
        forged = json.loads(lines[0])
        forged["kind"] = "forged"
        lines[0] = json.dumps(forged, sort_keys=True,
                              separators=(",", ":")) + "\n"
        with open(ws.audit.path, "w", encoding="utf-8",
                  newline="") as fh:
            fh.writelines(lines)
        ok, _c, bad = ws.audit.verify()
        assert not ok and bad == 1, (ok, bad)


@check
def parallel_drain_weaves_every_lane_at_once():
    import time as _t

    def slow_gate(bp_dir):
        return None
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=2)
        ids = [ws.submit({"blueprint": "jsonl-echo",
                          "name": f"par-{i}"})["id"] for i in range(2)]
        t0 = _t.time()
        r = ws.drain_parallel(max_jobs=2)
        elapsed = _t.time() - t0
        assert r["drained"] == 2, r
        assert all(x.get("ok") for x in r["results"]), r
        snap = ws.fleet.snapshot()
        assert sum(1 for l in snap if l["ok"] == 1) == 2, \
            "both lanes must have woven one build"
        # two ~0.4s gate runs joined concurrently must beat their sum
        assert elapsed < 1.6, f"parallel drain ran serially ({elapsed}s)"


@check
def flapping_lane_cools_down_instead_of_looping():
    from daedalus import content as dc
    from daedalus.fleet import SubFleet
    with sandbox() as hv:
        saved = dc.LANE_COOLDOWN_S
        dc.LANE_COOLDOWN_S = 0.05
        try:
            pool = SubFleet(2, hv)
            hot = pool.lanes[0]
            job = {"blueprint": "jsonl-echo", "id": "hot-job"}
            for _ in range(dc.LANE_COOLDOWN_AFTER_FAILS):
                hot.take(dict(job))
                hot.release(False, "gate red")
            assert hot.cooldown_until > 0, "cooldown never engaged"
            picked = pool.acquire(job)
            assert picked is not hot, "cooling lane was handed work"
            import time as _t
            _t.sleep(0.07)
            assert hot.available(), "lane never rejoined after cooldown"
        finally:
            dc.LANE_COOLDOWN_S = saved


@check
def dispatch_prefers_the_warm_lane():
    from daedalus.fleet import SubFleet
    with sandbox() as hv:
        pool = SubFleet(2, hv)
        warm = pool.lanes[0]
        warm.take({"blueprint": "jsonl-echo", "id": "warm-up"})
        warm.release(True)
        again = pool.acquire({"blueprint": "jsonl-echo"})
        assert again is warm, "affinity ignored a proven-warm lane"


@check
def sick_guest_rebuilds_itself():
    import sys as _sys
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        lane = ws.fleet.lanes[0]
        dead = lane.guest
        old_world = hv.get(dead)          # object identity, not the key:
        lane.release(False, "guest world corrupted", heal=True)
        # the lane re-slugs to the same id by design, so a rebirth is
        # proven by a DIFFERENT world object behind that key...
        assert hv.guests[dead] is not old_world, \
            "same world object survived the heal"
        assert lane.rebuilds == 1, "lane did not self-build"
        r = hv.exec(lane.guest, [_sys.executable, "-c", "print(1)"])
        assert r["ok"], "freshly built guest cannot run jobs"


@check
def pump_drains_the_queue_autonomously():
    import time as _t
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        assert ws.pump_start() is True
        try:
            jid = ws.submit({"blueprint": "jsonl-echo",
                             "name": "fluid"})["id"]
            deadline = _t.time() + 10
            while _t.time() < deadline:
                if ws.jobs[jid]["state"] == "done":
                    break
                _t.sleep(0.1)
            else:
                raise AssertionError("pump never drained the queue")
            assert ws.history[-1]["ok"], ws.history[-1]
        finally:
            ws.pump_stop()
        assert not ws.pump_running(), "pump refused to stop"
def new_blueprints_gate_green():
    """kv-store and beat-worker weave, gate, and seal first try."""
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=2)
        ws.submit({"blueprint": "kv-store", "name": "kv1"})
        ws.submit({"blueprint": "beat-worker", "name": "beat1"})
        a = ws.build_next()
        b = ws.build_next()
        assert a and a["ok"] and a["attempts"] == 1, a
        assert b and b["ok"] and b["attempts"] == 1, b


@check
def params_inject_into_weave_and_gate():
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        issues = validate_spec({"blueprint": "beat-worker",
                                "params": {"BEATS": "5",
                                           "bad key!": 1}},
                               BLUEPRINTS.keys())
        assert any("param name" in i for i in issues), issues
        ws.submit({"blueprint": "beat-worker", "name": "tuned",
                   "params": {"BEATS": "5"}})
        r = ws.build_next()
        assert r and r["ok"], r
        arts = os.listdir(content.ARTIFACTS_DIR)
        art = os.path.join(content.ARTIFACTS_DIR,
                           [a for a in arts
                            if a.startswith("beat-worker")][0])
        src = open(os.path.join(art, "beat_worker.py"),
                   encoding="utf-8").read()
        assert "BEATS = 5" in src, "param not injected"
        beats = [ln for ln in open(os.path.join(art, "beats.jsonl"),
                                   encoding="utf-8") if ln.strip()]
        assert len(beats) == 5, f"expected 5 beats: {len(beats)}"


@check
def repair_isolates_culprit_with_evidence():
    """cosmetic_doc is innocent; drop_echo is the culprit. The repair
    pass must name the culprit, keep the innocent fault active in the
    sealed artifact, and record telemetry."""
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        ws.submit({"blueprint": "jsonl-echo", "name": "isolate",
                   "faults": ["cosmetic_doc", "drop_echo"],
                   "attempts": 3})
        r = ws.build_next()
        assert r["ok"], r
        assert r.get("culprit") == "drop_echo", r
        assert r["fixed"] is True
        st = ws.status()
        slot = (st["repair_stats"].get("jsonl-echo", {})
                                  .get("drop_echo", {}))
        assert slot.get("repaired") == 1, st["repair_stats"]
        arts = os.listdir(content.ARTIFACTS_DIR)
        art = os.path.join(content.ARTIFACTS_DIR,
                           [x for x in arts
                            if x.startswith("jsonl-echo")][-1])
        src = open(os.path.join(art, "echo_server.py"),
                   encoding="utf-8").read()
        assert "(rewoven)" in src, \
            "innocent suspect must stay active in the artifact"
        assert 'obj["echo"] = True' in src, "culprit was not repaired"


@check
def multi_fault_interaction_restores_all():
    """Two independent breakers cannot be explained by one culprit -
    the repair pass must fall back to restoring everything."""
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        ws.submit({"blueprint": "jsonl-echo", "name": "multi",
                   "faults": ["drop_echo", "silent_start"],
                   "attempts": 3})
        r = ws.build_next()
        assert r["ok"], r
        assert "culprit" not in r, "no single culprit exists here"
        assert r["fixed"] is True and r["attempts"] >= 2, r


# ------------------------------------------------- planning station --

def _brief(**over):
    doc = {"title": "wiring pass 7",
           "intent": "Commission one echo server and close out "
                     "the docs checkpoint for the sprint.",
           "author": "verify-suite",
           "steps": [
               {"kind": "build",
                "spec": {"blueprint": "jsonl-echo"}},
               {"kind": "manual",
                "note": "confirm the artifact digest is recorded"},
           ]}
    doc.update(over)
    return doc


@check
def plan_schema_refuses_garbage():
    from daedalus.planning import validate_plan, PlanError
    names = BLUEPRINTS.keys()
    assert validate_plan(_brief(), names) == []
    bad = _brief(intent="too short")
    assert any("intent" in i for i in validate_plan(bad, names)), bad
    bad = _brief(title="ab")
    assert any("title" in i for i in validate_plan(bad, names)), bad
    bad = _brief(steps=[{"kind": "dance"}])
    assert any("step 0.kind" in i
               for i in validate_plan(bad, names)), bad
    bad = _brief(steps=[{"kind": "build"}])
    assert any("spec object" in i
               for i in validate_plan(bad, names)), bad
    bad = _brief(steps=[{"kind": "build",
                         "spec": {"blueprint": "nope"}}])
    assert any("unknown blueprint" in i
               for i in validate_plan(bad, names)), bad
    # store refuses hard errors outright
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        try:
            ws.plans.submit({"title": "x"})
            raise AssertionError("garbage plan was accepted")
        except PlanError as exc:
            assert "refused" in str(exc), exc


@check
def plan_lifecycle_requires_signoff():
    from daedalus.planning import PlanError
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        st = ws.plans
        pid = st.submit(_brief())["id"]
        assert st.show(pid)["status"] == "draft"
        try:
            st.approve(pid, {})
            raise AssertionError("approved without sign_off")
        except PlanError as exc:
            assert "who" in str(exc) and "how" in str(exc), exc
        st.approve(pid, {"who": "operator", "how": "session"})
        p = st.show(pid)
        assert p["status"] == "approved" \
            and p["sign_off"]["who"] == "operator", p
        try:                       # approve is one-way; no re-run
            st.approve(pid, {"who": "op", "how": "again"})
            raise AssertionError("double approval allowed")
        except PlanError:
            pass
        other = st.submit(_brief(title="reject me"))["id"]
        st.reject(other, "obsolete")
        assert st.show(other)["status"] == "rejected"


@check
def plan_commission_spawns_and_closes_steps():
    import time as _t
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        st = ws.plans
        pid = st.submit(_brief(title="echo commission"))["id"]
        st.approve(pid, {"who": "operator", "how": "session"})
        r = st.commission(pid)
        assert len(r["jobs"]) == 1, r          # one build job spawned
        job_id = r["jobs"][0]["job"]
        p = st.show(pid)
        assert p["status"] == "commissioned", p
        assert p["steps"][0]["job_id"] == job_id, p
        # manual step closes by hand while the build runs its course
        st.step_done(pid, 1, note="digest verified by hand")
        res = None
        deadline = _t.time() + 15
        while _t.time() < deadline:
            if ws.jobs[job_id]["state"] == "done":
                break
            ws.build_next()
            _t.sleep(0.05)
        else:
            raise AssertionError("commissioned build never drained")
        p = st.show(pid)
        assert p["status"] == "done", p
        assert p["steps"][0]["state"] == "closed" \
            and p["steps"][0]["ok"] is True, p


@check
def plan_survives_restart():
    from daedalus.planning import PlanStore
    with sandbox() as hv:
        ws = Workshop(hypervisor=hv, lanes=1)
        st = ws.plans
        pid = st.submit(_brief(title="durable order"))["id"]
        st.approve(pid, {"who": "operator", "how": "session"})
        st2 = PlanStore(content.PLANS_DIR, workshop=None)
        p2 = st2.show(pid)
        assert p2["status"] == "approved", p2
        assert p2["sign_off"]["who"] == "operator", p2
        assert len(p2["steps"]) == 2, p2


@check
def watcher_cannot_approve_or_resize_on_wire():
    from daedalus.server import DaedalusServer
    with sandbox() as hv:
        srv = DaedalusServer(port=0, workshop=Workshop(
            hypervisor=hv, lanes=1))
        srv.start_async()
        try:
            srv.profiles[2] = "watcher"
            r = srv.handle("plan_list", {}, cid=2)
            assert r["error"] is None, r          # reading plans is fine
            r = srv.handle("plan_approve",
                           {"plan_id": "plan-x-000001",
                            "sign_off": {"who": "w", "how": "h"}},
                           cid=2)
            assert "right_denied" in str(r.get("error")), r
            r = srv.handle("fleet_resize", {"lanes": 3}, cid=2)
            assert "right_denied" in str(r.get("error")), r
        finally:
            srv.running = False


@check
def fleet_resize_grows_and_shrinks():
    from daedalus.fleet import SubFleet
    with sandbox() as hv:
        pool = SubFleet(1, hv)
        rep = pool.resize(3)
        assert rep["added"] == ["L2", "L3"] and not rep["retired"], rep
        assert [l.name for l in pool.lanes] == ["L1", "L2", "L3"]
        # busy tail: shrink must wait for it instead of killing work
        pool.lanes[2].take({"blueprint": "jsonl-echo", "id": "hold"})
        rep = pool.resize(1)
        assert rep["retired"] == [] and rep["pending"] == ["L3"], rep
        assert len(pool.lanes) == 3          # still present until reap
        pool.lanes[2].release(True)
        pool.reap_retired()
        assert [l.name for l in pool.lanes] == ["L1", "L2"], \
            pool.snapshot()
        # now the excess is idle: shrink retires it on the spot
        rep = pool.resize(1)
        assert rep["retired"] == ["L2"] and rep["pending"] == [], rep
        assert [l.name for l in pool.lanes] == ["L1"], pool.snapshot()


@check
def resize_respects_the_atlas_ceiling():
    from atlas import content as ac
    from daedalus.fleet import SubFleet
    with sandbox() as hv:
        old = ac.MAX_GUESTS
        ac.MAX_GUESTS = 2
        try:
            pool = SubFleet(1, hv)
            try:
                pool.resize(3)
                raise AssertionError("resize passed the hypervisor cap")
            except ValueError as exc:
                assert "ceiling" in str(exc) or "MAX_GUESTS" in str(exc), \
                    exc
        finally:
            ac.MAX_GUESTS = old


@check
def env_override_sets_lane_count():
    import subprocess
    import sys as _sys
    code = ("import os, sys; os.environ['DAEDALUS_LANES']='3'; "
            f"sys.path.insert(0, {ROOT!r}); "
            "from daedalus import content; "
            "assert content.MAX_CONCURRENT_BUILDS == 3, "
            "content.MAX_CONCURRENT_BUILDS")
    r = subprocess.run([_sys.executable, "-c", code],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])


def main():
    print("=" * 64)
    print("DAEDALUS WORKSHOP GATE - subfleet builds that learn")
    print("=" * 64)
    failures = []
    total_ok = 0
    for fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:              # noqa: BLE001 - gate
            failures.append(fn.__name__)
            print(f"[FAIL] {fn.__name__}: "
                  f"{type(exc).__name__}: {exc}")
    total = len(CHECKS)
    print("-" * 64)
    verdict = f"{total - len(failures)}/{total} checks green"
    print(verdict + ("" if not failures else " - FAILURES PRESENT"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
