import heapq
import math

from .content import (AGILITY_LAP_TICKS, AGILITY_LAP_XP, ARROWS,
                      ARMOURS, ARMOUR_ACC_REDUCTION, ARMOUR_BLOCK_DIVISOR,
                      BONES_BURY_XP, BONES_OFFER_XP, BOWS, COMBAT_STYLES,
                      ENERGY_PER_AGILITY, FOOD, FLETCHING, HERBS,
                      HITPOINTS_START_XP, LEATHER,
                      NPCS, NPC_SPAWNS, POTIONS, PRAYER_DEFENCE_FACTOR,
                      RUNE_EXTRA_CAP, RUNE_EXTRA_CHANCE_STEP, RUNES,
                      SLAYER_REWARD_COINS, SLAYER_REWARD_XP,
                      SLAYER_TASK_POOL, SLAYER_XP_PER_TASK_KILL, SPELLS,
                      STALLS, WEAPONS)

# _EXTRA_FALLBACK: tolerate import-list drift for extension registries
for _n in ('QUESTS_EXTRA', 'COOKABLES_EXTRA', 'FIREMAKING_XP_EXTRA',
           'ROCKS_EXTRA', 'SMELTING_EXTRA', 'TREES_EXTRA'):
    if _n not in globals():
        globals()[_n] = {}


def xp_for_level(level):
    total = 0
    for l in range(1, level):
        total += math.floor(l + 300 * 2 ** (l / 7))
    return math.floor(total / 4)


XP_TABLE = [0] + [xp_for_level(l) for l in range(2, 100)]


def level_from_xp(xp):
    lvl = 1
    for i, threshold in enumerate(XP_TABLE):
        if xp >= threshold:
            lvl = i + 1
        else:
            break
    return lvl


SKILLS = ("woodcutting", "mining", "fishing", "cooking", "firemaking",
          "smithing", "attack", "strength", "defence", "hitpoints",
          "prayer", "ranged", "magic", "runecrafting", "thieving",
          "agility", "herblore", "crafting", "fletching", "slayer",
          "farming")

GRID = 24

GRID = 24

# All game-data tables live in content.py; re-exported here so existing
# `from game.world import X` calls keep working.
from .content import (AXES, COOKABLES, FIREMAKING_XP, FISH, LOCATIONS,
                      PICKAXES, QUESTS, ROCKS, SHOP_PRICES, SHOP_STOCK,
                      SPAWN, SMELTING, TREES, UNIQUE_TOOLS)  # noqa: E402,F401


def chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class GameError(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class World:
    kernel = None

    def __init__(self, seed=1337, tick_budget=3000, uim=False):
        import random
        self.rng = random.Random(seed)
        self.tick_budget = tick_budget
        self.uim = uim
        self.reset()

    def reset(self):
        self.tick = 0
        self.pos = SPAWN
        self.coins = 25
        self.inventory = {}
        self.bank_items = {}
        self.xp = {s: 0.0 for s in SKILLS}
        self.xp["hitpoints"] = float(HITPOINTS_START_XP)
        self.hp = self.max_hp
        self.tools = ["bronze_axe", "bronze_pickaxe"]
        self.node_hp = {}
        self.respawn_at = {}
        self._respawn_heap = []
        self.combat_style = "accurate"
        self.npc_hp = {n: NPCS[k]["hp"]
                       for n, (k, _p) in NPC_SPAWNS.items()}
        self.npc_respawn_at = {}
        self._npc_respawn_heap = []
        self.stall_cd = {}
        self.buffs = {}
        self.patches = {}
        self.slayer_task = None
        self.on_tick = None
        self.energy = 100.0
        self.run = False
        self._moving = False
        self.energy_regen_mult = 1.0
        self.claims = set()
        self.quests = {q: "not_started" for q in QUESTS}
        for name, (_kind, _res, _pos) in LOCATIONS.items():
            if _kind in ("tree", "rock"):
                spec = (TREES if _kind == "tree" else ROCKS)[_res]
                self.node_hp[name] = spec["hp"]
        self.xp_timeline = [(0, 0.0)]
        self.coin_timeline = [(0, self.coins)]
        self.log = []

    @property
    def ticks_left(self):
        return self.tick_budget - self.tick

    @property
    def max_hp(self):
        return self.skill_level("hitpoints")

    @property
    def energy_cap(self):
        return 100.0 + ENERGY_PER_AGILITY * self.skill_level("agility")

    def eff_level(self, skill):
        b = self.buffs.get(skill)
        if b and self.tick < b.get("until", 0):
            return self.skill_level(skill) + b["amt"]
        return self.skill_level(skill)

    def _armour_bonus(self):
        return sum(ARMOURS[p][1] for p in self.tools if p in ARMOURS)

    def save(self):
        return {
            "version": 5,
            "tick": self.tick,
            "tick_budget": self.tick_budget,
            "uim": self.uim,
            "pos": list(self.pos),
            "coins": self.coins,
            "inventory": dict(self.inventory),
            "bank_items": dict(self.bank_items),
            "xp": dict(self.xp),
            "tools": list(self.tools),
            "node_hp": dict(self.node_hp),
            "respawn_at": dict(self.respawn_at),
            "hp": self.hp,
            "combat_style": self.combat_style,
            "npc_hp": dict(self.npc_hp),
            "npc_respawn_at": dict(self.npc_respawn_at),
            "stall_cd": dict(self.stall_cd),
            "buffs": {k: dict(v) for k, v in self.buffs.items()},
            "patches": {k: dict(v) for k, v in self.patches.items()},
            "slayer_task": dict(self.slayer_task) if self.slayer_task else None,
            "xp_timeline": self.xp_timeline[-5000:],
            "coin_timeline": self.coin_timeline[-5000:],
            "log": self.log[-200:],
            "energy": self.energy,
            "run": self.run,
            "energy_regen_mult": float(self.energy_regen_mult),
            "claims": sorted(self.claims),
            "quests": dict(self.quests),
            "rng_state": self.rng.getstate(),
        }

    def load_snapshot(self, data):
        if data.get("version") not in (1, 2, 3, 4, 5):
            raise ValueError("unsupported session version")
        self.reset()
        self.tick = data["tick"]
        self.tick_budget = data["tick_budget"]
        self.uim = data["uim"]
        self.pos = tuple(data["pos"])
        self.coins = data["coins"]
        self.inventory = dict(data["inventory"])
        self.bank_items = dict(data["bank_items"])
        self.xp = {s: float(v) for s, v in data["xp"].items()}
        for s in SKILLS:
            self.xp.setdefault(s, 0.0)
        if data["version"] == 1:
            self.xp["hitpoints"] = float(HITPOINTS_START_XP)
        self.hp = min(int(data.get("hp", 0)) or self.max_hp,
                      self.max_hp)
        self.combat_style = data.get("combat_style", "accurate")
        self.tools = list(data["tools"])
        self.node_hp = dict(data["node_hp"])
        self.respawn_at = dict(data["respawn_at"])
        self._respawn_heap = [(due, node)
                              for node, due in self.respawn_at.items()]
        heapq.heapify(self._respawn_heap)
        self.npc_hp = {n: int(data.get("npc_hp", {}).get(n, hp))
                       for n, hp in
                       ((n, NPCS[k]["hp"]) for n, (k, _p) in
                        NPC_SPAWNS.items())}
        self.npc_respawn_at = dict(data.get("npc_respawn_at", {}))
        self._npc_respawn_heap = [(due, npc) for npc, due in
                                  self.npc_respawn_at.items()]
        heapq.heapify(self._npc_respawn_heap)
        self.stall_cd = dict(data.get("stall_cd", {}))
        self.buffs = {k: dict(v) for k, v in data.get("buffs", {}).items()}
        self.patches = {k: dict(v) for k, v in
                        data.get("patches", {}).items()}
        st = data.get("slayer_task")
        self.slayer_task = dict(st) if st else None
        self.xp_timeline = [tuple(x) for x in data["xp_timeline"]]
        self.coin_timeline = [tuple(x) for x in data["coin_timeline"]]
        self.log = list(data["log"])
        self.energy = data.get("energy", 100.0)
        self.run = data.get("run", False)
        self.energy_regen_mult = max(0.5, min(2.0,
                                       float(data.get("energy_regen_mult",
                                                      1.0))))
        self.claims = set(data.get("claims", []))
        saved_quests = data.get("quests")
        if saved_quests:
            self.quests.update(saved_quests)
        rs = data["rng_state"]
        self.rng.setstate((rs[0], tuple(rs[1]), rs[2]))

    def spend(self, n):
        if self.ticks_left <= 0:
            raise BudgetExceeded()
        n = min(n, self.ticks_left)
        self._idle_streak = 0
        self.tick += n
        return n

    def advance(self, n):
        start = self.tick
        end = start + n
        xp_changed = False
        coin_changed = False
        while self._respawn_heap and self._respawn_heap[0][0] <= end:
            due, node = heapq.heappop(self._respawn_heap)
            if node in self.respawn_at and self.respawn_at[node] != due:
                continue
            del self.respawn_at[node]
            kind_res = LOCATIONS[node]
            spec = (TREES if kind_res[0] == "tree" else ROCKS)[kind_res[1]]
            self.node_hp[node] = spec["hp"]
        while (self._npc_respawn_heap and
               self._npc_respawn_heap[0][0] <= end):
            due, npc = heapq.heappop(self._npc_respawn_heap)
            if (npc in self.npc_respawn_at and
                    self.npc_respawn_at[npc] != due):
                continue
            del self.npc_respawn_at[npc]
            kind, _p = NPC_SPAWNS[npc]
            self.npc_hp[npc] = NPCS[kind]["hp"]
        old_xp_total = self.xp_timeline[-1][1] if self.xp_timeline else 0.0
        old_coins = self.coin_timeline[-1][1] if self.coin_timeline else 0
        new_xp_total = self.total_xp
        if new_xp_total != old_xp_total:
            self.xp_timeline.append((self.tick, new_xp_total))
            xp_changed = True
        if self.coins != old_coins:
            self.coin_timeline.append((self.tick, self.coins))
            coin_changed = True
        if not self._moving and self.energy < self.energy_cap:
            self.energy = min(self.energy_cap,
                              self.energy + 0.5 * self.energy_regen_mult * n)
        if self.on_tick is not None:
            cur = self.tick
            for t in range(cur - n + 1, cur + 1):
                self.tick = t
                self.on_tick(t)
            self.tick = cur
        kernel_active = (self.kernel is not None and
                         (self.kernel.has_listeners("tick") or
                          self.kernel.jobs_pending()))
        if kernel_active:
            cur = self.tick
            for t in range(max(cur - n + 1, 1), cur + 1):
                self.tick = t
                self.kernel.emit("tick", tick=t)
            self.tick = cur
        elif self.kernel is not None:
            self.kernel.emit("tick", tick=self.tick)

    @property
    def total_xp(self):
        return sum(self.xp.values())

    def inv_count(self):
        return sum(self.inventory.values())

    def inv_add(self, item, n=1):
        space = 28 - self.inv_count()
        take = min(n, space)
        if take <= 0:
            return False
        self.inventory[item] = self.inventory.get(item, 0) + take
        if take < n:
            return False
        return True

    def skill_level(self, skill):
        return level_from_xp(self.xp[skill])

    def best_tool_bonus(self, table):
        owned = [v for k, v in table.items() if k in self.tools]
        return max(owned) if owned else 0.0

    def move_to(self, x, y):
        if not (0 <= x < GRID and 0 <= y < GRID):
            raise GameError(f"({x},{y}) is outside the map")
        dist = chebyshev(self.pos, (x, y))
        if dist == 0:
            return 0
        ticks = dist
        if self.run and self.energy >= dist * 0.67:
            ticks = max(1, math.ceil(dist / 2))
            self.energy = max(0.0, self.energy - dist)
        self._moving = True
        self.spend(ticks)
        self.advance(ticks)
        self._moving = False
        self.pos = (x, y)
        return ticks

    def set_run(self, on):
        if not isinstance(on, bool):
            raise GameError("set_run(True) or set_run(False)")
        self.run = on

    def light_fire(self):
        for item in ("logs", "oak_logs"):
            if self.inventory.get(item, 0) > 0:
                self.inventory[item] -= 1
                if self.inventory[item] == 0:
                    del self.inventory[item]
                self.add_xp("firemaking", FIREMAKING_XP[item])
                self.spend(2)
                self.advance(2)
                return item
        raise GameError("no logs to burn")

    def smelt(self, bar):
        if bar not in SMELTING:
            raise GameError(f"unknown bar '{bar}'")
        if chebyshev(self.pos, LOCATIONS["furnace"][2]) > 1:
            raise GameError("stand next to the furnace to smelt")
        spec = SMELTING[bar]
        lvl = self.skill_level("smithing")
        if lvl < spec["req"]:
            raise GameError(f"{bar} needs smithing level {spec['req']}")
        for ore in spec["ores"]:
            if self.inventory.get(ore, 0) <= 0:
                raise GameError(f"need a {ore} to smelt {bar}")
        for ore in spec["ores"]:
            self.inventory[ore] -= 1
            if self.inventory[ore] == 0:
                del self.inventory[ore]
        self.spend(4)
        success = True
        if bar == "iron_bar":
            fail = max(0.0, 0.5 - (lvl - spec["req"]) * 0.02)
            success = self.rng.random() >= fail
        if success:
            self.inv_add(spec["item"])
            self.add_xp("smithing", spec["xp"])
        else:
            self.note("lost an iron ore in the furnace")
        self.advance(4)
        return success

    def talk_quest(self, quest=None):
        if chebyshev(self.pos, LOCATIONS["quest_giver"][2]) > 1:
            raise GameError("stand next to the quest giver to talk")
        names = [quest] if quest else list(QUESTS)
        for q in names:
            if q not in QUESTS:
                raise GameError(f"unknown quest '{q}'")
            spec = QUESTS[q]
            status = self.quests[q]
            if status == "claimed":
                continue
            if status == "not_started":
                self.quests[q] = "active"
                self.note(f"quest accepted: {spec['description']}")
            elif status == "active":
                have = self.inventory.get(spec["item"], 0)
                if have >= spec["amount"]:
                    self.inventory[spec["item"]] -= spec["amount"]
                    if self.inventory[spec["item"]] == 0:
                        del self.inventory[spec["item"]]
                    self.add_xp(spec["skill"], spec["xp_reward"])
                    self.coins += spec["coin_reward"]
                    self.quests[q] = "claimed"
                    self.note(f"QUEST COMPLETE: {q} (+{int(spec['xp_reward'])} "
                              f"{spec['skill']} xp, +{spec['coin_reward']} coins)")
                    if self.kernel is not None:
                        self.kernel.emit("quest_complete", quest=q)
                else:
                    self.note(f"{q}: {have}/{spec['amount']} {spec['item']}")
        self.spend(1)
        self.advance(1)

    def quest_status(self):
        return dict(self.quests)

    def _node_at_adjacent(self, prefix):
        cands = []
        for name, (kind, res, pos) in LOCATIONS.items():
            if name.startswith(prefix) and chebyshev(self.pos, pos) <= 1:
                cands.append(name)
        if not cands:
            raise GameError(f"not standing next to a {prefix.rstrip('_123456789')}")
        alive = [n for n in cands if n in self.node_hp and self.node_hp[n] > 0]
        if not alive:
            self._idle_streak = getattr(self, '_idle_streak', 0) + 1
            if self._idle_streak >= 25:
                self.note('idling while resources regrow')
                self.wait(10)
                self._idle_streak = 0
            raise GameError(f"every nearby {prefix.rstrip('_123456789')} is "
                            "depleted and still regrowing")
        return self.rng.choice(alive)

    def chop(self):
        name = self._node_at_adjacent("tree")
        kind, res, _ = LOCATIONS[name]
        spec = TREES[res]
        lvl = self.skill_level("woodcutting")
        if lvl < spec["req"]:
            raise GameError(f"{res} needs woodcutting level {spec['req']}, you have {lvl}")
        if name in self.respawn_at or self.node_hp.get(name, 0) <= 0:
            raise GameError("this tree has fallen and is still regrowing")
        self.spend(4)
        chance = min(0.95, 0.30 + (lvl - spec["req"]) * 0.015 + self.best_tool_bonus(AXES))
        got_log = False
        if self.rng.random() < chance:
            item = spec["item"]
            if self.inv_add(item):
                got_log = True
                self.add_xp("woodcutting", spec["xp"])
            else:
                self.note("inventory full while chopping")
        self.node_hp[name] -= 1
        if self.node_hp[name] <= 0:
            self.respawn_at[name] = self.tick + spec["respawn"]
            heapq.heappush(self._respawn_heap,
                           (self.respawn_at[name], name))
        self.advance(4)
        return got_log

    def mine(self):
        name = self._node_at_adjacent("rock")
        kind, res, _ = LOCATIONS[name]
        spec = ROCKS[res]
        lvl = self.skill_level("mining")
        if lvl < spec["req"]:
            raise GameError(f"{res} needs mining level {spec['req']}, you have {lvl}")
        if name in self.respawn_at or self.node_hp.get(name, 0) <= 0:
            raise GameError("this rock is depleted and still regenerating")
        self.spend(4)
        chance = min(0.95, spec.get("base", 0.30) +
                     (lvl - spec["req"]) * 0.015 +
                     self.best_tool_bonus(PICKAXES))
        got_ore = False
        if self.rng.random() < chance:
            item = spec["item"]
            if self.inv_add(item):
                got_ore = True
                self.add_xp("mining", spec["xp"])
            else:
                self.note("inventory full while mining")
        self.node_hp[name] -= 1
        if self.node_hp[name] <= 0:
            self.respawn_at[name] = self.tick + spec["respawn"]
            heapq.heappush(self._respawn_heap,
                           (self.respawn_at[name], name))
        self.advance(4)
        return got_ore

    def fish(self):
        name = None
        for n, (kind, res, pos) in LOCATIONS.items():
            if kind == "spot" and chebyshev(self.pos, pos) <= 1:
                name = n
        if name is None:
            raise GameError("not standing next to a fishing spot")
        spec = FISH["shrimp"]
        lvl = self.skill_level("fishing")
        if lvl < spec["req"]:
            raise GameError(f"fishing level {spec['req']} required")
        self.spend(4)
        caught = False
        chance = min(0.95, 0.40 + lvl * 0.008)
        if self.rng.random() < chance:
            if self.inv_add(spec["item"]):
                caught = True
                self.add_xp("fishing", spec["xp"])
            else:
                self.note("inventory full while fishing")
        self.advance(4)
        return caught

    def cook(self, raw_item=None):
        target = raw_item or self._first_raw()
        if target is None:
            raise GameError("no raw food in inventory")
        if chebyshev(self.pos, LOCATIONS["range"][2]) > 1:
            raise GameError("stand next to the range to cook")
        spec = COOKABLES[target]
        lvl = self.skill_level("cooking")
        if lvl < spec["req"]:
            raise GameError(f"cooking level {spec['req']} required")
        if self.inventory.get(target, 0) <= 0:
            raise GameError(f"no {target} left")
        self.inventory[target] -= 1
        if self.inventory[target] == 0:
            del self.inventory[target]
        burn = max(0.0, 0.45 - (lvl - spec["req"]) * 0.02)
        if target == "raw_shrimp" and lvl >= spec["stop_burn"]:
            burn = 0.0
        cooked = self.rng.random() >= burn
        if cooked:
            self.inv_add(spec["item"])
            self.add_xp("cooking", spec["xp"])
        else:
            self.note(f"burned a {target}")
        self.spend(2)
        self.advance(2)
        return cooked

    def _first_raw(self):
        for item in self.inventory:
            if item.startswith("raw_"):
                return item
        return None

    # ---------------- combat (modelled on OSRS mechanics) ----------------

    def set_combat_style(self, style):
        if style not in COMBAT_STYLES:
            raise GameError(
                f"unknown combat style '{style}' "
                f"(valid: {', '.join(COMBAT_STYLES)})")
        self.combat_style = style

    def _weapon(self):
        best = None
        for name, (atk, stren, req) in WEAPONS.items():
            if name in self.tools and self.skill_level("attack") >= req:
                if best is None or stren > best[1]:
                    best = (atk, stren)
        return best or (0, 0)

    def _player_hit(self, kind):
        spec = NPCS[kind]
        atk_lvl = self.eff_level("attack")
        atk_bonus, str_bonus = self._weapon()
        acc = min(0.95, max(0.20, 0.60 + (atk_lvl + atk_bonus -
                                          spec["accuracy"]) * 0.03))
        if self.rng.random() >= acc:
            return 0
        max_hit = 1 + (self.eff_level("strength") + str_bonus * 2) // 6
        return self.rng.randint(1, max(1, int(max_hit)))

    def _npc_retaliate(self, kind):
        spec = NPCS[kind]
        def_lvl = self.eff_level("defence")
        armour = self._armour_bonus()
        acc = min(0.8, max(0.05,
                           0.5 - (def_lvl - spec["level"]) * 0.02 -
                           self.eff_level("prayer") *
                           PRAYER_DEFENCE_FACTOR -
                           armour * ARMOUR_ACC_REDUCTION))
        dmg = 0
        if self.rng.random() < acc:
            dmg = self.rng.randint(0, spec["max_hit"])
        if dmg > 0:
            dmg = max(0, dmg - armour // ARMOUR_BLOCK_DIVISOR)
        if dmg > 0:
            self._take_damage(dmg)
        return dmg

    def _take_damage(self, dmg):
        self.hp -= dmg
        if self.hp <= 0:
            self.hp = self.max_hp
            self.pos = SPAWN
            self.note("you died and woke up back at spawn - items kept")
            if self.kernel is not None:
                self.kernel.emit("player_death")

    def _grant_combat_xp(self, dmg):
        if dmg <= 0:
            return
        style_skill = COMBAT_STYLES[self.combat_style]
        self.add_xp(style_skill, 4.0 * dmg)
        self.add_xp("hitpoints", 1.33 * dmg)

    def _player_shot(self, kind, arrow):
        spec = NPCS[kind]
        r_lvl = self.eff_level("ranged")
        bow_bonus = max((BOWS[b][1] for b in self.tools if b in BOWS),
                        default=0)
        acc = min(0.95, max(0.20, 0.55 + (r_lvl + bow_bonus -
                                          spec["accuracy"]) * 0.03))
        if self.rng.random() >= acc:
            return 0
        bonus = ARROWS[arrow][1]
        max_hit = (1 + r_lvl // 10 + bonus // 2 + bow_bonus // 2)
        return self.rng.randint(1, max(1, int(max_hit)))

    def _kill_npc(self, npc_name, kind):
        spec = NPCS[kind]
        self.npc_hp[npc_name] = 0
        self.npc_respawn_at[npc_name] = self.tick + spec["respawn"]
        heapq.heappush(self._npc_respawn_heap,
                       (self.npc_respawn_at[npc_name], npc_name))
        loot = []
        for item, chance, lo, hi in spec["drops"]:
            if self.rng.random() < chance:
                n = self.rng.randint(lo, hi)
                if item == "coins":
                    self.coins += n
                elif not self.inv_add(item, n):
                    n = 0
                if n > 0:
                    loot.append(f"{item} x{n}")
        self.note(f"killed {kind}: " + (", ".join(loot) or "no drops"))
        if (self.slayer_task and self.slayer_task["kind"] == kind
                and self.slayer_task["done"] < self.slayer_task["need"]):
            self.slayer_task["done"] += 1
            self.add_xp("slayer", SLAYER_XP_PER_TASK_KILL)
            if self.slayer_task["done"] >= self.slayer_task["need"]:
                self.note(f"slayer task complete: return to the slayer "
                          "master for your reward")
        self.kernel and self.kernel.emit("npc_kill", npc=npc_name, kind=kind)
        return loot

    def attack(self, npc_name):
        entry = NPC_SPAWNS.get(npc_name)
        if entry is None:
            raise GameError(f"unknown npc '{npc_name}' "
                            f"(valid: {', '.join(NPC_SPAWNS)})")
        kind, pos = entry
        dist = chebyshev(self.pos, pos)
        arrow = None
        if self.combat_style == "ranged":
            if dist > 3:
                raise GameError(f"{npc_name} is out of bow range (3 tiles)")
            bow_ok = any(b in self.tools for b in BOWS)
            if not bow_ok:
                raise GameError("you need a shortbow to shoot (buy one)")
            arrow = next((a for a in ARROWS
                          if self.inventory.get(a, 0) > 0), None)
            if arrow is None:
                raise GameError("no arrows left")
            req = ARROWS[arrow][0]
            if self.skill_level("ranged") < req:
                raise GameError(f"{arrow} needs ranged level {req}")
        else:
            if dist > 1:
                raise GameError(f"move next to {npc_name} to attack it")
        if npc_name in self.npc_respawn_at or self.npc_hp.get(npc_name, 0) <= 0:
            raise GameError(f"{npc_name} is dead and still respawning")
        self.spend(4)
        result = {"npc": npc_name}
        if arrow is not None:
            self.inventory[arrow] -= 1
            if self.inventory[arrow] == 0:
                del self.inventory[arrow]
            dmg = self._player_shot(kind, arrow)
        else:
            dmg = self._player_hit(kind)
        self.npc_hp[npc_name] -= dmg
        result["player_damage"] = dmg
        self._grant_combat_xp(dmg)
        killed = self.npc_hp[npc_name] <= 0
        result["killed"] = killed
        if killed:
            result["drops"] = self._kill_npc(npc_name, kind)
        elif chebyshev(self.pos, pos) <= 1:
            result["retaliation_damage"] = self._npc_retaliate(kind)
        else:
            result["retaliation_damage"] = 0
        self.advance(4)
        return result

    def cast(self, spell, npc_name):
        if spell not in SPELLS:
            raise GameError(f"unknown spell '{spell}' "
                            f"(valid: {', '.join(SPELLS)})")
        spec = SPELLS[spell]
        lvl = self.skill_level("magic")
        if lvl < spec["req"]:
            raise GameError(f"{spell} needs magic level {spec['req']}")
        entry = NPC_SPAWNS.get(npc_name)
        if entry is None:
            raise GameError(f"unknown npc '{npc_name}'")
        kind, pos = entry
        dist = chebyshev(self.pos, pos)
        if dist > 4:
            raise GameError(f"{npc_name} is out of spell range (4 tiles)")
        for rune, need in spec["runes"].items():
            if self.inventory.get(rune, 0) < need:
                raise GameError(f"{spell} needs {need}x {rune}")
        if npc_name in self.npc_respawn_at or self.npc_hp.get(npc_name, 0) <= 0:
            raise GameError(f"{npc_name} is dead and still respawning")
        self.spend(4)
        for rune, need in spec["runes"].items():
            self.inventory[rune] -= need
            if self.inventory[rune] == 0:
                del self.inventory[rune]
        acc = min(0.95, max(0.15, 0.55 + (lvl - NPCS[kind]["level"]) * 0.03))
        dmg = (self.rng.randint(1, spec["max_hit"])
               if self.rng.random() < acc else 0)
        self.npc_hp[npc_name] -= dmg
        xp = spec["base_xp"] + 2.0 * dmg
        self.add_xp("magic", xp)
        if dmg > 0:
            self.add_xp("hitpoints", 1.33 * dmg)
        result = {"npc": npc_name, "spell": spell,
                  "player_damage": dmg, "magic_xp": round(xp, 1)}
        killed = self.npc_hp[npc_name] <= 0
        result["killed"] = killed
        if killed:
            result["drops"] = self._kill_npc(npc_name, kind)
        elif chebyshev(self.pos, pos) <= 1:
            result["retaliation_damage"] = self._npc_retaliate(kind)
        else:
            result["retaliation_damage"] = 0
        self.advance(4)
        return result

    def eat(self, item):
        if item not in FOOD:
            raise GameError(f"'{item}' is not edible "
                            f"(valid: {', '.join(FOOD)})")
        if self.inventory.get(item, 0) <= 0:
            raise GameError(f"no {item} in inventory")
        heal = min(FOOD[item], self.max_hp - self.hp)
        self.inventory[item] -= 1
        if self.inventory[item] == 0:
            del self.inventory[item]
        self.hp += heal
        self.note(f"ate a {item} (+{heal} hp)")
        self.spend(3)
        self.advance(3)
        return heal

    def npcs(self):
        out = []
        for name, (kind, pos) in NPC_SPAWNS.items():
            d = chebyshev(self.pos, pos)
            status = "(respawning)" if name in self.npc_respawn_at \
                else f"(hp {self.npc_hp[name]})"
            out.append({"name": name, "kind": kind, "level": NPCS[kind]["level"],
                        "pos": pos, "distance": d, "status": status})
        return out

    def bury_bones(self):
        if self.inventory.get("bones", 0) <= 0:
            raise GameError("no bones to bury - kill something first")
        self.inventory["bones"] -= 1
        if self.inventory["bones"] == 0:
            del self.inventory["bones"]
        self.add_xp("prayer", BONES_BURY_XP)
        self.note("you bury the bones")
        self.spend(1)
        self.advance(1)
        return True

    def offer_bones(self):
        if chebyshev(self.pos, LOCATIONS["shrine"][2]) > 1:
            raise GameError("stand next to the shrine to offer bones")
        n = self.inventory.get("bones", 0)
        if n <= 0:
            raise GameError("no bones to offer")
        del self.inventory["bones"]
        xp = BONES_OFFER_XP * n
        self.add_xp("prayer", xp)
        self.note(f"you offer {n} bones at the shrine (+{int(xp)} prayer xp)")
        self.spend(n)
        self.advance(n)
        return n

    def search_chest(self):
        if chebyshev(self.pos,
                     LOCATIONS["stronghold_of_security"][2]) > 1:
            raise GameError("stand next to the stronghold chest to search "
                            "it")
        if "stronghold_chest" in self.claims:
            self.note("the stronghold chest is already emptied")
            return False
        self.claims.add("stronghold_chest")
        reward = 500
        self.coins += reward
        self.note(f"you find {reward} coins in the stronghold chest")
        self.spend(2)
        self.advance(2)
        return True

    def craft_rune(self, rune_name):
        if rune_name not in RUNES:
            raise GameError(f"unknown rune '{rune_name}' "
                            f"(valid: {', '.join(RUNES)})")
        altar = None
        for name, (kind, res, _p) in LOCATIONS.items():
            if kind == "altar" and res == rune_name:
                altar = name
        if altar is None or chebyshev(self.pos, LOCATIONS[altar][2]) > 1:
            raise GameError(f"stand next to the {rune_name.split('_')[0]} "
                            "altar to craft")
        spec = RUNES[rune_name]
        lvl = self.skill_level("runecrafting")
        if lvl < spec["req"]:
            raise GameError(f"{rune_name} needs runecrafting level "
                            f"{spec['req']}")
        have = self.inventory.get("rune_essence", 0)
        if have <= 0:
            raise GameError("no rune_essence - mine it from the essence rock")
        space = max(0, 28 - self.inv_count())
        made_total = 0
        k = min(have, max(1, space))
        extra_chance = min(RUNE_EXTRA_CAP,
                           (lvl - spec["req"]) * RUNE_EXTRA_CHANCE_STEP)
        for _ in range(k):
            made = 1 + (1 if self.rng.random() < extra_chance else 0)
            made_total += made
        self.inventory["rune_essence"] -= k
        if self.inventory["rune_essence"] <= 0:
            del self.inventory["rune_essence"]
        for _ in range(made_total):
            self.inv_add(rune_name, 1)
        self.add_xp("runecrafting", spec["xp"] * k)
        self.note(f"crafted {made_total}x {rune_name} from {k} essence")
        self.spend(2)
        self.advance(2)
        return made_total

    def thieve(self, stall_name):
        if stall_name not in STALLS:
            raise GameError(f"unknown stall '{stall_name}' "
                            f"(valid: {', '.join(STALLS)})")
        node = LOCATIONS.get(stall_name)
        if node is None or node[0] != "stall":
            raise GameError("stall is not on the map")
        if chebyshev(self.pos, node[2]) > 1:
            raise GameError("move next to the stall to steal from it")
        spec = STALLS[stall_name]
        lvl = self.skill_level("thieving")
        if lvl < spec["req"]:
            raise GameError(f"{stall_name} needs thieving level {spec['req']}")
        if self.stall_cd.get(stall_name, 0) > self.tick:
            raise GameError("the owner is still watching you - wait a bit")
        self.stall_cd[stall_name] = self.tick + spec["cooldown"]
        self.spend(2)
        success = min(0.95, max(0.05,
                                0.45 + (lvl - spec["req"]) * 0.02))
        stole = False
        if self.rng.random() < success:
            loot = []
            for item, chance, lo, hi in spec["loot"]:
                if self.rng.random() < chance:
                    n = self.rng.randint(lo, hi)
                    if item == "coins":
                        self.coins += n
                    elif not self.inv_add(item, n):
                        n = 0
                    if n > 0:
                        loot.append(f"{item} x{n}")
            self.add_xp("thieving", spec["xp"])
            stole = True
            self.note("you steal: " + (", ".join(loot) or "nothing"))
        else:
            self.note("caught red-handed - the owner shoos you away")
        self.advance(2)
        return stole

    # ------------- agility / farming / herblore / production -------------

    def run_lap(self):
        if chebyshev(self.pos, LOCATIONS["agility_course"][2]) > 1:
            raise GameError("stand next to the agility course to train")
        self.spend(AGILITY_LAP_TICKS)
        self.add_xp("agility", AGILITY_LAP_XP)
        self.energy = self.energy_cap
        self.note(f"completed an agility lap (energy restored to "
                  f"{int(self.energy_cap)})")
        self.advance(AGILITY_LAP_TICKS)
        return True

    def plant(self, seed_name):
        if seed_name not in HERBS:
            raise GameError(f"unknown seed '{seed_name}'")
        spec = HERBS[seed_name]
        lvl = self.skill_level("farming")
        if lvl < spec["req"]:
            raise GameError(f"{seed_name} needs farming level {spec['req']}")
        if self.inventory.get(seed_name, 0) <= 0:
            raise GameError(f"no {seed_name} in inventory")
        patch = None
        for name, (kind, _r, pos) in LOCATIONS.items():
            if kind == "patch" and chebyshev(self.pos, pos) <= 1 \
                    and name not in self.patches:
                patch = name
                break
        if patch is None:
            raise GameError("no free herb patch nearby (or all still growing)")
        self.inventory[seed_name] -= 1
        if self.inventory[seed_name] == 0:
            del self.inventory[seed_name]
        self.patches[patch] = {"seed": seed_name,
                               "ready_at": self.tick + spec["grow"]}
        self.note(f"planted {seed_name} at {patch}")
        self.spend(2)
        self.advance(2)
        return patch

    def harvest(self):
        ready = []
        for name, (kind, _r, pos) in LOCATIONS.items():
            if kind != "patch" or chebyshev(self.pos, pos) > 1:
                continue
            p = self.patches.get(name)
            if p and self.tick >= p["ready_at"]:
                ready.append((name, p))
        if not ready:
            raise GameError("no grown herbs nearby to harvest")
        name, p = ready[0]
        spec = HERBS[p["seed"]]
        lo, hi = spec["yield"]
        n = self.rng.randint(lo, hi)
        got = n
        if not self.inv_add(spec["crop"], n):
            got = 28 - self.inv_count()
            if got > 0:
                self.inv_add(spec["crop"], got)
        del self.patches[name]
        self.add_xp("farming", spec["xp"])
        self.note(f"harvested {got}x {spec['crop']}")
        self.spend(2)
        self.advance(2)
        return got

    def make_potion(self, potion_name):
        if potion_name not in POTIONS:
            raise GameError(f"unknown potion '{potion_name}' "
                            f"(valid: {', '.join(POTIONS)})")
        spec = POTIONS[potion_name]
        lvl = self.skill_level("herblore")
        if lvl < spec["req"]:
            raise GameError(f"{potion_name} needs herblore level "
                            f"{spec['req']}")
        if self.inventory.get("vial_of_water", 0) <= 0:
            raise GameError("need a vial_of_water (buy at the shop)")
        if self.inventory.get(spec["herb"], 0) <= 0:
            raise GameError(f"need a {spec['herb']} - grow it or get drops")
        self.inventory["vial_of_water"] -= 1
        if self.inventory["vial_of_water"] == 0:
            del self.inventory["vial_of_water"]
        self.inventory[spec["herb"]] -= 1
        if self.inventory[spec["herb"]] == 0:
            del self.inventory[spec["herb"]]
        if not self.inv_add(potion_name):
            raise GameError("inventory full")
        self.add_xp("herblore", spec["xp"])
        self.note(f"mixed a {potion_name}")
        self.spend(2)
        self.advance(2)
        return True

    def quaff(self, potion_name):
        if potion_name not in POTIONS:
            raise GameError(f"'{potion_name}' is not a potion")
        if self.inventory.get(potion_name, 0) <= 0:
            raise GameError(f"no {potion_name} in inventory")
        spec = POTIONS[potion_name]
        self.inventory[potion_name] -= 1
        if self.inventory[potion_name] == 0:
            del self.inventory[potion_name]
        skill = spec["boost_skill"]
        cur = self.buffs.get(skill, {})
        amt = cur.get("amt", 0) if self.tick < cur.get("until", 0) else 0
        self.buffs[skill] = {"amt": max(amt, spec["boost"]),
                             "until": self.tick + spec["ticks"]}
        self.note(f"drank a {potion_name} (+{spec['boost']} {skill} "
                  f"for {spec['ticks']} ticks)")
        self.spend(2)
        self.advance(2)
        return skill

    def fletch(self, log_item=None):
        candidates = [l for l in FLETCHING
                      if self.inventory.get(l, 0) > 0]
        if log_item is None:
            best = None
            for l in candidates:
                if self.skill_level("fletching") >= FLETCHING[l][1]:
                    if best is None or FLETCHING[l][1] > FLETCHING[best][1]:
                        best = l
            log_item = best
            if log_item is None:
                raise GameError("no logs you can fletch yet (need knife? "
                                "higher level logs?)")
        elif log_item not in FLETCHING:
            raise GameError(f"cannot fletch '{log_item}'")
        if "knife" not in self.tools:
            raise GameError("you need a knife to fletch (buy one)")
        bow, req, xp = FLETCHING[log_item]
        lvl = self.skill_level("fletching")
        if lvl < req:
            raise GameError(f"{bow} from {log_item} needs fletching "
                            f"level {req}")
        self.inventory[log_item] -= 1
        if self.inventory[log_item] == 0:
            del self.inventory[log_item]
        if bow not in self.tools:
            self.tools.append(bow)
            self.note(f"fletched a {bow} - you now wield it")
        else:
            self.inv_add(bow)
            self.note(f"fletched a {bow}")
        self.add_xp("fletching", xp)
        self.spend(3)
        self.advance(3)
        return bow

    def craft_leather(self, item):
        if item not in LEATHER:
            raise GameError(f"unknown leather item '{item}' "
                            f"(valid: {', '.join(LEATHER)})")
        spec = LEATHER[item]
        lvl = self.skill_level("crafting")
        if lvl < spec["req"]:
            raise GameError(f"{item} needs crafting level {spec['req']}")
        if "needle" not in self.tools:
            raise GameError("you need a needle (buy one)")
        if self.inventory.get("cowhide", 0) < spec["hides"]:
            raise GameError("need cowhide - kill cows")
        if self.inventory.get("thread", 0) < spec["thread"]:
            raise GameError("need thread (buy at the shop)")
        self.inventory["cowhide"] -= spec["hides"]
        if self.inventory["cowhide"] <= 0:
            self.inventory.pop("cowhide", None)
        self.inventory["thread"] -= spec["thread"]
        if self.inventory.get("thread", 0) <= 0:
            self.inventory.pop("thread", None)
        if item in UNIQUE_TOOLS and item not in self.tools:
            self.tools.append(item)
        else:
            self.inv_add(item)
        self.add_xp("crafting", spec["xp"])
        self.note(f"crafted a {item}")
        self.spend(3)
        self.advance(3)
        return item

    def assign_slayer(self):
        if chebyshev(self.pos, LOCATIONS["slayer_master"][2]) > 1:
            raise GameError("stand next to the slayer master for a task")
        if self.slayer_task and self.slayer_task["done"] < \
                self.slayer_task["need"]:
            t = self.slayer_task
            self.note(f"current task: kill {t['need']} {t['kind']}s "
                      f"({t['done']}/{t['need']})")
            return dict(t)
        kind, need = self.rng.choice(SLAYER_TASK_POOL)
        self.slayer_task = {"kind": kind, "need": need, "done": 0,
                            "complete": False}
        self.note(f"slayer task: kill {need} {kind}s")
        self.spend(1)
        self.advance(1)
        return dict(self.slayer_task)

    def claim_slayer(self):
        if chebyshev(self.pos, LOCATIONS["slayer_master"][2]) > 1:
            raise GameError("stand next to the slayer master to claim")
        t = self.slayer_task
        if not t or not (t["done"] >= t["need"] or t.get("complete")):
            raise GameError("no completed task to claim")
        self.coins += SLAYER_REWARD_COINS
        self.add_xp("slayer", SLAYER_REWARD_XP)
        self.slayer_task = None
        self.note(f"slayer reward: +{SLAYER_REWARD_COINS} coins, "
                  f"+{int(SLAYER_REWARD_XP)} slayer xp")
        self.spend(1)
        self.advance(1)
        return True

    def add_xp(self, skill, amount):
        before = self.skill_level(skill)
        self.xp[skill] += amount
        after = self.skill_level(skill)
        if after > before:
            self.note(f"level up! {skill} is now {after}")
            if self.kernel is not None:
                self.kernel.emit("level_up", skill=skill, level=after)

    def note(self, msg):
        self.log.append(f"[t{self.tick}] {msg}")

    def open_bank(self):
        if self.uim:
            raise GameError(
                "banks are disabled: you are an ULTIMATE Ironman - your 28-slot "
                "inventory is the only storage")
        if chebyshev(self.pos, LOCATIONS["bank"][2]) > 1:
            raise GameError("stand next to the bank to use it")
        self.spend(1)
        self.advance(1)

    def deposit_all(self):
        self.open_bank()
        for item, n in list(self.inventory.items()):
            self.bank_items[item] = self.bank_items.get(item, 0) + n
            del self.inventory[item]

    def deposit(self, item, n=None):
        self.open_bank()
        have = self.inventory.get(item, 0)
        if have == 0:
            raise GameError(f"no {item} in inventory")
        take = have if n is None else min(n, have)
        self.inventory[item] -= take
        if self.inventory[item] == 0:
            del self.inventory[item]
        self.bank_items[item] = self.bank_items.get(item, 0) + take

    def withdraw(self, item, n=None):
        self.open_bank()
        have = self.bank_items.get(item, 0)
        if have == 0:
            raise GameError(f"no {item} in bank")
        take = have if n is None else min(n, have)
        if not self.inv_add(item, take):
            raise GameError("inventory full")
        self.bank_items[item] -= take
        if self.bank_items[item] == 0:
            del self.bank_items[item]

    def sell(self, item, n=None):
        if chebyshev(self.pos, LOCATIONS["shop"][2]) > 1:
            raise GameError("stand next to the shop to trade")
        have = self.inventory.get(item, 0)
        if have == 0:
            raise GameError(f"no {item} to sell")
        take = have if n is None else min(n, have)
        price = SHOP_PRICES.get(item, 1)
        self.inventory[item] -= take
        if self.inventory[item] == 0:
            del self.inventory[item]
        self.coins += price * take
        self.spend(1)
        self.advance(1)
        return price * take

    def buy(self, item, n=1):
        if chebyshev(self.pos, LOCATIONS["shop"][2]) > 1:
            raise GameError("stand next to the shop to trade")
        if item in UNIQUE_TOOLS:
            if item in self.tools:
                raise GameError(f"you already own a {item}")
            price = SHOP_PRICES[item]
            if self.coins < price:
                raise GameError(f"need {price} coins, you have {self.coins}")
            self.coins -= price
            self.tools.append(item)
            self.note(f"bought {item}")
        elif item in SHOP_STOCK:
            n = max(1, int(n))
            cost = SHOP_PRICES[item] * n
            if self.coins < cost:
                raise GameError(f"need {cost} coins, you have {self.coins}")
            if not self.inv_add(item, n):
                raise GameError("inventory full")
            self.coins -= cost
            self.note(f"bought {n}x {item} (-{cost} coins)")
        else:
            raise GameError(f"the shop does not stock {item}")
        self.spend(1)
        self.advance(1)

    def drop(self, item, n=None):
        have = self.inventory.get(item, 0)
        if have == 0:
            raise GameError(f"no {item} to drop")
        take = have if n is None else min(n, have)
        self.inventory[item] -= take
        if self.inventory[item] == 0:
            del self.inventory[item]
        self.spend(1)
        self.advance(1)

    def wait(self, ticks=1):
        if ticks < 1:
            raise GameError("wait needs at least 1 tick")
        self.spend(ticks)
        self.advance(ticks)

    def state(self):
        inv_str = ", ".join(f"{k} x{v}" for k, v in self.inventory.items()) or "(empty)"
        skills = {s: {"level": self.skill_level(s), "xp": int(self.xp[s])} for s in SKILLS}
        nearby = []
        for name, (kind, res, pos) in LOCATIONS.items():
            d = chebyshev(self.pos, pos)
            status = ""
            if kind in ("tree", "rock"):
                if name in self.respawn_at:
                    status = f"(depleted, respawns ~t{self.respawn_at[name]})"
                else:
                    status = f"(hp {self.node_hp[name]})"
            elif kind == "stall":
                if self.stall_cd.get(name, 0) > self.tick:
                    status = "(owner watching)"
                else:
                    status = "(unguarded)"
            elif kind == "patch":
                p = self.patches.get(name)
                if not p:
                    status = "(empty)"
                elif self.tick >= p["ready_at"]:
                    status = f"(ready {HERBS[p['seed']]['crop']})"
                else:
                    status = f"(growing, ~{p['ready_at'] - self.tick}t)"
            nearby.append({"name": name, "kind": kind, "resource": res,
                           "pos": pos, "distance": d, **{"status": status}})
        recent_log = self.log[-12:]
        active_buffs = {s: f"+{b['amt']} ({b['until'] - self.tick}t)"
                        for s, b in self.buffs.items()
                        if self.tick < b.get("until", 0)}
        task = dict(self.slayer_task) if self.slayer_task else None
        return {
            "tick": self.tick,
            "ticks_left": self.ticks_left,
            "position": self.pos,
            "coins": self.coins,
            "hp": {"current": self.hp, "max": self.max_hp},
            "combat_style": self.combat_style,
            "inventory": inv_str,
            "inventory_slots_used": self.inv_count(),
            "skills": skills,
            "tools": list(self.tools),
            "buffs": active_buffs,
            "slayer_task": task,
            "mode": "ultimate_ironman" if self.uim else "normal",
            "energy": round(self.energy, 1),
            "run": self.run,
            "quests": dict(self.quests),
            "bank_contents": ("LOCKED - no bank access in Ultimate Ironman"
                              if self.uim else dict(self.bank_items)),
            "nodes": nearby,
            "npcs": self.npcs(),
            "events": recent_log,
        }

    def peak_window_rate(self, window=150):
        tl = self.xp_timeline
        best = 0.0
        j = 0
        for i, (t_i, xp_i) in enumerate(tl):
            while j < i and t_i - tl[j][0] > window:
                j += 1
            if t_i - tl[j][0] > 0:
                rate = (xp_i - tl[j][0 + 1]) / (t_i - tl[j][0])
                best = max(best, rate)
        return best

    def score_task(self, task):
        self._last_scored_task = task
        start_coins = self.coin_timeline[0][1]
        result = {
            "task": task,
            "ticks_used": self.tick,
            "total_xp": int(self.total_xp),
            "xp_breakdown": {s: int(v) for s, v in self.xp.items()},
            "coins": self.coins,
            "coins_gained": self.coins - start_coins,
            "peak_xp_per_tick": round(self.peak_window_rate(), 3),
            "levels": {s: self.skill_level(s) for s in SKILLS},
            "events": self.log[-25:],
        }
        if task == "wc_xp":
            result["score"] = int(self.xp["woodcutting"])
        elif task == "gold":
            result["score"] = self.coins - start_coins
        elif task == "total_xp":
            result["score"] = int(self.total_xp)
        elif task == "cook_xp":
            result["score"] = int(self.xp["cooking"])
        else:
            result["score"] = int(self.total_xp)
        return result
