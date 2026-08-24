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
               ("DATA_DIR", "AUDIT_PATH", "ARTIFACTS_DIR")}
    saved_a = {"GUESTS_DIR": ac.GUESTS_DIR}
    saved_env = os.environ.get("RATATOSK_ROOT")
    data = os.path.join(outer, "data")
    content.DATA_DIR = data
    content.AUDIT_PATH = os.path.join(data, "audit.jsonl")
    content.ARTIFACTS_DIR = os.path.join(data, "artifacts")
    ac.GUESTS_DIR = os.path.join(outer, "guests")
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
