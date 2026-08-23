# osrs-rl

Self-play PPO agent for tick-based OSRS-style melee PvP, trained entirely inside a
local simulator. Research/education only — no game clients are touched.

## Architecture

```
train.py                 self-play loop: learner vs opponent pool + RandomBot
evaluate.py              W/D/L report vs heuristic / random / past checkpoints
envs/osrs_sim.py         the environment (see below)
algo/networks.py         MLP actor-critic with action masking
algo/ppo.py              rollout buffer, GAE, clipped PPO update
runs/<name>/             checkpoints (ckpt_latest.pt, ckpt_NNNNN.pt), log.csv
```

### Environment (`OsrsPvpEnv`)

Simultaneous-turn tick simulation of a 1v1 fight on a 1D tile line:

| Mechanic          | Implementation |
|-------------------|----------------|
| Tick rate         | 0.6 s/tick (`TICK_SECONDS`), max 200 ticks per fight |
| Combat rolls      | Real OSRS formulas — effective levels (+8/+9), `atk_roll = eff_atk * (atk_bonus+64)`, `def_roll` analog, standard hit-chance formula, uniform damage roll `[0..max_hit]` |
| Attack speed      | 4-tick cooldown; attacking resets it; other actions don't |
| Food              | 24 heals of 20 HP; eating consumes your tick (can't attack) |
| Prayer            | Protect toggle blocks all incoming melee that tick; drains 1 point/tick while up; depleting force-disables it. Toggling costs your tick → prayer-flicking emerges as a skill |
| Movement          | ±1 tile/tick toward/away; melee needs distance ≤ 1 |
| Observation       | 12-dim normalized vector (both fighters' HP, food, cooldowns, prayer, protect states, distance, ticks left) |
| Actions           | 6 discrete: attack, eat, move_toward, move_away, protect_toggle, wait — illegal ones masked out before sampling |
| Reward            | +0.05/dmg dealt − 0.05/dmg taken, ±5 win/loss, timeout graded by remaining-HP share |

### Algorithm

PPO (clip 0.2, GAE λ=0.95, γ=0.99, 4 epochs, minibatch 256, entropy bonus 0.01,
value coef 0.5, grad clip 0.5, KL early-stop). Opponent pool snapshots the policy
every 10 iterations (cap 10); each training episode samples an opponent uniformly
from the pool (80%) or RandomBot (20%) so the agent stays robust against stale
strategies — the same self-play scheme used to produce superhuman PvP play.

## Usage

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

# train
& $py train.py --name v1 --iters 200 --episodes 40

# interrupted? pick up where it left off (model+optimizer+opponent pool)
& $py train.py --name v1 --iters 200 --episodes 40 --resume

# evaluate latest checkpoint
& $py evaluate.py runs\v1\ckpt_latest.pt
```

Training logs one CSV row per iteration (win/loss/draw rates, avg reward,
losses, entropy, KL) and prints progress. Expect draws early (random policies
never close distance), then rising win rates vs the pool within ~50–100
iterations on CPU.

## Extension path: real private-server training

The simulator is a drop-in stand-in for a live RSPS environment. To train
against real Elvarg-based mechanics (as in open-source osrs-pvp-reinforcement-learning
projects):

1. Run the modified RSPS that exposes a gym-style socket API
   (`step(action)` / `reset()` routes over a remote-environment server).
2. Replace `OsrsPvpEnv.step/reset/legal_mask` with socket calls returning the
   same `(obs_a, obs_b, r_a, r_b, outcome, done)` tuple.
3. Keep obs/reward semantics identical so checkpoints transfer conceptually;
   widen the observation/action space (styles, specials, potions, multi-target)
   incrementally once the base policy transfers.

Everything above trains on servers you host yourself.
