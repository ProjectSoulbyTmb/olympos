import numpy as np

TICK_SECONDS = 0.6
ACTIONS = ("attack", "eat", "move_toward", "move_away", "protect_toggle",
           "wait", "shoot", "cast")
N_ACTIONS = len(ACTIONS)
OBS_DIM = 16
MAX_TICKS = 200
MAX_DIST = 8
MELEE_RANGE = 1
RANGED_RANGE = 5
MAGIC_RANGE = MAX_DIST


class Fighter:
    def __init__(self, rng, pos, max_hp=99, food=10, food_heal=20,
                 atk_level=99, str_level=99, def_level=99,
                 rng_level=99, mag_level=94,
                 atk_bonus=60, str_bonus=90, def_bonus=40,
                 rng_bonus=60, mag_bonus=30,
                 ammo=100, runes=100,
                 attack_speed=4, prayer_points=50):
        self.rng = rng
        self.pos = pos
        self.max_hp = max_hp
        self.hp = float(max_hp)
        self.food = food
        self.food_heal = food_heal
        self.atk_level = atk_level
        self.str_level = str_level
        self.def_level = def_level
        self.rng_level = rng_level
        self.mag_level = mag_level
        self.atk_bonus = atk_bonus
        self.str_bonus = str_bonus
        self.def_bonus = def_bonus
        self.rng_bonus = rng_bonus
        self.mag_bonus = mag_bonus
        self.ammo = int(ammo)
        self.runes = int(runes)
        self.attack_speed = attack_speed
        self.cooldown = 0
        self.protect = False
        self.prayer = float(prayer_points)
        self.max_prayer = float(prayer_points)

    def eff_atk(self):
        return self.atk_level + 8

    def eff_rng(self):
        return self.rng_level + 8

    def eff_mag(self):
        return self.mag_level + 8

    def eff_str(self):
        return self.str_level + 9

    def eff_def(self):
        return self.def_level + 8

    def _max_hit(self, eff_level, bonus):
        return int(0.5 + eff_level * (bonus + 64) / 642) + 1

    def max_hit(self):
        return self._max_hit(self.eff_str(), self.str_bonus)

    def max_hit_ranged(self):
        return max(2, self._max_hit(self.eff_rng(), self.rng_bonus))

    def max_hit_magic(self):
        # spells carry their own cap on top of the level scaling
        return min(18, max(3, self._max_hit(self.eff_mag(),
                                            self.mag_bonus)))

    def accuracy_vs(self, defender, style="melee"):
        if style == "ranged":
            atk_roll = self.eff_rng() * (self.rng_bonus + 64)
        elif style == "magic":
            atk_roll = self.eff_mag() * (self.mag_bonus + 64) + 8
        else:
            atk_roll = self.eff_atk() * (self.atk_bonus + 64)
        def_roll = defender.eff_def() * (defender.def_bonus + 64)
        if atk_roll > def_roll:
            return 1.0 - (def_roll + 2) / (2 * (atk_roll + 1))
        return atk_roll / (2.0 * (def_roll + 1))

    def obs_view(self, opp, ticks_left):
        return np.array([
            self.hp / 99.0,
            opp.hp / 99.0,
            self.food / 10.0,
            opp.food / 10.0,
            abs(opp.pos - self.pos) / MAX_DIST,
            self.cooldown / self.attack_speed,
            opp.cooldown / opp.attack_speed,
            self.prayer / self.max_prayer,
            opp.prayer / opp.max_prayer,
            float(self.protect),
            float(opp.protect),
            ticks_left / MAX_TICKS,
            self.ammo / 100.0,
            opp.ammo / 100.0,
            self.runes / 100.0,
            opp.runes / 100.0,
        ], dtype=np.float32)


class OsrsPvpEnv:
    """Tick-based 1v1 PvP with melee, ranged and magic styles. Both
    fighters act each tick simultaneously, mirroring OSRS tick
    semantics; attacks land only inside the style's range."""

    def __init__(self, seed=None):
        self.rng = np.random.default_rng(seed)
        self.a = None
        self.b = None
        self.ticks = 0
        self.done = False

    def reset(self):
        mid = MAX_DIST // 2
        self.a = Fighter(self.rng, mid - 1)
        self.b = Fighter(self.rng, mid + 1)
        self.ticks = 0
        self.done = False
        return self._obs()

    def _obs(self):
        return (
            self.a.obs_view(self.b, MAX_TICKS - self.ticks),
            self.b.obs_view(self.a, MAX_TICKS - self.ticks),
        )

    def legal_mask(self):
        return (
            self._mask_for(self.a, self.b),
            self._mask_for(self.b, self.a),
        )

    def _mask_for(self, f, opp):
        dist = abs(opp.pos - f.pos)
        away_room = (f.pos > 0) if opp.pos > f.pos else (f.pos < MAX_DIST)
        can_act = f.cooldown == 0
        return np.array([
            dist <= MELEE_RANGE and can_act,
            f.food > 0 and f.hp < f.max_hp,
            dist > MELEE_RANGE,
            away_room,
            True,
            True,
            f.ammo > 0 and can_act and dist <= RANGED_RANGE,
            f.runes > 0 and can_act and dist <= MAGIC_RANGE,
        ], dtype=bool)

    def step(self, act_a, act_b):
        assert not self.done
        ra = self._apply(self.a, self.b, act_a)
        rb = self._apply(self.b, self.a, act_b)
        dmg_a, dmg_b = self._resolve_attacks(ra, rb)
        self._tick_cooldowns()
        self.ticks += 1
        rewards, outcome = self._rewards(dmg_a, dmg_b)
        if self.ticks >= MAX_TICKS or self.a.hp <= 0 or self.b.hp <= 0:
            self.done = True
        obs_a, obs_b = self._obs()
        return obs_a, obs_b, rewards[0], rewards[1], outcome, self.done

    def _apply(self, f, opp, action):
        info = {"attacking": None}
        dist = abs(opp.pos - f.pos)
        if action == 0:
            if dist <= MELEE_RANGE:
                info["attacking"] = "melee"
        elif action == 1:
            if f.food > 0 and f.hp < f.max_hp:
                f.food -= 1
                f.hp = min(f.max_hp, f.hp + f.food_heal)
        elif action == 2:
            if dist > MELEE_RANGE:
                if f.pos < opp.pos:
                    f.pos += 1
                else:
                    f.pos -= 1
        elif action == 3:
            if opp.pos > f.pos and f.pos > 0:
                f.pos -= 1
            elif opp.pos < f.pos and f.pos < MAX_DIST:
                f.pos += 1
        elif action == 4:
            if f.protect:
                f.protect = False
            elif f.prayer > 0:
                f.protect = True
        elif action == 6:
            if f.ammo > 0 and f.cooldown == 0 and \
                    dist <= RANGED_RANGE:
                f.ammo -= 1
                info["attacking"] = "ranged"
        elif action == 7:
            if f.runes > 0 and f.cooldown == 0 and \
                    dist <= MAGIC_RANGE:
                f.runes -= 1
                info["attacking"] = "magic"
        return info

    def _resolve_attacks(self, ra, rb):
        dist = abs(self.b.pos - self.a.pos)
        dealt_a = dealt_b = 0.0
        if ra["attacking"] is not None and self.a.cooldown == 0:
            self.a.cooldown = self.a.attack_speed
            dealt_a = self._roll_damage(self.a, self.b, ra["attacking"])
        if rb["attacking"] is not None and self.b.cooldown == 0:
            self.b.cooldown = self.b.attack_speed
            dealt_b = self._roll_damage(self.b, self.a, rb["attacking"])
        return dealt_a, dealt_b

    def _roll_damage(self, attacker, defender, style):
        if self.rng.random() > attacker.accuracy_vs(defender, style):
            return 0.0
        if defender.protect:
            return 0.0
        cap = {"melee": attacker.max_hit(),
               "ranged": attacker.max_hit_ranged(),
               "magic": attacker.max_hit_magic()}[style]
        dmg = int(self.rng.integers(0, cap + 1))
        defender.hp = max(0.0, defender.hp - dmg)
        return float(dmg)

    def _tick_cooldowns(self):
        for f in (self.a, self.b):
            if f.cooldown > 0:
                f.cooldown -= 1
            if f.protect:
                f.prayer -= 1.0
                if f.prayer <= 0:
                    f.prayer = 0.0
                    f.protect = False

    def _rewards(self, dmg_a, dmg_b):
        rw_a = 0.05 * dmg_a - 0.05 * dmg_b
        rw_b = -rw_a
        outcome = 0
        if self.a.hp <= 0 and self.b.hp <= 0:
            outcome = 3
            rw_a -= 5.0
            rw_b -= 5.0
        elif self.b.hp <= 0:
            outcome = 1
            rw_a += 5.0
            rw_b -= 5.0
        elif self.a.hp <= 0:
            outcome = 2
            rw_a -= 5.0
            rw_b += 5.0
        elif self.ticks >= MAX_TICKS:
            outcome = 4
            share_a = self.a.hp / (self.a.hp + self.b.hp + 1e-6)
            rw_a += (share_a - 0.5) * 1.0 - 1.0
            rw_b += ((1.0 - share_a) - 0.5) * 1.0 - 1.0
        return (rw_a, rw_b), outcome


class HeuristicBot:
    """Kite-and-eat bot that shoots when it cannot close the distance."""

    def act(self, obs, mask):
        hp, ohp, food, ofood, dist, cd, ocd, prayer, opray, prot, oprot, \
            tleft, ammo, oammo, runes, orunes = obs
        if mask[1] and hp < 0.45:
            return 1
        if mask[4] and not prot and ocd <= 0.25:
            return 4
        if mask[0]:
            return 0
        if mask[6] and dist > MELEE_RANGE:
            return 6
        if mask[7] and dist > MELEE_RANGE:
            return 7
        if mask[2]:
            return 2
        return 5


class RandomBot:
    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)

    def act(self, obs, mask):
        idxs = np.flatnonzero(mask)
        if len(idxs) == 0:
            return 5
        return int(self.rng.choice(idxs))
