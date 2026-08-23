import torch
import torch.nn as nn
from torch.distributions import Categorical


def mlp(sizes, activation=nn.Tanh):
    layers = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        if i < len(sizes) - 2:
            layers.append(activation())
    return nn.Sequential(*layers)


class ActorCritic(nn.Module):
    def __init__(self, obs_dim, n_actions, hidden=128):
        super().__init__()
        self.trunk = mlp([obs_dim, hidden, hidden])
        self.pi_head = nn.Linear(hidden, n_actions)
        self.v_head = nn.Linear(hidden, 1)

    def forward(self, obs, mask=None):
        h = self.trunk(obs)
        logits = self.pi_head(h)
        if mask is not None:
            logits = logits.masked_fill(~mask, float("-inf"))
        return logits, self.v_head(h).squeeze(-1)

    def value(self, obs):
        return self.v_head(self.trunk(obs)).squeeze(-1)

    def distribution(self, obs, mask=None):
        logits, _ = self.forward(obs, mask)
        return Categorical(logits=logits)

    @torch.inference_mode()
    def act(self, obs, mask, deterministic=False):
        logits, value = self.forward(obs.unsqueeze(0), mask.unsqueeze(0))
        dist = Categorical(logits=logits)
        action = dist.probs.argmax(dim=-1) if deterministic else dist.sample()
        return int(action.item()), float(dist.log_prob(action).item()), float(value.item())

    @torch.inference_mode()
    def act_batch(self, obs, mask):
        logits, values = self.forward(obs, mask)
        dist = Categorical(logits=logits)
        actions = dist.sample()
        return actions, dist.log_prob(actions), values
