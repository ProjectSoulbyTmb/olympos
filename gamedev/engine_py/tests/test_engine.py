import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine_py import (  # noqa: E402
    EventBus,
    FakeClock,
    GameLoop,
    InvalidTransition,
    Node,
    RNG,
    Recorder,
    ReplayRunner,
    Scene,
    StateMachine,
    World,
    check_deterministic,
    snapshot,
    state_hash,
)


class TestRNG(unittest.TestCase):
    def test_deterministic_sequence(self):
        a = [RNG(7).random() for _ in range(1)]
        r1, r2 = RNG(42), RNG(42)
        self.assertEqual([r1.randint(0, 99) for _ in range(20)],
                         [r2.randint(0, 99) for _ in range(20)])

    def test_derive_stable_and_independent(self):
        r = RNG(5)
        c1a, c1b = r.derive("combat"), r.derive("loot")
        self.assertEqual(c1a.random(), RNG(5).derive("combat").random())
        self.assertNotEqual(c1a.random(), c1b.random())

    def test_state_hash_stable(self):
        obj = {"b": 1, "a": [1, 2]}
        self.assertEqual(state_hash(obj), state_hash({"a": [1, 2], "b": 1}))


class TestWorld(unittest.TestCase):
    def test_spawn_query_destroy(self):
        w = World()
        e1 = w.spawn(pos=[0, 0], vel=[1, 1])
        e2 = w.spawn(pos=[5, 5])
        got = list(w.query("pos", "vel"))
        self.assertEqual(got, [(e1, ([0, 0], [1, 1]))])
        w.destroy(e1)
        self.assertFalse(w.alive(e1))
        self.assertIsNone(w.get(e1, "pos"))
        self.assertEqual(list(w.query("pos")), [(e2, ([5, 5],))])

    def test_set_on_dead_entity_raises(self):
        w = World()
        e = w.spawn()
        w.destroy(e)
        with self.assertRaises(KeyError):
            w.set(e, "hp", 3)

    def test_systems_step_in_order(self):
        w = World()
        order = []
        w.add_system(lambda world, dt: order.append("a"))
        w.add_system(lambda world, dt: order.append("b"))
        w.step()
        self.assertEqual(order, ["a", "b"])

    def test_snapshot_shape(self):
        w = World()
        e = w.spawn(pos=[1, 2])
        snap = snapshot(w, ["pos"])
        self.assertEqual(snap["entities"][e], {"pos": [1, 2]})


class TestGameLoop(unittest.TestCase):
    def test_fixed_timestep_accumulation_with_fake_clock(self):
        clock = FakeClock(step=1 / 30)
        loop = GameLoop(tick_rate=60.0, clock=clock)
        ticks = []
        loop.run(tick=lambda dt: ticks.append(round(dt, 6)), stop=lambda: len(ticks) >= 4)
        for dt in ticks:
            self.assertAlmostEqual(dt, 1 / 60, places=6)

    def test_catchup_clamp(self):
        class BurstClock:
            def __init__(self):
                self.calls = -1

            def __call__(self):
                self.calls += 1
                return 0 if self.calls == 0 else 10.0

        loop = GameLoop(tick_rate=10.0, max_catchup=3, clock=BurstClock())
        ticks = []
        loop.run(tick=lambda dt: ticks.append(dt), stop=lambda: len(ticks) >= 3)
        self.assertEqual(len(ticks), 3)
        self.assertAlmostEqual(sum(ticks), 0.3, places=9)

    def test_manual_stepping_counts(self):
        loop = GameLoop(tick_rate=50.0)
        n = []
        loop.step_ticks(7, lambda dt: n.append(dt))
        self.assertEqual(loop.tick_count, 7)


class TestStateMachine(unittest.TestCase):
    def states(self):
        return {
            "idle": {"on_enter": lambda p: log.append(("enter_idle", p)),
                     "on_update": lambda dt: "scan"},
            "chase": {"on_enter": lambda p: log.append(("enter_chase", p))},
        }

    def setUp(self):
        global log
        log = []

    def test_valid_transition_fires_callbacks(self):
        sm = StateMachine(
            self.states(),
            {("idle", "see_player"): ("chase", None)},
            "idle",
        )
        self.assertEqual(sm.update(0.1), "scan")
        self.assertEqual(sm.fire("see_player"), "chase")
        self.assertEqual(log, [("enter_idle", None), ("enter_chase", None)])
        self.assertEqual([e[0] for e in sm.log], ["enter", "exit", "enter"])

    def test_invalid_transition_rejected_loudly(self):
        sm = StateMachine(self.states(), {}, "idle")
        with self.assertRaises(InvalidTransition):
            sm.fire("nonexistent")

    def test_guard_rejection(self):
        transitions = {
            ("idle", "open"): ("chase", lambda p: p == "key"),
        }
        sm = StateMachine(self.states(), transitions, "idle")
        with self.assertRaises(InvalidTransition):
            sm.fire("open", "wrong")
        sm.fire("open", "key")
        self.assertEqual(sm.state, "chase")


class TestEvents(unittest.TestCase):
    def test_on_emit_off(self):
        bus = EventBus()
        seen = []
        fn = lambda p: seen.append(p)  # noqa: E731
        bus.on("hit", fn)
        bus.emit("hit", 5)
        bus.off("hit", fn)
        bus.emit("hit", 6)
        self.assertEqual(seen, [5])

    def test_unknown_topic_noop(self):
        bus = EventBus()
        bus.emit("nothing")
        self.assertEqual(bus.subscriber_count("nothing"), 0)


class TestScene(unittest.TestCase):
    def test_update_traversal_parent_then_children(self):
        scene = Scene("root")
        scene.root.update_fn = lambda dt: order.append("root")
        order = []

        def mk(name):
            return Node(name, update_fn=lambda dt, n=name: order.append(n))

        scene.root.add(mk("a")).add(mk("a1"))
        scene.root.add(mk("b"))
        scene.update(0.01)
        self.assertEqual(order, ["root", "a", "a1", "b"])

    def test_find_and_path(self):
        scene = Scene("root")
        a = scene.root.add(Node("a"))
        a.add(Node("leaf"))
        self.assertIsNotNone(scene.root.find("leaf"))
        leaf = scene.root.find("leaf")
        self.assertEqual(leaf.path(), "root/a/leaf")

    def test_add_to_missing_parent_raises(self):
        scene = Scene("root")
        with self.assertRaises(KeyError):
            scene.add("ghost", Node("x"))


def make_counter_game():
    state = {"n": 0}

    def apply_tick(inputs):
        state["n"] += len(inputs)

    return apply_tick, lambda: state["n"]


class TestReplay(unittest.TestCase):
    def test_record_build_validates(self):
        rec = Recorder(seed=3, game_name="counter")
        rec.push(["inc"])
        rec.push([])
        rep = rec.build()
        self.assertEqual(rep["ticks"][0]["inputs"], ["inc"])
        self.assertEqual([t["t"] for t in rep["ticks"]], [0, 1])

    def test_runner_replays_to_same_state(self):
        rec = Recorder(seed=3, game_name="counter")
        for _ in range(5):
            rec.push(["inc"])
        rep = rec.build()

        def factory():
            return make_counter_game()

        hashes = ReplayRunner(rep, factory).run(collect=True)
        self.assertEqual(hashes[-1], 5)

    def test_roundtrip_file(self):
        rec = Recorder(seed=9, game_name="counter")
        rec.push(["inc"])
        rep = rec.build()
        with tempfile.TemporaryDirectory() as td:
            p = str(Path(td) / "r.json")
            from engine_py.replay import save_replay_file, load_replay_file

            save_replay_file(rep, p)
            self.assertEqual(load_replay_file(p), rep)

    def test_check_deterministic(self):
        ok, first = check_deterministic(lambda: state_hash({"x": 1}), runs=3)
        self.assertTrue(ok)
        self.assertEqual(first, state_hash({"x": 1}))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    )
    sys.exit(0 if result.wasSuccessful() else 1)
