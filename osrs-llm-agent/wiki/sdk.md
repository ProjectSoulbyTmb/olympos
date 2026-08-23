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
  fishing_spot_1, range, bank, shop

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
