# Overview

A simplified Old School RuneScape-style skilling world, 16x16 grid, tick-based.
You control one character with six skills (woodcutting, mining, fishing,
cooking, firemaking, smithing), a 28-slot inventory, a coin balance, a bank
(unless playing Ultimate Ironman), a general store, a furnace, and two fetch
quests from the quest giver.

Core loop: gather resources -> bank or sell them -> upgrade tools -> repeat
faster. Every action costs ticks; the episode ends when the tick budget runs
out. Score depends on the task: XP gained or net coins.

See sdk.md for the exact API and map.md for locations.
