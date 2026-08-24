import argparse

from engine_py import (
    RNG,
    GameLoop,
    World,
    snapshot,
    state_hash,
    Recorder,
    ReplayRunner,
)


def build_bounce_world(seed, width=100, height=60):
    rng = RNG(seed)
    world = World()
    world.tags.add(f"seed:{seed}")
    movers = []
    for i in range(8):
        eid = world.spawn(
            pos=[rng.uniform(0, width), rng.uniform(0, height)],
            vel=[rng.uniform(-20, 20), rng.uniform(-20, 20)],
        )
        movers.append(eid)

    def integrate(w, dt):
        for eid, (pos, vel) in w.query("pos", "vel"):
            pos[0] += vel[0] * dt
            pos[1] += vel[1] * dt
            for axis in (0, 1):
                limit = width if axis == 0 else height
                if not 0 <= pos[axis] <= limit:
                    pos[axis] = max(0, min(limit, pos[axis]))
                    vel[axis] = -vel[axis]

    world.add_system(integrate)
    return world, movers


def run_demo_ticks(seed=1234, ticks=300):
    loop = GameLoop(tick_rate=60.0)
    world, _ = build_bounce_world(seed)
    loop.step_ticks(ticks, lambda dt: world.step(dt))
    snap = snapshot(world, ["pos", "vel"])
    snap["tags"] = sorted(world.tags)
    return state_hash(snap)


def demo():
    h1 = run_demo_ticks()
    h2 = run_demo_ticks()
    print(f"bounce sim hash: {h1}")
    print(f"determinism: {'OK' if h1 == h2 else 'FAILED'}")
    return h1 == h2


def replay_demo(path):
    recorder = Recorder(seed=99, game_name="bounce")
    inputs_pool = ["nudge"]
    world, movers = build_bounce_world(99)

    def tick(inputs):
        recorder.push(inputs)
        if "nudge" in inputs and movers:
            vel = world.get(movers[0], "vel")
            vel[1] -= 5.0
        world.step(1 / 60)

    loop = GameLoop(tick_rate=60.0)
    loop.step_ticks(120, lambda dt: tick([]))
    loop.step_ticks(10, lambda dt: tick(inputs_pool))
    loop.step_ticks(120, lambda dt: tick([]))
    live_hash = state_hash(snapshot(world, ["pos", "vel"]))

    replay = recorder.build()
    import json
    import os

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(replay, f)

    def factory():
        w2, m2 = build_bounce_world(99)
        state = {"movers": m2}

        def apply_tick(inputs):
            if "nudge" in inputs and state["movers"]:
                v = w2.get(state["movers"][0], "vel")
                v[1] -= 5.0
            w2.step(1 / 60)

        return apply_tick, lambda: state_hash(snapshot(w2, ["pos", "vel"]))

    runner = ReplayRunner(replay, factory)
    replayed_hash = runner.run()
    print(f"live hash:   {live_hash}")
    print(f"replay hash: {replayed_hash}")
    ok = live_hash == replayed_hash
    print(f"replay match: {'OK' if ok else 'FAILED'}")
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(prog="engine_py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    rp = sub.add_parser("replay")
    rp.add_argument("--out", default="out/bounce.replay.json")
    args = parser.parse_args(argv)
    if args.cmd == "demo":
        raise SystemExit(0 if demo() else 1)
    if args.cmd == "replay":
        raise SystemExit(0 if replay_demo(args.out) else 1)


if __name__ == "__main__":
    main()
