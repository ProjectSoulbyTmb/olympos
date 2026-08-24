"""NORN integration gate - the shared machinery, checked in situ.

Covers the pulse SLO engine, capability-rights gating on both wired
realms, witness attestation of mutating verbs, and the generic replay
seeder. Every fixture is a throwaway; nothing here touches live data.

    python norn/verify_norn.py        (exit 0 = all green)
"""

import glob
import importlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from norn.pulse import Pulse                      # noqa: E402
from norn.replay import run_seed_file, write_seed  # noqa: E402
from norn.witness import Witness, WitnessSDK      # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def _purge_content_module():
    """Vulcan and Zeus both ship top-level 'content' and 'sdk' modules
    (L020): purge them between realm imports or the second realm
    silently gets the first one's tables."""
    for name in ("content", "sdk"):
        sys.modules.pop(name, None)
    importlib.invalidate_caches()


# ------------------------------------------------------------ pulse core

@check
def pulse_slo_quarantine_and_revival():
    now = {"t": 0.0}
    p = Pulse(name="gate", beat_s=1.0, now_fn=lambda: now["t"])

    def slow():
        now["t"] += 0.05
    p.add_organ("slow", slow, slo_max_ms=5.0,
                slo_max_late=2, revive_after=2)
    p.beat()
    p.beat()
    o = p.organs["slow"]
    assert o.state == "quarantined", o.snapshot()
    assert "slo breach" in o.quarantine_reason
    assert p.vitals()["organs"]["slow"]["late_ratio"] == 1.0
    p.beat()
    p.beat()
    assert o.state == "alive" and o.consecutive_late == 0


# ------------------------------------------------- vulcan: pulse+witness

@check
def vulcan_pulse_vitals_in_state():
    vdir = os.path.join(ROOT, "vulcan")
    sys.path.insert(0, vdir)
    try:
        import host as vhost
        srv = vhost.BuildingServer(port=0, auto_tick=False)
        srv.beat_once()
        srv.beat_once()
        organ = srv.world.pulse.organs["world_tick"]
        assert organ.runs == 2, organ.snapshot()
        st = srv.sdk.state()
        blk = st["building"]["pulse"]
        assert blk["organs"]["world_tick"]["runs"] == 2, blk
        assert "late_ratio" in blk["organs"]["world_tick"]
    finally:
        sys.path.remove(vdir)
        _purge_content_module()


@check
def vulcan_rights_gate_and_witness():
    tmp = tempfile.mkdtemp(prefix="norn-vulcan-")
    wdir = os.path.join(tmp, "witness")
    vdir = os.path.join(ROOT, "vulcan")
    sys.path.insert(0, vdir)
    try:
        import host as vhost
        srv = vhost.BuildingServer(port=0, auto_tick=False)
        srv.witness = Witness(wdir, actor="gate_vulcan", keep=5)
        # operator (default): mutating verb allowed + journalled
        r1 = srv.handle("tick", {"n": 1}, cid=7)
        assert r1["error"] is None, r1
        # watcher: narrowing only - mutating verb refused
        srv.profiles[8] = "watcher"
        r2 = srv.handle("tick", {"n": 1}, cid=8)
        assert "right_denied" in str(r2.get("error")), r2
        lines = [json.loads(l) for l in open(
            glob.glob(os.path.join(wdir, "*.jsonl"))[0],
            encoding="utf-8")]
        assert any(e["verb"] == "tick" and e["ok"] for e in lines), lines
        assert not any(e["verb"] == "state" for e in lines), \
            "info verbs must not be journalled"
    finally:
        sys.path.remove(vdir)
        _purge_content_module()
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------- zeus: rights+pulse

@check
def zeus_rights_gate_and_pulse():
    tmp = tempfile.mkdtemp(prefix="norn-zeus-")
    zdir = os.path.join(ROOT, "zeus")
    sys.path.insert(0, zdir)
    os.environ["NORN_WITNESS_DIR"] = os.path.join(tmp, "witness")
    try:
        import kernel as zkernel
        import server as zserver
        with zkernel.sandbox(os.path.join(tmp, "ws")) as k:
            srv = zserver.ZeusServer(port=0, auto_patrol=False, kernel=k)
            # operator default: info verb fine
            r1 = srv.handle("status", {}, cid=1)
            assert r1["error"] is None, r1
            # watcher: high-stakes mutation refused
            srv.profiles[2] = "watcher"
            r2 = srv.handle("policy_set",
                            {"key": "CPU_SOFT_PCT", "value": 50},
                            cid=2)
            assert "right_denied" in str(r2.get("error")), r2
            # pulse: one tick == one patrol beat, vitals ride status
            k.tick()
            assert k.pulse is not None, "pulse missing on kernel"
            assert k.pulse.organs["patrol"].runs == 1
            st = k.status()
            assert st["pulse"]["organs"]["patrol"]["runs"] == 1, st
    finally:
        os.environ.pop("NORN_WITNESS_DIR", None)
        sys.path.remove(zdir)
        _purge_content_module()
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------ witness internals

class _StubWorld:
    def __init__(self):
        self.tick = 3
        self.xp = {"woodcutting": 100.0}
        self.coins = 50

    def save(self):
        return {"tick": self.tick, "coins": self.coins}


@check
def witness_records_deltas():
    tmp = tempfile.mkdtemp(prefix="norn-wit-")
    try:
        w = _StubWorld()
        wit = Witness(tmp, actor="gate_wit", world=w, keep=2)

        class FakeSDK:
            def chop(self):
                w.xp["woodcutting"] += 25
                return "ok"

        g = WitnessSDK(FakeSDK(), wit, actor="gate_wit")
        g.chop()
        assert wit.entries == 1
        line = json.loads(open(wit.path, encoding="utf-8").read())
        assert line["xp_delta"] == 25 and line["ok"], line
        assert line["tick"] == 3
        wit.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------- generic replay

class _ReplayWorld:
    def __init__(self, seed):
        self.seed = seed
        self.n = 0

    def advance(self):
        self.n += 1 + (self.seed % 3)

    def save(self):
        return {"seed": self.seed, "n": self.n}


class _ReplaySDK:
    def __init__(self, world):
        self.world = world

    def tick(self, times=1):
        for _ in range(times):
            self.world.advance()


@check
def replay_seed_roundtrip_and_divergence():
    tmp = tempfile.mkdtemp(prefix="norn-replay-")
    try:
        seed_path = os.path.join(tmp, "stub.jsonl")

        def factory(seed):
            w = _ReplayWorld(seed)
            return w, _ReplaySDK(w)

        write_seed(seed_path, seed=4, world_factory=factory,
                   script=lambda w, s: s.tick(3),
                   note="stub scenario")
        note = run_seed_file(seed_path, world_factory=factory)
        assert note == "stub scenario"

        def other_factory(_seed):     # same script, different seed
            return factory(5)
        diverged = False
        try:
            run_seed_file(seed_path, world_factory=other_factory)
        except AssertionError:
            diverged = True
        assert diverged, "different seed must not replay identically"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=" * 64)
    print("NORN INTEGRATION GATE - rights, witness, pulse, replay")
    print("=" * 64)
    failures = []
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
    print(f"{total - len(failures)}/{total} checks green"
          + ("" if not failures else " - FAILURES PRESENT"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
