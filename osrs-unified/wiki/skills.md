# Skills and resources

XP needed per level follows the classic curve: level 2 needs ~83 total xp,
level 10 ~1154, level 20 ~4473, level 30 ~13363, level 40 ~37224.

## Woodcutting (axe required)
| Node | Req lvl | XP per log | Item | Node hp | Respawn |
|---|---|---|---|---|---|
| tree | 1 | 25 | logs | 8 | ~15 ticks |
| oak | 15 | 37.5 | oak_logs | 12 | ~25 ticks |

Success chance per 4-tick attempt: 30% + 1.5% per level above requirement +
tool bonus (bronze axe +0%, iron +5%, steel +10%), capped 95%.

## Mining (pickaxe required)
| Rock | Req | XP | Item | hp | Respawn |
|---|---|---|---|---|---|
| copper | 1 | 17.5 | copper_ore | 6 | ~10 ticks |
| tin | 1 | 17.5 | tin_ore | 6 | ~10 ticks |
| iron | 15 | 35 | iron_ore | 9 | ~20 ticks |

Same success formula using pickaxe bonus.

## Fishing (no tool needed)
Shrimp: req 1, 10 xp each, spot never depletes. Chance 40% + 0.8%/level, cap 95%.

## Cooking (at the range)
Raw shrimp: req 1, 30 xp cooked. Burn chance starts 45% and drops 2% per cooking
level; stops burning entirely at level 34. Burnt food is lost.

## Firemaking (anywhere)
Burn one inventory of logs per action: logs 40 xp, oak_logs 60 xp. 2 ticks
each, always succeeds, consumes the log. Pure xp conversion - useful when
far from a bank and your inventory is full of cheap logs.

## Smithing (at the furnace, (13,3))
| Bar | Req | Ores needed | XP | Notes |
|---|---|---|---|---|
| bronze_bar | 1 | copper_ore + tin_ore | 6.2 | never fails; sells 12gp |
| iron_bar | 15 | iron_ore x1 | 12.5 | ~50% fail chance at lvl 15, -2%/level; ore lost on fail |

Smelting takes 4 ticks. Bars sell at the shop (bronze 12, iron 30).

## Construction (workshop at (14,18))
Sawmill: any logs -> plank (fee: logs 20 / oak 40 / willow 40 coins), 3 ticks.
| Furniture | Req | Materials | XP |
|---|---|---|---|
| crude_wooden_chair | 1 | 2 plank + 2 steel_nails | 57 |
| wooden_bookcase | 4 | 4 plank + 4 steel_nails | 115 |
| wooden_chair | 8 | 3 plank + 3 steel_nails | 87 |

5-tick build; needs saw + hammer (shop). Numbers follow the OSRS wiki;
furniture sells back at the shop.

## Hunter (hunting ground at (3,21))
Bird snares only (shop ~27 coins), max 2 armed, ~6 ticks to arm, 2-tick
lay/check actions.
| Bird | Req | XP | Loot |
|---|---|---|---|
| crimson_swift | 1 | 34 | bones, raw_bird_meat, 5-10 red feathers |
| copper_longtail | 9 | 61.2 | bones, raw_bird_meat, 5-10 orange feathers |

Catch rate 39% at req level, +2%/level above, cap 95%. Failed snares reset
to your inventory. raw_bird_meat cooks into cooked_meat like beef.

## XP math worth knowing
- A full inventory of 28 logs = 700 wc xp before walking/banking time.
- Cooking a shrimp yields triple the fishing xp of catching it, so fish->cook
  chains roughly quadruple total xp per catch vs dropping raws.
