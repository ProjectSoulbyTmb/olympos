from .content import NPC_SPAWNS
from .world import GRID, LOCATIONS, SHOP_PRICES, SHOP_STOCK, XP_TABLE, \
    GameError


class GameSDK:
    """The only object strategy snippets receive. Each action advances
    the tick clock; a 3000-tick budget is enforced by the world."""

    _VALID = ("state()", "skills(name=None)", "inventory()", "coins()",
              "ticks_left()", "log()", "quest_status()", "quest(q=None)",
              "shop_prices()", "shop_stock()", "npcs()",
              "get_location()", "move_to(x,y)", "walk(name)", "chop()",
              "cut_log()", "mine()", "mine_ore()", "fish()", "catch_fish()",
              "cook(raw=None)", "light_fire()", "smelt(bar)",
              "attack(npc)", "eat(food)", "set_combat_style(style)",
              "cast(spell,npc)", "bury_bones()", "offer_bones()",
              "craft_rune(rune)", "thieve(stall)",
              "run_lap()", "plant(seed)", "harvest()",
              "make_potion(p)", "quaff(p)", "fletch(log=None)",
              "craft_leather(item)", "assign_slayer()", "claim_slayer()",
              "ge_price(item)", "tools()", "bank()", "claims()",
              "search_chest()", "set_energy_regen(rate)",
              "talk_quest(q=None)", "deposit_all()", "deposit(i,n=None)",
              "withdraw(i,n=None)", "sell(i,n=None)", "buy(item,n=1)",
              "drop(i,n=None)", "wait(t)", "set_run(bool)",
              "get_score(task='total_xp')")

    def __init__(self, world):
        self._w = world

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise GameError(
            f"game.{name} does not exist. Valid members: "
            f"{', '.join(self._VALID)}")

    def state(self):
        return self._w.state()

    def skills(self, name=None):
        if name is None:
            return {s: self._w.skill_level(s) for s in self._w.xp}
        key = str(name).lower()
        if key not in self._w.xp:
            raise GameError(f"unknown skill '{name}' (valid: "
                            f"{', '.join(sorted(self._w.xp))})")
        return self._w.skill_level(key)

    def inventory(self):
        return dict(self._w.inventory)

    def get_location(self):
        pos = tuple(self._w.pos)
        best, best_d = None, None
        for name, spec in LOCATIONS.items():
            d = max(abs(pos[0] - spec[2][0]), abs(pos[1] - spec[2][1]))
            if best_d is None or d < best_d:
                best, best_d = name, d
        return {"pos": [pos[0], pos[1]], "nearest": best,
                "distance": int(best_d)}

    def tools(self):
        owned = list(getattr(self._w, "tools", []))
        return {
            "axes": [t for t in owned if t.endswith("_axe")],
            "pickaxes": [t for t in owned if t.endswith("_pickaxe")],
            "weapons": [t for t in owned if t.endswith("_sword")
                        or t.endswith("bow")],
            "other": [t for t in owned
                      if not (t.endswith("_axe") or t.endswith("_pickaxe")
                              or t.endswith("_sword") or t.endswith("bow"))],
        }

    def bank(self):
        return dict(self._w.bank_items)

    def claims(self):
        return sorted(getattr(self._w, "claims", set()))

    def search_chest(self):
        return self._w.search_chest()

    def set_energy_regen(self, rate):
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            raise GameError("set_energy_regen(rate) needs a number")
        clamped = max(0.5, min(2.0, rate))
        self._w.energy_regen_mult = clamped
        return clamped

    def quest(self, q=None):
        status = self._w.quest_status()
        if q is None:
            return dict(status)
        key = str(q)
        if key not in status:
            raise GameError(f"unknown quest '{q}' (valid: "
                            f"{', '.join(sorted(status))})")
        return status[key]

    def cut_log(self):
        return self.chop()

    def mine_ore(self):
        return self.mine()

    def catch_fish(self):
        return self.fish()

    def get_score(self, task="total_xp"):
        return self._w.score_task(str(task))

    def coins(self):
        return self._w.coins

    def ticks_left(self):
        return self._w.ticks_left

    def log(self):
        return list(self._w.log)

    def move_to(self, x, y):
        return self._w.move_to(int(x), int(y))

    def walk(self, place_name):
        if place_name in LOCATIONS:
            x, y = LOCATIONS[place_name][2]
        elif place_name in NPC_SPAWNS:
            x, y = NPC_SPAWNS[place_name][1]
        else:
            raise KeyError(f"unknown place '{place_name}' "
                           f"(valid: {', '.join(list(LOCATIONS) + list(NPC_SPAWNS))})")
        return self._w.move_to(int(x), int(y))

    def chop(self):
        return self._w.chop()

    def mine(self):
        return self._w.mine()

    def fish(self):
        return self._w.fish()

    def cook(self, raw_item=None):
        return self._w.cook(raw_item)

    def deposit_all(self):
        self._w.deposit_all()

    def deposit(self, item, n=None):
        self._w.deposit(item, n)

    def withdraw(self, item, n=None):
        self._w.withdraw(item, n)

    def sell(self, item, n=None):
        return self._w.sell(item, n)

    def buy(self, item, n=None):
        self._w.buy(item, int(n) if n else 1)

    def set_run(self, on):
        self._w.set_run(bool(on))

    def light_fire(self):
        return self._w.light_fire()

    def smelt(self, bar):
        return self._w.smelt(bar)

    def talk_quest(self, quest=None):
        self._w.talk_quest(quest)

    def quest_status(self):
        return self._w.quest_status()

    def drop(self, item, n=None):
        self._w.drop(item, n)

    def wait(self, ticks=1):
        self._w.wait(ticks)

    def shop_prices(self):
        return dict(SHOP_PRICES)

    def shop_stock(self):
        return list(SHOP_STOCK)

    def npcs(self):
        return self._w.npcs()

    def attack(self, npc_name):
        return self._w.attack(str(npc_name))

    def eat(self, item):
        return self._w.eat(str(item))

    def set_combat_style(self, style):
        self._w.set_combat_style(str(style))

    def cast(self, spell, npc_name):
        return self._w.cast(str(spell), str(npc_name))

    def bury_bones(self):
        return self._w.bury_bones()

    def offer_bones(self):
        return self._w.offer_bones()

    def craft_rune(self, rune):
        return self._w.craft_rune(str(rune))

    def thieve(self, stall):
        return self._w.thieve(str(stall))

    def run_lap(self):
        return self._w.run_lap()

    def plant(self, seed):
        return self._w.plant(str(seed))

    def harvest(self):
        return self._w.harvest()

    def make_potion(self, potion):
        return self._w.make_potion(str(potion))

    def quaff(self, potion):
        return self._w.quaff(str(potion))

    def fletch(self, log=None):
        return self._w.fletch(str(log) if log else None)

    def craft_leather(self, item):
        return self._w.craft_leather(str(item))

    def assign_slayer(self):
        return self._w.assign_slayer()

    def claim_slayer(self):
        return self._w.claim_slayer()

    def ge_price(self, item):
        """Live Grand Exchange price from the updater snapshot (or None)."""
        from .market import ge_price
        return ge_price(str(item))


def build_sdk_docs():
    return """## SDK reference (the `game` object in run(game))
ALL accessors are METHODS with parentheses: game.skills() NOT game.skills.
Valid members: state() skills() inventory() coins() ticks_left() log()
quest_status() move_to(x,y) walk(name) chop() mine() fish() cook(raw=None)
light_fire() smelt(bar) talk_quest(q=None) quest_status() deposit_all()
deposit(i,n=None) withdraw(i,n=None) sell(i,n=None) buy(item,n=1)
drop(i,n=None) wait(t) set_run(bool) shop_prices() shop_stock() npcs()
attack(npc) eat(food) set_combat_style(style) cast(spell,npc)
bury_bones() offer_bones() craft_rune(rune) thieve(stall)
run_lap() plant(seed) harvest() make_potion(p) quaff(p) fletch(log=None)
craft_leather(item) assign_slayer() claim_slayer()
- game.state() -> full snapshot: position, coins, hp{current,max},
  combat_style, inventory (str), skills (21), buffs{}, slayer_task,
  nodes[], npcs[], events[]
- game.skills() -> 21 skills incl. combat, prayer, ranged, magic,
  runecrafting, thieving, agility, herblore, crafting, fletching,
  slayer, farming
New loops:
- game.run_lap()            30 ticks at the course: agility xp + energy refilled (cap rises with agility level)
- game.plant("guam_seed") / game.harvest()   at herb patches; herbs grow over ticks
- game.make_potion("attack_potion")  herb + vial_of_water; then game.quaff(...) for a timed combat buff
- game.fletch()             knife + logs -> bows (oak_bow at lvl 20)
- game.craft_leather("leather_body")  needle + thread + cowhide -> armour (reduces enemy accuracy/damage when worn)
- game.assign_slayer() / game.claim_slayer()  task loop at the slayer master: kill N of a kind, claim coins+xp
Combat:
- game.npcs() -> list of {name, kind, level, pos, distance, status}
- game.attack("goblin_1")   melee adjacent; style "ranged" shoots to 3
  tiles (needs shortbow + arrows); returns
  {player_damage, killed, drops|retaliation_damage}
- game.cast("wind_strike"|"fire_strike", npc)  range 4 tiles; needs runes;
  magic xp = base + 2/damage; hitpoints +1.33/damage
- game.eat("shrimp")        3 ticks, heals 3 hp (also cooked_meat, cake)
- game.set_combat_style("accurate|aggressive|defensive|ranged")
  Prayer level passively lowers enemy accuracy.
Prayer:
- game.bury_bones()         1 tick, +4.5 prayer xp per bones
- game.offer_bones()        at the shrine: all bones at 13.5 xp each
Runecrafting:
- mine rune_essence from the essence rock (east zone), then:
- game.craft_rune("air_rune")  or "fire_rune" at the matching altar;
  bonus runes at higher levels
Thieving:
- game.thieve("fruit_stall") lvl 5 / ("cake_stall") lvl 15; cooldown while
  the owner watches
Death = safe respawn with items. Shop stocks bows/arrows/runes/cake.
Movement:
- game.move_to(x, y) -> walks (1 tick/tile; 2 tiles/tick with run, drains energy)
- game.set_run(True|False) -> run mode toggle; idle regen 0.5 energy/tick
- game.walk("tree_1"|"tree_2"|"tree_oak"|"rock_copper"|"rock_tin"|
             "rock_iron"|"fishing_spot_1"|"range"|"bank"|"shop"|
             "furnace"|"quest_giver")
Skilling (each attempt = 4 ticks; returns True if an item landed in inventory):
- game.chop()   must stand next to a tree node
- game.mine()   next to a rock node
- game.fish()   next to fishing_spot_1
Combat:
- game.npcs() -> list of {name, kind, level, pos, distance, status}
- game.attack("goblin_1")   4 ticks, must be adjacent; returns
  {player_damage, killed, drops|retaliation_damage}
- game.eat("shrimp")        3 ticks, heals 3 hp (also "cooked_meat")
- game.set_combat_style("accurate"|"aggressive"|"defensive")
  accurate->attack xp, aggressive->strength xp, defensive->defence xp;
  hitpoints always gains 1.33 xp per damage dealt. Death = respawn at
  spawn, items kept. Buy swords at the shop (bronze 20 / iron 90 /
  steel 400 coins).
Processing:
- game.cook()          2 ticks, at the range, cooks first raw item found
- game.light_fire()    2 ticks, burns one logs/oak_logs for firemaking xp
- game.smelt("bronze_bar")  4 ticks at furnace; needs copper_ore+tin_ore
- game.smelt("iron_bar")    4 ticks; needs iron_ore; may fail and lose the ore
Quests (stand next to quest_giver):
- game.talk_quest()    accept/turn in all quests automatically
- game.quest_status()  {"shrimp_fetch": "not_started|active|claimed", ...}
  shrimp_fetch: 5 cooked shrimps -> +300 cooking xp +50 coins
  logs_fetch: 10 logs -> +500 woodcutting xp +80 coins
Banking (must be adjacent to bank):
- game.deposit_all() / game.deposit(item, n=None) / game.withdraw(item, n=None)
Shop (adjacent to shop):
- game.sell(item, n=None) -> returns coins received
- game.buy("iron_axe"|...|"steel_sword") (one-off tools/weapons)
Other:
- game.drop(item, n=None) / game.wait(ticks)
- game.log() -> recent event messages
Introspection (safe to call anywhere):
- game.skills("woodcutting")  -> int level for one skill; game.skills() -> all
- game.get_location()         -> {"pos": [x,y], "nearest": place, "distance": n}
- game.tools()                -> {"axes": [...], "pickaxes": [...],
                                  "weapons": [...], "other": [...]}
- game.bank()                 -> dict of bank contents (what you deposited)
- game.quest("logs_fetch")    -> status string of one quest; quest() -> all
- game.get_score(task="total_xp") -> live scoring snapshot incl. "score"
- game.claims()               -> one-time claims done, e.g. ["stronghold_chest"]
Stronghold of Security (walk target "stronghold_of_security"):
- game.search_chest()   stand next to the chest; one time per session gives
  +500 coins. Returns True on first claim, False afterwards.
Energy:
- game.set_energy_regen(1.5)  idle regen multiplier, clamped to [0.5, 2.0]
Aliases: cut_log()==chop(), mine_ore()==mine(), catch_fish()==fish()."""
