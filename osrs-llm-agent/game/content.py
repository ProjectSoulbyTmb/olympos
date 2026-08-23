"""Content tables for the OSRS Lab engine.

All numbers are original implementations modelled on publicly known
Old School RuneScape game mechanics. No Jagex assets or code are used.
"""

# ---------------------------------------------------------------- combat --
COMBAT_STYLES = {
    "accurate": "attack",
    "aggressive": "strength",
    "defensive": "defence",
    "ranged": "ranged",
}

WEAPONS = {
    # weapon: (attack_bonus, strength_bonus, level_req)
    "bronze_sword": (4, 3, 1),
    "iron_sword": (8, 6, 1),
    "steel_sword": (12, 9, 5),
}

BOWS = {
    # bow: (level_req, accuracy/damage bonus)
    "shortbow": (1, 0),
    "oak_bow": (15, 2),
}

ARROWS = {
    # arrow: (level_req, ranged_strength_bonus)
    "bronze_arrow": (1, 2),
}

SPELLS = {
    # spell: level_req, runes consumed per cast, max hit, base xp
    "wind_strike": {"req": 1, "runes": {"air_rune": 1},
                    "max_hit": 3, "base_xp": 5.5},
    "fire_strike": {"req": 17, "runes": {"fire_rune": 1},
                    "max_hit": 6, "base_xp": 11.0},
}

FOOD = {
    # food: hitpoints restored per OSRS mechanics
    "shrimp": 3,
    "cooked_meat": 3,
    "cake": 4,
}

# ------------------------------------------------------------------ npcs --
NPCS = {
    # npc: level, hp, max_hit, defence_rating, respawn_ticks, drops
    # drops: [(item_or_"coins", chance, min, max), ...]
    "goblin": {"level": 2, "hp": 5, "max_hit": 1, "accuracy": 5,
               "respawn": 20,
               "drops": [("coins", 1.0, 5, 24)]},
    "cow": {"level": 2, "hp": 8, "max_hit": 1, "accuracy": 4,
            "respawn": 25,
            "drops": [("raw_beef", 1.0, 1, 2), ("bones", 1.0, 1, 1),
                      ("cowhide", 0.9, 1, 1), ("coins", 0.4, 2, 8)]},    "giant_rat": {"level": 3, "hp": 6, "max_hit": 1, "accuracy": 8,
                  "respawn": 20,
                  "drops": [("coins", 1.0, 3, 16)]},
    "zombie": {"level": 7, "hp": 22, "max_hit": 2, "accuracy": 10,
               "respawn": 25,
               "drops": [("bones", 1.0, 1, 1), ("coins", 0.85, 10, 40),
                         ("bronze_arrow", 0.35, 4, 12),
                         ("guam_seed", 0.15, 1, 2)]},
    "guard": {"level": 9, "hp": 25, "max_hit": 3, "accuracy": 12,
              "respawn": 30,
              "drops": [("bones", 1.0, 1, 1), ("coins", 1.0, 20, 60),
                        ("iron_arrow", 0.30, 5, 14),
                        ("tarromin_seed", 0.12, 1, 1)]},
}

ARROWS["iron_arrow"] = (5, 4)

NPC_SPAWNS = {
    "goblin_1": ("goblin", (4, 6)),
    "goblin_2": ("goblin", (12, 12)),
    "cow_1": ("cow", (14, 12)),
    "cow_2": ("cow", (3, 14)),
    "giant_rat_1": ("giant_rat", (1, 4)),
    "zombie_1": ("zombie", (21, 3)),
    "zombie_2": ("zombie", (22, 9)),
    "guard_1": ("guard", (17, 18)),
    "guard_2": ("guard", (22, 21)),
}

# ------------------------------------------------------------- gathering --
TREES_EXTRA = {
    "willow": {"req": 30, "xp": 67.5, "hp": 14, "respawn": 30,
               "item": "willow_logs"},
}
ROCKS_EXTRA = {
    "coal": {"req": 30, "xp": 50.0, "hp": 10, "respawn": 30,
             "item": "coal"},
    "essence": {"req": 1, "xp": 5.0, "hp": 99, "respawn": 4,
                "item": "rune_essence", "base": 0.85},
}
FIREMAKING_XP_EXTRA = {"willow_logs": 90.0}
COOKABLES_EXTRA = {}

# --------------------------------------------------------------- prayer --
BONES_BURY_XP = 4.5          # per OSRS bones
BONES_OFFER_XP = 13.5        # 3x at the shrine
PRAYER_DEFENCE_FACTOR = 0.003  # npc accuracy reduction per prayer level

# ---------------------------------------------------------- runecrafting --
RUNES = {
    # rune: altar_level_req, xp_per_essence
    "air_rune": {"req": 1, "xp": 5.0},
    "fire_rune": {"req": 14, "xp": 7.0},
}
RUNE_EXTRA_CHANCE_STEP = 0.02   # +chance of a bonus rune per level over req
RUNE_EXTRA_CAP = 0.9

# -------------------------------------------------------------- thieving --
STALLS = {
    # stall: level_req, cooldown_ticks, xp, drops
    "fruit_stall": {"req": 5, "cooldown": 10, "xp": 10.0,
                    "loot": [("coins", 1.0, 10, 30)]},
    "cake_stall": {"req": 15, "cooldown": 14, "xp": 16.0,
                   "loot": [("cake", 1.0, 1, 1), ("coins", 0.5, 5, 15)]},
}

# ------------------------------------------------------------ smithing --
SMELTING_EXTRA = {
    "steel_bar": {"ores": ("iron_ore", "coal", "coal"), "req": 30,
                  "xp": 17.5, "item": "steel_bar"},
}

# ---------------------------------------------------------------- quests --
QUESTS_EXTRA = {
    "rune_fetch": {
        "item": "air_rune", "amount": 10, "skill": "runecrafting",
        "xp_reward": 700.0, "coin_reward": 150,
        "description": "bring 10 air runes to the quest giver",
    },
    "herbal_remedy": {
        "item": "attack_potion", "amount": 2, "skill": "herblore",
        "xp_reward": 800.0, "coin_reward": 200,
        "description": "bring 2 attack potions to the quest giver",
    },
}

# ------------------------------------------------------------- starting --
HITPOINTS_START_XP = 1154     # Hitpoints starts at level 10 like OSRS

# --------------------------------------------------------------- armour --
ARMOURS = {
    # piece: (level_req, defence_bonus)
    "leather_gloves": (1, 1),
    "leather_body": (1, 4),
    "bronze_chainbody": (5, 7),
    "iron_chainbody": (15, 10),
    "steel_chainbody": (25, 13),
}
ARMOUR_ACC_REDUCTION = 0.02   # enemy accuracy loss per defence-bonus point
ARMOUR_BLOCK_DIVISOR = 8      # every 8 points blocks 1 damage

# -------------------------------------------------------------- potions --
POTIONS = {
    # potion: herblore_req, herb, xp, stat boosted, amount, duration ticks
    "attack_potion": {"req": 3, "herb": "guam_leaf", "xp": 25.0,
                      "boost_skill": "attack", "boost": 3, "ticks": 60},
    "strength_potion": {"req": 12, "herb": "tarromin_leaf", "xp": 42.0,
                        "boost_skill": "strength", "boost": 3, "ticks": 60},
    "defence_potion": {"req": 20, "herb": "ranarr_leaf", "xp": 60.0,
                       "boost_skill": "defence", "boost": 3, "ticks": 60},
}

HERBS = {
    # seed: farming_req, crop, grow_ticks, harvest_xp, yield range
    "guam_seed": {"req": 1, "crop": "guam_leaf", "grow": 60,
                  "xp": 12.0, "yield": (1, 3)},
    "tarromin_seed": {"req": 14, "crop": "tarromin_leaf", "grow": 90,
                      "xp": 18.0, "yield": (1, 3)},
    "ranarr_seed": {"req": 26, "crop": "ranarr_leaf", "grow": 120,
                    "xp": 24.0, "yield": (1, 2)},
}

# ------------------------------------------------------------ fletching --
FLETCHING = {
    # log: (bow produced, fletching_req, xp)
    "logs": ("shortbow", 5, 10.0),
    "oak_logs": ("oak_bow", 20, 17.5),
    "willow_logs": ("oak_bow", 30, 21.5),
}

# ------------------------------------------------------------- crafting --
LEATHER = {
    # product: hides needed, threads needed, crafting_req, xp
    "leather_gloves": {"hides": 1, "thread": 1, "req": 1, "xp": 13.8},
    "leather_body": {"hides": 1, "thread": 1, "req": 14, "xp": 27.0},
}

# -------------------------------------------------------------- agility --
AGILITY_LAP_TICKS = 30
AGILITY_LAP_XP = 48.0
ENERGY_PER_AGILITY = 2        # energy cap = 100 + 2*agility level

# --------------------------------------------------------------- slayer --
SLAYER_TASK_POOL = [
    # (npc_kind, kill_count)
    ("goblin", 5), ("cow", 5), ("giant_rat", 6),
    ("zombie", 8), ("guard", 10),
]
SLAYER_XP_PER_TASK_KILL = 15.0
SLAYER_REWARD_COINS = 100
SLAYER_REWARD_XP = 200.0

# ------------------------------------------------------- world content --
# Single source of truth for every game-data table. world.py re-exports
# these names so existing imports keep working.

TREES = {
    "tree": {"req": 1, "xp": 25.0, "hp": 8, "respawn": 15, "item": "logs"},
    "oak": {"req": 15, "xp": 37.5, "hp": 12, "respawn": 25, "item": "oak_logs"},
}
ROCKS = {
    "copper": {"req": 1, "xp": 17.5, "hp": 6, "respawn": 10, "item": "copper_ore"},
    "tin": {"req": 1, "xp": 17.5, "hp": 6, "respawn": 10, "item": "tin_ore"},
    "iron": {"req": 15, "xp": 35.0, "hp": 9, "respawn": 20, "item": "iron_ore"},
}
FISH = {
    "shrimp": {"req": 1, "xp": 10.0, "item": "raw_shrimp"},
}
COOKABLES = {
    "raw_shrimp": {"req": 1, "xp": 30.0, "item": "shrimp", "stop_burn": 34},
    "raw_beef": {"req": 1, "xp": 30.0, "item": "cooked_meat", "stop_burn": 31},
}
AXES = {"bronze_axe": 0.0, "iron_axe": 0.05, "steel_axe": 0.10}
PICKAXES = {"bronze_pickaxe": 0.0, "iron_pickaxe": 0.05, "steel_pickaxe": 0.10}

FIREMAKING_XP = {"logs": 40.0, "oak_logs": 60.0, **FIREMAKING_XP_EXTRA}
SMELTING = {
    "bronze_bar": {"ores": ("copper_ore", "tin_ore"), "req": 1,
                   "xp": 6.2, "item": "bronze_bar"},
    "iron_bar": {"ores": ("iron_ore",), "req": 15,
                 "xp": 12.5, "item": "iron_bar"},
}

QUESTS = {
    "shrimp_fetch": {
        "item": "shrimp", "amount": 5, "skill": "cooking",
        "xp_reward": 300.0, "coin_reward": 50,
        "description": "bring 5 cooked shrimps to the quest giver",
    },
    "logs_fetch": {
        "item": "logs", "amount": 10, "skill": "woodcutting",
        "xp_reward": 500.0, "coin_reward": 80,
        "description": "bring 10 logs to the quest giver",
    },
}

QUESTS.update(QUESTS_EXTRA)
COOKABLES.update(COOKABLES_EXTRA)
SMELTING.update(SMELTING_EXTRA)
TREES.update(TREES_EXTRA)
ROCKS.update(ROCKS_EXTRA)

SHOP_PRICES = {
    "logs": 8, "oak_logs": 20,
    "copper_ore": 6, "tin_ore": 6, "iron_ore": 17,
    "raw_shrimp": 2, "shrimp": 5,
    "bronze_bar": 12, "iron_bar": 30,
    "iron_axe": 60, "steel_axe": 320,
    "iron_pickaxe": 60, "steel_pickaxe": 320,
    "bronze_sword": 20, "iron_sword": 90, "steel_sword": 400,
    "raw_beef": 3, "cooked_meat": 6,
    "shortbow": 25, "bronze_arrow": 2, "iron_arrow": 4,
    "air_rune": 4, "fire_rune": 7, "rune_essence": 4,
    "cake": 8, "willow_logs": 15, "coal": 25, "steel_bar": 60,
    "knife": 15, "needle": 5, "thread": 2, "vial_of_water": 3,
    "guam_seed": 10, "tarromin_seed": 40, "ranarr_seed": 90,
    "cowhide": 20,
    "leather_gloves": 30, "leather_body": 80,
    "bronze_chainbody": 60, "iron_chainbody": 180, "steel_chainbody": 480,
}
SHOP_STOCK = ["iron_axe", "steel_axe", "iron_pickaxe", "steel_pickaxe",
              "bronze_sword", "iron_sword", "steel_sword",
              "shortbow", "bronze_arrow", "iron_arrow",
              "air_rune", "fire_rune", "cake",
              "knife", "needle", "thread", "vial_of_water",
              "guam_seed", "tarromin_seed", "ranarr_seed",
              "leather_gloves", "leather_body",
              "bronze_chainbody", "iron_chainbody", "steel_chainbody"]
UNIQUE_TOOLS = (set(AXES) | set(PICKAXES) | set(WEAPONS) | set(BOWS)
                | set(ARMOURS) | {"knife", "needle"})

LOCATIONS = {
    "tree_1": ("tree", "tree", (3, 3)),
    "tree_2": ("tree", "tree", (12, 4)),
    "tree_oak": ("tree", "oak", (5, 10)),
    "tree_willow": ("tree", "willow", (19, 3)),
    "rock_copper": ("rock", "copper", (2, 12)),
    "rock_tin": ("rock", "tin", (13, 13)),
    "rock_iron": ("rock", "iron", (11, 11)),
    "rock_coal": ("rock", "coal", (21, 16)),
    "rock_essence": ("rock", "essence", (18, 21)),
    "fishing_spot_1": ("spot", "shrimp", (14, 8)),
    "range": ("range", None, (8, 8)),
    "bank": ("bank", None, (8, 2)),
    "shop": ("shop", None, (8, 5)),
    "furnace": ("furnace", None, (13, 3)),
    "quest_giver": ("npc", None, (7, 7)),
    "air_altar": ("altar", "air_rune", (17, 7)),
    "fire_altar": ("altar", "fire_rune", (22, 6)),
    "shrine": ("shrine", None, (20, 13)),
    "fruit_stall": ("stall", "fruit_stall", (16, 14)),
    "cake_stall": ("stall", "cake_stall", (17, 15)),
    "agility_course": ("course", None, (11, 19)),
    "herb_patch_1": ("patch", None, (5, 16)),
    "herb_patch_2": ("patch", None, (6, 18)),
    "herb_patch_3": ("patch", None, (4, 20)),
    "slayer_master": ("master", None, (10, 17)),
}
SPAWN = (8, 9)
