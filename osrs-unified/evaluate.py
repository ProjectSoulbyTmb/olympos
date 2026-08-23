import argparse
import glob
import os

import numpy as np
import torch

from algo.networks import ActorCritic
from envs.osrs_sim import OsrsPvpEnv, N_ACTIONS, OBS_DIM, HeuristicBot, RandomBot


def load_policy(path, device):
    ckpt = torch.load(path, map_location=device, weights_only=True)
    policy = ActorCritic(ckpt.get("obs_dim", OBS_DIM), ckpt.get("n_actions", N_ACTIONS))
    policy.load_state_dict(ckpt["model"])
    policy.eval()
    return policy


class PoolBot:
    def __init__(self, net):
        self.net = net

    def act(self, obs, mask):
        a, _, _ = self.net.act(torch.from_numpy(obs), torch.from_numpy(mask),
                               deterministic=True)
        return a


def play_matches(policy, opponent, n=300, seed=1234):
    env = OsrsPvpEnv(seed=seed)
    wins = losses = draws = 0
    tot_r = 0.0
    for i in range(n):
        obs_a, obs_b = env.reset()
        done = False
        while not done:
            mask_a, mask_b = env.legal_mask()
            act, _, _ = policy.act(torch.from_numpy(obs_a),
                                   torch.from_numpy(mask_a), deterministic=True)
            opp_act = opponent.act(obs_b, mask_b)
            obs_a, obs_b, r_a, r_b, outcome, done = env.step(act, opp_act)
            tot_r += r_a
        wins += outcome == 1
        losses += outcome == 2
        draws += outcome in (3, 4)
    return wins / n, losses / n, draws / n, tot_r / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt")
    ap.add_argument("--matches", type=int, default=300)
    args = ap.parse_args()

    device = torch.device("cpu")
    policy = load_policy(args.ckpt, device)

    opponents = {"heuristic": HeuristicBot(), "random": RandomBot(7)}
    run_dir = os.path.dirname(args.ckpt) or "."
    for p in sorted(glob.glob(os.path.join(run_dir, "ckpt_*.pt")))[-3:]:
        opponents[os.path.basename(p)] = PoolBot(load_policy(p, device))

    print(f"evaluating {args.ckpt} over {args.matches} matches each")
    for name, opp in opponents.items():
        w, l, d, r = play_matches(policy, opp, n=args.matches)
        print(f"vs {name:<14} W {w:.2f} | L {l:.2f} | D {d:.2f} | avgR {r:+.2f}")


if __name__ == "__main__":
    main()
