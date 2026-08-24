import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(HERE, "osrs-llm-agent")
RL = os.path.join(HERE, "osrs-rl")
sys.path.insert(0, AGENT)

results = []


def bench(name, fn):
    val, detail = fn()
    results.append((name, val, detail))
    print(f"  {name:<34} {val:>12}  {detail}")


def b_sim_ticks():
    from game.world import World
    from game.sdk import GameSDK
    w = World(tick_budget=30000)
    g = GameSDK(w)
    t0 = time.perf_counter()
    while w.ticks_left > 100:
        try:
            g.walk("tree_1")
            g.chop()
        except Exception:
            g.walk("bank")
            g.deposit_all()
    dt = time.perf_counter() - t0
    return f"{w.tick / dt:,.0f} ticks/s", f"{w.tick} ticks in {dt:.2f}s"


def b_rl_collectors():
    os.chdir(RL)
    sys.path.insert(0, RL)
    import torch
    torch.set_num_threads(1)
    from algo.networks import ActorCritic
    from envs.osrs_sim import OsrsPvpEnv, N_ACTIONS, OBS_DIM
    from train import collect_batched, play_episode, OpponentPool
    device = torch.device("cpu")
    policy = ActorCritic(OBS_DIM, N_ACTIONS)
    pool = OpponentPool(device)

    def legacy():
        env = OsrsPvpEnv(seed=1)
        t0 = time.perf_counter()
        eps = 0
        while time.perf_counter() - t0 < 4:
            play_episode(env, policy, RandomOpp(), device)
            eps += 1
        dt = time.perf_counter() - t0
        ticks = eps * 200
        return ticks / dt

    class RandomOpp:
        def __init__(self):
            from envs.osrs_sim import RandomBot
            self.bot = None

        def act(self, obs, mask):
            if self.bot is None:
                from envs.osrs_sim import RandomBot
                self.bot = RandomBot(7)
            return self.bot.act(obs, mask)

    leg = legacy()

    envs = [OsrsPvpEnv(seed=100 + i) for i in range(16)]
    t0 = time.perf_counter()
    eps = 0
    while time.perf_counter() - t0 < 4:
        collect_batched(envs, policy, pool, target_episodes=16,
                        seed_base=int(time.time()))
        eps += 16
    dt = time.perf_counter() - t0
    fast = eps * 200 / dt
    return f"{fast / max(leg, 1):.1f}x", \
        f"legacy {leg:,.0f} vs batched {fast:,.0f} tick-steps/s"


class RandomOpp:
    pass


def b_rsps_rtt():
    from server.rsps_server import GameServer, DEFAULT_PORT
    from server.client import RemoteGameSDK
    port = 43977
    srv = GameServer(port=port)
    srv.start_async()
    time.sleep(0.5)
    try:
        g = RemoteGameSDK(name="bench", port=port)
        lat = []
        for _ in range(300):
            t0 = time.perf_counter()
            g.state()
            lat.append((time.perf_counter() - t0) * 1000)
            time.sleep(0.012)   # stay under the server's 100 req/s cap
        med = statistics.median(lat)
        g.close()
        return f"{med:.2f} ms", f"median of 300 state round-trips"
    finally:
        srv.stop()


print("=" * 66)
print("OSRS LAB PERFORMANCE BENCHMARK")
print("=" * 66)

bench("sim engine throughput", b_sim_ticks)
bench("RL collector speedup (batched)", b_rl_collectors)
bench("RSPS socket round-trip", b_rsps_rtt)

print("=" * 66)
