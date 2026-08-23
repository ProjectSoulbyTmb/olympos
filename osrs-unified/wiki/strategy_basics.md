# Strategy basics

1. Minimize walking. Bank/shop trips should be batched: fill all 28 slots,
   then do one combined bank+shop visit if they are near each other.
2. Respect respawns. A fallen tree respawns in ~15 ticks; a second tree two
   tiles away may be better than standing still. game.state() reports status.
3. Tool upgrades pay compounding dividends: +5% success on every future
   attempt usually beats saving for anything else early on.
4. Cook before selling: raw shrimp sell for 2gp, cooked for 5gp, plus 30xp.
5. Track your rates: compare xp gained vs ticks_left to sanity-check whether
   a loop is actually improving.
6. Guard the budget: BudgetExceeded ends the episode cleanly mid-loop, so put
   the most valuable actions first and avoid infinite loops without progress.
7. Quests are huge xp-per-tick: shrimp_fetch pays 300 cooking xp + 50 coins
   for ~5 catches + 5 cooks you would do anyway. Always accept early and turn
   in when ready - game.quest_status() tracks progress.
8. Use run for long trips (>4 tiles) and walk for short hops; energy drains
   on run tiles and refills while skilling.
