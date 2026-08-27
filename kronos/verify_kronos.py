"""KRONOS gate - proves the governor holds, releases, and recovers.

Every scenario runs against a throwaway root under the system temp
dir with a fake task controller; the real workspace is only read for
imports. One check samples real memory (this gate is Windows-born).

Run:  python kronos/verify_kronos.py
Exit: 0 green, 1 failures.
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from kronos import content as C        # noqa: E402
from kronos import kernel              # noqa: E402
from kronos.kernel import Governor, TaskController, ram_sample  # noqa: E402

CHECKS = []
FAILS = []


def check(fn):
    CHECKS.append(fn)
    return fn


class FakeController:
    """In-memory stand-in for TaskScheduler."""

    def __init__(self, missing=()):
        self.missing = set(missing)
        self.stopped = []
        self.started = []
        self.running = set(C.MANAGED_TASKS)

    def stop(self, name):
        if name in self.missing:
            return False
        self.stopped.append(name)
        self.running.discard(name)
        return True

    def start(self, name):
        if name in self.missing:
            return False
        self.started.append(name)
        self.running.add(name)
        return True

    def query(self, name):
        if name in self.running:
            return "Running"
        if name in C.MANAGED_TASKS:
            return "Ready"          # registered, verifiably not running
        return None                 # unregistered/unknown


class Fixture:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="kronos-gate-")

    def paths(self):
        return kernel.data_paths(self.root)

    def write_journal(self, holding, held):
        p = self.paths()
        os.makedirs(p["dir"], exist_ok=True)
        with open(p["state"], "w", encoding="utf-8") as fh:
            json.dump({"holding": holding, "held": held,
                       "planned": [], "pid": 0,
                       "ts": "2026-08-25T00:00:00"}, fh)

    def journal(self):
        return kernel._read_journal(self.paths())

    def events(self):
        p = self.paths()
        with open(p["events"], encoding="utf-8") as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


# ------------------------------------------------------------- tests

@check
def manifest_never_touches_zeus():
    assert C.FORBIDDEN_MARKERS, "no forbidden markers defined"
    for task in C.MANAGED_TASKS:
        low = task.lower()
        for marker in C.FORBIDDEN_MARKERS:
            assert marker not in low, \
                "managed list may never hold %r (%s)" % (task, marker)


@check
def controller_vetoes_zeus_even_if_listed():
    """The governor runs elevated, so the veto must be code law:
    the controller itself refuses ZEUS-named tasks, whatever a
    future edit does to the manifest."""
    fx = Fixture()
    try:
        ctrl = TaskController(dry_run=True)
        assert ctrl.stop("Olympos ZEUS Guardian") is False
        assert ctrl.start("Yggdrasil ZEUS Guardian") is False
        assert ctrl.refused == [("stop", "Olympos ZEUS Guardian"),
                                ("start", "Yggdrasil ZEUS Guardian")]
        assert not ctrl.actions, "vetoed calls must not reach scheduler"
        original = C.MANAGED_TASKS
        try:
            C.MANAGED_TASKS = tuple(original) + ("Olympos ZEUS Guardian",)
            g = Governor(controller=ctrl, root=fx.root)
            row = g.do_hold()
            assert "Olympos ZEUS Guardian" not in row["held"], row
            assert all(t != "Olympos ZEUS Guardian"
                       for _, t in ctrl.actions), ctrl.actions
        finally:
            C.MANAGED_TASKS = tuple(original)
    finally:
        fx.cleanup()


@check
def sampler_reports_sane_memory():
    s = ram_sample()
    assert 0 <= s["load_pct"] <= 100, s
    assert s["total_bytes"] > 0 and s["avail_bytes"] >= 0, s
    assert s["avail_bytes"] <= s["total_bytes"], s


@check
def hold_needs_sustained_strain():
    fx = Fixture()
    try:
        ctrl = FakeController()
        g = Governor(controller=ctrl, root=fx.root)
        r1 = g.step(C.HOLD_PCT + 1)
        assert r1["action"] == "watch", r1
        r2 = g.step(C.HOLD_PCT + 1)
        assert r2["action"] == "watch", r2
        assert not ctrl.stopped, "held before HOLD_SAMPLES"
        r3 = g.step(C.HOLD_PCT + 5)
        assert r3["action"] == "hold", r3
        assert ctrl.stopped == list(C.MANAGED_TASKS), ctrl.stopped
        assert r3["held"] == list(C.MANAGED_TASKS), r3
        j = fx.journal()
        assert j["holding"] is True and j["held"], j
    finally:
        fx.cleanup()


@check
def calm_release_and_hysteresis_band():
    fx = Fixture()
    try:
        g = Governor(controller=FakeController(), root=fx.root)
        g.do_hold()
        for _ in range(C.RELEASE_SAMPLES - 1):
            row = g.step(C.RELEASE_PCT - 1)
            assert row["action"] == "holding", row
        row = g.step(0)
        assert row["action"] == "release", row
        # deadband between the lines resets both streaks: no flapping
        mid = (C.RELEASE_PCT + C.HOLD_PCT) // 2
        assert g.step(mid)["action"] == "watch"
        assert g.over_streak == 0 and g.under_streak == 0
    finally:
        fx.cleanup()


@check
def deadband_resets_a_brewing_streak():
    fx = Fixture()
    try:
        g = Governor(controller=FakeController(), root=fx.root)
        mid = (C.RELEASE_PCT + C.HOLD_PCT) // 2
        seq = [C.HOLD_PCT + 1] * (C.HOLD_SAMPLES - 1) \
            + [mid] + [C.HOLD_PCT + 1] * (C.HOLD_SAMPLES - 1)
        actions = [g.step(v)["action"] for v in seq]
        assert "hold" not in actions, actions
        third = g.step(C.HOLD_PCT + 1)
        assert third["action"] == "hold", third
    finally:
        fx.cleanup()


@check
def crash_mid_hold_recovers_on_boot():
    fx = Fixture()
    try:
        survivor = "Olympos GAIA Pulse"
        fx.write_journal(holding=True, held=[survivor])
        ctrl = FakeController()
        ctrl.running.discard(survivor)   # it really was stopped
        g = Governor(controller=ctrl, root=fx.root)
        assert g.recover() == [survivor]
        assert g.holding and g.held == [survivor]
        for _ in range(C.RELEASE_SAMPLES - 1):
            assert g.step(10)["action"] == "holding"
        row = g.step(10)
        assert row["action"] == "release" \
            and row["resumed"] == [survivor], row
        j = fx.journal()
        assert j["holding"] is False and j["held"] == [], j
    finally:
        fx.cleanup()


@check
def phantom_hold_is_dropped_not_adopted():
    """A journal claiming a hold that never landed (crash before the
    stops) must not be adopted as truth - else the phantom blocks all
    future real holds."""
    fx = Fixture()
    try:
        ghost = "Olympos HYPNOS Dreamworker"
        fx.write_journal(holding=True, held=[ghost])
        ctrl = FakeController()          # ghost still running
        g = Governor(controller=ctrl, root=fx.root)
        assert g.recover() == [], "phantom hold adopted"
        assert g.holding and g.held == []
        row = g.do_hold(90)              # and a real hold still works
        assert ghost in row["held"], row
    finally:
        fx.cleanup()


@check
def missing_tasks_are_skipped_not_fatal():
    fx = Fixture()
    try:
        ghost = "Olympos HEBE Scribe"
        ctrl = FakeController(missing={ghost})
        g = Governor(controller=ctrl, root=fx.root)
        row = g.do_hold()
        assert ghost not in row["held"], row
        assert row["held"] == \
            [t for t in C.MANAGED_TASKS if t != ghost], row
        rel = g.do_release()
        assert ghost not in rel["resumed"], rel
        assert rel["missed"] == [], rel
    finally:
        fx.cleanup()


@check
def dry_run_never_invokes_powershell():
    fx = Fixture()
    try:
        def forbidden(*a, **kw):
            raise AssertionError("dry-run called a real process")

        real_run = kernel.subprocess.run
        kernel.subprocess.run = forbidden
        try:
            ctrl = TaskController(dry_run=True)
            g = Governor(controller=ctrl, root=fx.root)
            g.step(C.HOLD_PCT + 1), g.step(C.HOLD_PCT + 1)
            assert g.step(C.HOLD_PCT + 1)["action"] == "hold"
            assert len(ctrl.actions) == len(C.MANAGED_TASKS)
            for _ in range(C.RELEASE_SAMPLES):
                g.step(0)
            assert ("start", C.MANAGED_TASKS[0]) in ctrl.actions
        finally:
            kernel.subprocess.run = real_run
    finally:
        fx.cleanup()


@check
def event_log_is_jsonl_with_transitions():
    fx = Fixture()
    try:
        g = Governor(controller=FakeController(), root=fx.root)
        for _ in range(C.HOLD_SAMPLES):
            g.step(C.HOLD_PCT + 1)
        for _ in range(C.RELEASE_SAMPLES):
            g.step(5)
        rows = fx.events()
        kinds = {r["kind"] for r in rows}
        assert {"hold", "release"} <= kinds, kinds
        assert all("ts" in r for r in rows)
    finally:
        fx.cleanup()


@check
def bus_never_blocks_the_governor():
    """A dead or hostile nervous system must not stop the organ:
    publish/beat raising still yields clean holds and releases."""
    fx = Fixture()
    try:
        class HostileBus:
            def publish(self, *a, **kw):
                raise OSError("bus down")

            class Post:
                def beat(self, *a, **kw):
                    raise OSError("bus down")

        real_bus = kernel._bus
        kernel._bus = lambda: HostileBus()
        try:
            g = Governor(controller=FakeController(), root=fx.root)
            for _ in range(C.HOLD_SAMPLES):
                row = g.step(C.HOLD_PCT + 1)
            assert row["action"] == "hold", row
            for _ in range(C.RELEASE_SAMPLES):
                row = g.step(5)
            assert row["action"] == "release", row
        finally:
            kernel._bus = real_bus
    finally:
        fx.cleanup()


@check
def spawns_are_windowless():
    """Real-mode controller must pass CREATE_NO_WINDOW so the
    governor never flashes consoles at the operator."""
    fx = Fixture()
    try:
        captured = []

        def spy(argv, **kw):
            captured.append(kw)

            class R:
                returncode = 0
                stdout = ""
                stderr = ""
            return R()

        real_run = kernel.subprocess.run
        kernel.subprocess.run = spy
        try:
            ctrl = TaskController(dry_run=False)
            assert ctrl.stop(C.MANAGED_TASKS[0]) is True
            ctrl.query(C.MANAGED_TASKS[0])
        finally:
            kernel.subprocess.run = real_run
        assert len(captured) == 2, captured
        flags = getattr(kernel.subprocess, "CREATE_NO_WINDOW", 0)
        assert all(k.get("creationflags") == flags
                   for k in captured), \
            "spawns are not windowless: %r" % (captured,)
    finally:
        fx.cleanup()


def main():
    print("=" * 64)
    print("KRONOS GATE - hold under strain, release in calm, "
          "never touch ZEUS")
    print("=" * 64)
    for fn in CHECKS:
        try:
            fn()
            print("[PASS] %s" % fn.__name__)
        except AssertionError as exc:
            FAILS.append(fn.__name__)
            print("[FAIL] %s: %s" % (fn.__name__, exc))
        except Exception as exc:              # noqa: BLE001 - gate
            FAILS.append(fn.__name__)
            print("[FAIL] %s: %s: %s"
                  % (fn.__name__, type(exc).__name__, exc))
    total = len(CHECKS)
    print("-" * 64)
    print("%d/%d checks green" % (total - len(FAILS), total))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
