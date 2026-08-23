import numpy as np
import torch
import torch.nn as nn
from torch.distributions import Categorical


def compute_gae(rewards, values, gamma=0.99, lam=0.95):
    n = len(rewards)
    adv = torch.zeros(n)
    lastgae = 0.0
    for t in reversed(range(n)):
        next_value = values[t + 1] if t < n - 1 else 0.0
        delta = rewards[t] + gamma * next_value - values[t]
        lastgae = delta + gamma * lam * lastgae
        adv[t] = lastgae
    return adv, adv + torch.tensor(values[:n], dtype=torch.float32)


class PPOBuffer:
    def __init__(self):
        self.obs, self.acts, self.logp = [], [], []
        self.rew, self.val, self.mask = [], [], []
        self.episodes = []

    def start_episode(self):
        self._start = len(self.obs)

    def store(self, obs, act, logp, rew, val, mask):
        self.obs.append(obs)
        self.acts.append(act)
        self.logp.append(logp)
        self.rew.append(rew)
        self.val.append(val)
        self.mask.append(mask)

    def finish_episode(self):
        self.episodes.append((self._start, len(self.obs)))

    def compute(self, policy, gamma, lam, device):
        with torch.no_grad():
            obs_t = torch.as_tensor(np_stack(self.obs), dtype=torch.float32, device=device)
            vals = policy.value(obs_t).cpu()
        flat_adv = torch.zeros(len(self.obs))
        flat_ret = torch.zeros(len(self.obs))
        for start, end in self.episodes:
            r = torch.tensor(self.rew[start:end], dtype=torch.float32)
            v = [vals[i].item() for i in range(start, end)] + [0.0]
            adv, ret = compute_gae(r, v, gamma, lam)
            flat_adv[start:end] = adv
            flat_ret[start:end] = ret
        return {
            "obs": obs_t,
            "acts": torch.tensor(self.acts, dtype=torch.long, device=device),
            "logp_old": torch.tensor(self.logp, dtype=torch.float32, device=device),
            "mask": torch.as_tensor(np_stack(self.mask), dtype=torch.bool, device=device),
            "adv": flat_adv.to(device),
            "ret": flat_ret.to(device),
        }

    def clear(self):
        self.__init__()


def np_stack(arrs):
    return np.stack([np.asarray(a, dtype=np.float32) for a in arrs])


def ppo_update(policy, optimizer, batch, clip_ratio=0.2, epochs=4,
               minibatch_size=256, ent_coef=0.01, vf_coef=0.5,
               max_grad_norm=0.5, target_kl=0.03):
    n = batch["obs"].shape[0]
    idx = torch.randperm(n, device=batch["obs"].device)
    stats = {"pi_loss": 0.0, "v_loss": 0.0, "entropy": 0.0, "kl": 0.0, "stops": 0}
    batches_done = 0

    adv = batch["adv"]
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)

    for _ in range(epochs):
        for s in range(0, n, minibatch_size):
            mb = idx[s:s + minibatch_size]
            if len(mb) < 2:
                continue
            logits, values = policy(batch["obs"][mb], batch["mask"][mb])
            dist = Categorical(logits=logits)
            logp = dist.log_prob(batch["acts"][mb])
            ratio = torch.exp(logp - batch["logp_old"][mb])
            mb_adv = adv[mb]
            clipped = torch.clamp(ratio, 1 - clip_ratio, 1 + clip_ratio) * mb_adv
            pi_loss = -(torch.min(ratio * mb_adv, clipped)).mean()
            v_loss = ((values - batch["ret"][mb]) ** 2).mean() * 0.5
            entropy = dist.entropy().mean()
            loss = pi_loss + vf_coef * v_loss - ent_coef * entropy

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(policy.parameters(), max_grad_norm)
            optimizer.step()

            with torch.no_grad():
                kl = (batch["logp_old"][mb] - logp).mean().item()
            stats["pi_loss"] += pi_loss.item()
            stats["v_loss"] += v_loss.item()
            stats["entropy"] += entropy.item()
            stats["kl"] += max(kl, 0.0)
            batches_done += 1
            if target_kl and kl > 1.5 * target_kl:
                stats["stops"] += 1
                break

    if batches_done:
        for k in ("pi_loss", "v_loss", "entropy", "kl"):
            stats[k] /= batches_done
    return stats
