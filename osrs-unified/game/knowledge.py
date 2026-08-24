import importlib


def _fmt(v):
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_fmt(x)}" for k, x in v.items())
    return str(v)


def _table(rows, columns=None):
    if not rows:
        return "(none)"
    if not isinstance(rows[0], dict):
        rows = [{"value": r} for r in rows]
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    if columns:
        keys = columns + [k for k in keys if k not in columns]
    head = "| " + " | ".join(keys) + " |"
    sep = "|" + "|".join("-" * (len(k) + 2) for k in keys) + "|"
    body = ["| " + " | ".join(_fmt(r.get(k, "")) for k in keys) + " |"
            for r in rows]
    return "\n".join([head, sep] + body)


def _drops(loot):
    parts = []
    for item in loot:
        name, chance, lo, hi = item
        pct = f"{chance * 100:.0f}%"
        rng = f"({lo}-{hi})" if hi != lo else f"x{lo}"
        parts.append(f"{name} {pct} {rng}")
    return "; ".join(parts)


def collect(world_module=None):
    W = world_module or importlib.import_module("game.world")
    C = importlib.import_module("game.content")
    S = importlib.import_module("game.sdk")

    skills = list(W.SKILLS)
    locations = [{"place": n, "kind": k, "resource": r or "", "pos": p}
                 for n, (k, r, p) in W.LOCATIONS.items()]

    sections = {
        "overview": {
            "grid": W.GRID,
            "skills": skills,
            "tick_seconds": 0.6,
            "hitpoints_start_xp": C.HITPOINTS_START_XP,
            "max_energy": "100 + 2 x agility level",
            "shop_sell_and_buy": True,
        },
        "gathering_trees": [
            {"node": k, **v} for k, v in W.TREES.items()],
        "gathering_rocks": [
            {"rock": k, **v} for k, v in W.ROCKS.items()],
        "gathering_fishing": [
            {"spot": k, **v} for k, v in getattr(W, "FISH", {}).items()],
        "cooking": [
            {"raw": k, **v} for k, v in W.COOKABLES.items()],
        "smelting": [
            {"bar": k,
             "ores": "+".join(v["ores"]),
             **{kk: vv for kk, vv in v.items() if kk != "ores"},
             "fail": ("iron loses ore on fail; fail chance falls 2%/level "
                      if k == "iron_bar" else "never fails")}
            for k, v in W.SMELTING.items()],
        "firemaking": [
            {"log": k, "xp": v} for k, v in W.FIREMAKING_XP.items()],
        "fletching": [
            {"log": k, "product": v[0], "req": v[1], "xp": v[2]}
            for k, v in C.FLETCHING.items()],
        "crafting_leather": [
            {"item": k, **v} for k, v in C.LEATHER.items()],
        "farming_herbs": [
            {"seed": k, **v} for k, v in C.HERBS.items()],
        "herblore_potions": [
            {"potion": k, **v} for k, v in C.POTIONS.items()],
        "agility": {"lap_ticks": C.AGILITY_LAP_TICKS,
                    "lap_xp": C.AGILITY_LAP_XP,
                    "max_energy_bonus_per_level": C.ENERGY_PER_AGILITY},
        "construction_planks": [
            {"log": k, "plank": v, "sawmill_fee": C.SAWMILL_FEE[k]}
            for k, v in C.PLANKS.items()],
        "construction_furniture": [
            {"furniture": k,
             "mats": _fmt(v["mats"]),
             **{kk: vv for kk, vv in v.items() if kk != "mats"}}
            for k, v in C.CONSTRUCTION.items()],
        "hunter_birds": [
            {"bird": k, **v} for k, v in getattr(C, "BIRDS", {}).items()],
        "thieving_stalls": [
            {"stall": k, **v, "loot": _drops(v["loot"])}
            for k, v in C.STALLS.items()],
        "runecrafting": [
            {"rune": k, **v} for k, v in C.RUNES.items()],
        "magic_spells": [
            {"spell": k, "runes": _fmt(v.pop("runes", "")), **v}
            for k, v in (dict(C.SPELLS)).items()],
        "combat_styles_trained_skill": dict(C.COMBAT_STYLES),
        "melee_weapons": [
            {"weapon": k, "attack_bonus": v[0], "strength_bonus": v[1],
             "req": v[2]} for k, v in C.WEAPONS.items()],
        "armours": [
            {"armour": k, "req": v[0], "defence_bonus": v[1]}
            for k, v in C.ARMOURS.items()],
        "bows": [
            {"bow": k, "req": v[0], "bonus": v[1]}
            for k, v in C.BOWS.items()],
        "arrows": [
            {"arrow": k, "req": v[0], "damage_bonus": v[1]}
            for k, v in C.ARROWS.items()],
        "food_heals": dict(C.FOOD),
        "bones": {"bury_xp": C.BONES_BURY_XP,
                  "offer_at_shrine_xp": C.BONES_OFFER_XP},
        "prayer_defence_factor_per_level": C.PRAYER_DEFENCE_FACTOR,
        "slayer": {"task_pool": _fmt(C.SLAYER_TASK_POOL),
                   "xp_per_task_kill": C.SLAYER_XP_PER_TASK_KILL,
                   "reward_xp": C.SLAYER_REWARD_XP,
                   "reward_coins": C.SLAYER_REWARD_COINS},
        "npcs": [
            {"npc": k, **{kk: (_drops(vv) if kk == "drops" else vv)
                          for kk, vv in v.items()}}
            for k, v in C.NPCS.items()],
        "npc_spawns": [
            {"spawn": n, "npc": k, "pos": p}
            for n, (k, p) in C.NPC_SPAWNS.items()],
        "map_locations": locations,
        "economy_shop_prices": dict(W.SHOP_PRICES),
        "economy_shop_stock": list(W.SHOP_STOCK),
        "quests": [
            {"quest": q, "bring": f"{s['amount']}x {s['item']}",
             "reward": f"+{s['xp_reward']:g} {s['skill']} xp, "
                       f"+{s['coin_reward']} coins"}
            for q, s in W.QUESTS.items()],
        "sdk_methods": sorted(
            m for m in dir(S.GameSDK) if not m.startswith("_")),
    }
    return sections


_ORDER = ["overview", "gathering_trees", "gathering_rocks", "gathering_fishing",
          "cooking", "smelting", "firemaking", "fletching", "crafting_leather",
          "farming_herbs", "herblore_potions", "agility",
          "construction_planks", "construction_furniture", "hunter_birds",
          "thieving_stalls",
          "runecrafting", "magic_spells", "combat_styles_trained_skill",
          "melee_weapons", "armours", "bows", "arrows", "food_heals", "bones",
          "prayer_defence_factor_per_level", "slayer", "npcs", "npc_spawns",
          "map_locations", "economy_shop_prices", "economy_shop_stock",
          "quests"]

_TITLES = {
    "overview": "World overview",
    "gathering_trees": "Trees (chop)",
    "gathering_rocks": "Rocks (mine)",
    "gathering_fishing": "Fishing",
    "cooking": "Cooking (at range)",
    "smelting": "Smelting (at furnace)",
    "firemaking": "Firemaking (anywhere)",
    "fletching": "Fletching (knife on logs)",
    "crafting_leather": "Crafting leather (needle+thread on cowhide)",
    "farming_herbs": "Farming herbs (seeds at herb patches)",
    "herblore_potions": "Herblore potions",
    "agility": "Agility course",
    "construction_planks": "Construction planks (sawmill at workshop)",
    "construction_furniture": "Construction furniture (build at workshop)",
    "hunter_birds": "Hunter birds (bird snares at hunting ground)",
    "thieving_stalls": "Thieving stalls",
    "runecrafting": "Runecrafting (essence at altars)",
    "magic_spells": "Magic spells (cast)",
    "combat_styles_trained_skill": "Combat styles -> skill trained",
    "melee_weapons": "Melee weapons (equip)",
    "armours": "Armours (equip)",
    "bows": "Bows (equip)",
    "arrows": "Arrows (equip for ranged)",
    "food_heals": "Food healing",
    "bones": "Bones",
    "slayer": "Slayer (assign/claim at slayer master)",
}


def render_markdown(sections=None, world_module=None):
    data = sections or collect(world_module)
    out = ["# MIND generated game knowledge (auto-derived from live "
           "registries)", ""]
    for key in _ORDER:
        if key not in data:
            continue
        title = _TITLES.get(key, key.replace("_", " ").title())
        v = data[key]
        out.append(f"\n## {title}")
        if isinstance(v, dict):
            rows = []
            for k, val in v.items():
                if isinstance(val, dict):
                    rows.append({**{"name": k}, **val})
                else:
                    rows.append({"name": k, "value": _fmt(val)})
            out.append(_table(rows))
        elif isinstance(v, list):
            out.append(_table(v))
        else:
            out.append(str(v))
    out.append("\n## SDK methods")
    out.append(", ".join(data.get("sdk_methods", [])))
    return "\n".join(out)
