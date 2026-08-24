# SDK reference

Your snippet receives `game` (class GameSDK) and must define `def run(game):`.

## Introspection
- game.state() -> dict: tick, ticks_left, position, coins, inventory (string),
  inventory_slots_used, skills {name: {level, xp}}, tools, bank_contents,
  nodes [{name, kind, resource, pos, distance, status}], events []
- game.skills(), game.inventory(), game.coins(), game.ticks_left(), game.log()

## Movement
- game.move_to(x, y) - 1 tick per tile
- game.walk(name) - walk adjacent to a named node:
  tree_1, tree_2, tree_oak, rock_copper, rock_tin, rock_iron,
  fishing_spot_1, range, bank, shop, stronghold_of_security

## Introspection (extended)
- game.skills("woodcutting") -> int level of one skill
- game.get_location() -> {"pos": [x,y], "nearest": place, "distance": tiles}
- game.tools() -> {"axes": [...], "pickaxes": [...], "weapons": [...], "other": [...]}
- game.bank() -> dict of deposited items
- game.quest("logs_fetch") -> status string ("not_started|active|claimed")
- game.claims() -> one-time claims done, e.g. ["stronghold_chest"]
- game.get_score(task="total_xp") -> live score snapshot with "score" key
- aliases: cut_log()==chop(), mine_ore()==mine(), catch_fish()==fish()

## Stronghold of Security
- walk("stronghold_of_security"), then game.search_chest():
  one time per session, +500 coins. Returns True on first claim.
  Best first move of any run - funds tool upgrades.

## Construction (workshop, walk target "workshop")
- game.cut_planks() - sawmill: logs/oak_logs/willow_logs -> plank,
  charges a sawmill fee in coins
- game.build("crude_wooden_chair") - lvl 1, 2 plank + 2 steel_nails,
  57 xp / "wooden_bookcase" lvl 4, 4+4, 115 xp /
  "wooden_chair" lvl 8, 3+3, 87 xp; needs saw + hammer;
  furniture sells at the shop

## Hunter (walk target "hunting_ground")
- game.lay_trap() - consumes a bird_snare (shop ~27 coins), up to 2
  snares armed at once, resolves after ~6 ticks
- game.check_trap() - collect: crimson_swift (lvl 1, 34 xp) or
  copper_longtail (lvl 9, 61.2 xp); loot: bones + raw_bird_meat +
  5-10 feathers; empty snares reset to your inventory
- raw_bird_meat cooks into cooked_meat at the range

## Energy
- game.set_energy_regen(rate) - idle regen multiplier, clamped [0.5, 2.0]
- game.set_run(True|False), set_run(False) saves energy

## Gathering (4 ticks per attempt; True if an item was gained)
- game.chop() next to a tree | game.mine() next to a rock |
  game.fish() next to fishing_spot_1

## Processing
- game.cook(raw_item=None) - 2 ticks, must be at the range, cooks first raw item

## Bank (adjacent to bank)
- game.deposit_all(), game.deposit(item, n=None), game.withdraw(item, n=None)

## Shop (adjacent to shop)
- game.sell(item, n=None) -> coins received
- game.buy("iron_axe"|"steel_axe"|"iron_pickaxe"|"steel_pickaxe") one-off tools

## Misc
- game.drop(item, n=None), game.wait(ticks)

Errors raise GameError with a helpful message; the tick budget raises
BudgetExceeded when exhausted. Both end your snippet.
