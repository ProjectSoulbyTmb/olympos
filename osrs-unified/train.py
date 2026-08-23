import argparse
import copy
import csv
import os
import time

import numpy as np
import torch

from algo.networks import ActorCritic
from algo.ppo import PPOBuffer, ppo_update
from envs.osrs_sim import OsrsPvpEnv, N_ACTIONS, OBS_DIM, RandomBot


class OpponentPool:
    def __init__(self, device):
        self.device = device
        self.nets = []

    def add(self, policy):
        clone = ActorCritic(OBS_DIM, N_ACTIONS).to(self.device)
        clone.load_state_dict(copy.deepcopy(policy.state_dict()))
        clone.eval()
        for p in clone.parameters():
            p.requires_grad_(False)
        self.nets.append(clone)

    def sample(self):
        if not self.nets:
            return RandomBot(int(time.time()))
        return self.nets[int(np.random.randint(len(self.nets)))]

    def trim(self, cap):
        while len(self.nets) > cap:
            self.nets.pop(int(np.random.randint(len(self.nets))))


def opponent_action(opponent, obs, mask):
    result = opponent.act(torch.from_numpy(obs), torch.from_numpy(mask))
    return result[0] if isinstance(result, tuple) else result


def play_episode(env, policy, opponent, device):
    obs_a, obs_b = env.reset()
    buf = PPOBuffer()
    buf.start_episode()
    total_r, outcome, ticks = 0.0, 0, 0
    done = False
    while not done:
        mask_a, mask_b = env.legal_mask()
        act, logp, val = policy.act(
            torch.from_numpy(obs_a), torch.from_numpy(mask_a)
        )
        opp_act = opponent_action(opponent, obs_b, mask_b)
        next_a, next_b, r_a, r_b, outcome, done = env.step(act, opp_act)
        buf.store(obs_a, act, logp, r_a, val, mask_a)
        total_r += r_a
        obs_a, obs_b = next_a, next_b
        ticks += 1
    buf.finish_episode()
    return buf, outcome, total_r, ticks


def collect_batched(envs, policy, pool, target_episodes, seed_base=0):
    slots = len(envs)
    bufs = [PPOBuffer() for _ in range(slots)]
    for b in bufs:
        b.start_episode()
    obs_pairs = [env.reset() for env in envs]
    opps = [_new_opponent(pool, seed_base, i) for i in range(slots)]
    wins = losses = draws = tot_r = tot_ticks = 0
    completed = 0

    def fresh_slot(i):
        obs_pairs[i] = envs[i].reset()
        opps[i] = _new_opponent(pool, seed_base, i + 7919)

    while completed < target_episodes:
        opp_actions = [None] * slots
        by_net = {}
        for i in range(slots):
            _, mask_b = envs[i].legal_mask()
            ob = opps[i]
            if isinstance(ob, ActorCritic):
                by_net.setdefault(id(ob), (ob, []))[1].append(i)
            else:
                opp_actions[i] = int(ob.act(obs_pairs[i][1], mask_b))
        for net, members in by_net.values():
            o = torch.from_numpy(
                np.stack([obs_pairs[i][1] for i in members])).float()
            m = torch.from_numpy(
                np.stack([envs[i].legal_mask()[1] for i in members]))
            acts, _, _ = net.act_batch(o, m)
            for j, i in enumerate(members):
                opp_actions[i] = int(acts[j])

        o_t = torch.from_numpy(
            np.stack([obs_pairs[i][0] for i in range(slots)])).float()
        m_t = torch.from_numpy(
            np.stack([envs[i].legal_mask()[0] for i in range(slots)]))
        acts_t, logp_t, val_t = policy.act_batch(o_t, m_t)
        actions = acts_t.tolist()
        logps = logp_t.tolist()
        values = val_t.tolist()

        for i in range(slots):
            env = envs[i]
            mask_a, _ = env.legal_mask()
            next_a, next_b, r_a, _, outcome, d = env.step(actions[i],
                                                          opp_actions[i])
            bufs[i].store(obs_pairs[i][0], actions[i], logps[i], r_a,
                          values[i], mask_a)
            tot_r += r_a
            tot_ticks += 1
            if d:
                wins += outcome == 1
                losses += outcome == 2
                draws += outcome in (3, 4)
                bufs[i].finish_episode()
                completed += 1
                fresh_slot(i)
            else:
                obs_pairs[i] = (next_a, next_b)

    merged = PPOBuffer()
    for b in bufs:
        offset = len(merged.obs)
        merged.obs.extend(b.obs)
        merged.acts.extend(b.acts)
        merged.logp.extend(b.logp)
        merged.rew.extend(b.rew)
        merged.val.extend(b.val)
        merged.mask.extend(b.mask)
        for s0, s1 in b.episodes:
            merged.episodes.append((offset + s0, offset + s1))
    avg_r = tot_r / max(1, target_episodes)
    return merged, wins, losses, draws, avg_r, tot_ticks / max(2, slots)


def _new_opponent(pool, seed_base, i):
    return pool.sample() if np.random.random() < 0.8 \
        else RandomBot(seed_base * 977 + i)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="run1")
    ap.add_argument("--iters", type=int, default=300)
    ap.add_argument("--episodes", type=int, default=48,
                    help="episodes per iteration")
    ap.add_argument("--fast", action="store_true",
                    help="batched lockstep collector (much faster)")
    ap.add_argument("--slots", type=int, default=16,
                    help="parallel env slots for --fast")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--gamma", type=float, default=0.99)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--ent-coef", type=float, default=0.01)
    ap.add_argument("--snap-every", type=int, default=10)
    ap.add_argument("--pool-cap", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", action="store_true",
                    help="continue from ckpt_latest.pt (model+optimizer+pool)")
    args = ap.parse_args()

    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cpu")

    out_dir = os.path.join("runs", args.name)
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "log.csv")
    new_log = not os.path.exists(log_path)

    env = OsrsPvpEnv(seed=args.seed)
    policy = ActorCritic(OBS_DIM, N_ACTIONS).to(device)
    optimizer = torch.optim.Adam(policy.parameters(), lr=args.lr)
    pool = OpponentPool(device)
    start_iter = 1

    if args.resume:
        ckpt_path = os.path.join(out_dir, "ckpt_latest.pt")
        if not os.path.exists(ckpt_path):
            raise SystemExit(f"nothing to resume: {ckpt_path} not found")
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=True)
        policy.load_state_dict(ckpt["model"])
        if "optimizer" in ckpt:
            optimizer.load_state_dict(ckpt["optimizer"])
        start_iter = ckpt.get("iter", 0) + 1
        import glob
        for p in sorted(glob.glob(os.path.join(out_dir, "ckpt_*.pt"))):
            old = torch.load(p, map_location=device, weights_only=True)
            net = ActorCritic(old.get("obs_dim", OBS_DIM),
                              old.get("n_actions", N_ACTIONS)).to(device)
            net.load_state_dict(old["model"])
            net.eval()
            for param in net.parameters():
                param.requires_grad_(False)
            pool.nets.append(net)
        print(f"resumed at iter {start_iter} with {len(pool.nets)} "
              f"pool opponents")

    fast_envs = [OsrsPvpEnv(seed=args.seed * 31 + k)
                 for k in range(max(1, args.slots))] if args.fast else None

    with open(log_path, "a", newline="") as log_f:
        writer = csv.writer(log_f)
        if new_log:
            writer.writerow(["iter", "episodes", "win_rate", "loss_rate",
                             "draw_rate", "avg_ticks", "avg_reward",
                             "pi_loss", "v_loss", "entropy", "kl"])
        for it in range(start_iter, args.iters + 1):
            t0 = time.time()
            if args.fast:
                buf_all, wins, losses, draws, avg_r, avg_ticks = \
                    collect_batched(fast_envs, policy, pool,
                                    target_episodes=args.episodes,
                                    seed_base=args.seed + it)
                stats = ppo_update(policy, optimizer, buf_all.compute(
                    policy, args.gamma, args.lam, device),
                    clip_ratio=args.clip, epochs=args.epochs,
                    ent_coef=args.ent_coef)
                n = args.episodes
                row_w, row_l, row_d = wins / n, losses / n, draws / n
            else:
                buf_all = PPOBuffer()
                wins = losses = draws = 0
                tot_r = tot_ticks = 0
                for ep in range(args.episodes):
                    opponent = pool.sample() if np.random.random() < 0.8 \
                        else RandomBot(args.seed + ep + it)
                    buf, outcome, r, ticks = play_episode(env, policy,
                                                          opponent, device)
                    wins += outcome == 1
                    losses += outcome == 2
                    draws += outcome in (3, 4)
                    tot_r += r
                    tot_ticks += ticks
                    offset = len(buf_all.obs)
                    buf_all.obs.extend(buf.obs)
                    buf_all.acts.extend(buf.acts)
                    buf_all.logp.extend(buf.logp)
                    buf_all.rew.extend(buf.rew)
                    buf_all.val.extend(buf.val)
                    buf_all.mask.extend(buf.mask)
                    buf_all.episodes.append((offset, offset + len(buf.obs)))
                batch = buf_all.compute(policy, args.gamma, args.lam, device)
                stats = ppo_update(policy, optimizer, batch,
                                   clip_ratio=args.clip, epochs=args.epochs,
                                   ent_coef=args.ent_coef)
                n = args.episodes
                row_w, row_l, row_d = wins / n, losses / n, draws / n
                avg_r = tot_r / n
                avg_ticks = tot_ticks / n

            writer.writerow([it, n, row_w, row_l, row_d, avg_ticks, avg_r,
                             f"{stats['pi_loss']:.4f}", f"{stats['v_loss']:.4f}",
                             f"{stats['entropy']:.4f}", f"{stats['kl']:.5f}"])
            log_f.flush()
            print(f"iter {it:4d} | win {row_w:.2f} loss {row_l:.2f} "
                  f"draw {row_d:.2f} | ticks {avg_ticks:.0f} R {avg_r:+.2f} "
                  f"| ent {stats['entropy']:.3f} kl {stats['kl']:.4f} "
                  f"| {time.time() - t0:.1f}s")

            torch.save({"model": policy.state_dict(),
                        "optimizer": optimizer.state_dict(),
                        "iter": it,
                        "obs_dim": OBS_DIM, "n_actions": N_ACTIONS},
                       os.path.join(out_dir, "ckpt_latest.pt"))
            if it % args.snap_every == 0:
                pool.add(policy)
                pool.trim(args.pool_cap)
                torch.save({"model": policy.state_dict(), "iter": it,
                            "obs_dim": OBS_DIM, "n_actions": N_ACTIONS},
                           os.path.join(out_dir, f"ckpt_{it:05d}.pt"))

    print(f"done -> {out_dir}")


if __name__ == "__main__":
    main()
