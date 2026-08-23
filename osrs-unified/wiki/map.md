# Map

```
x: 0..15 left to right, y: 0..15 top to bottom.

(3,3)   tree_1          normal trees
(12,4)  tree_2          normal trees
(8,2)   bank            deposit/withdraw
(8,5)   shop            sell all / buy tools
(8,8)   range           cook raw food
(8,9)   SPAWN point
(5,10)  tree_oak        oak, needs wc 15
(2,12)  rock_copper     mining lvl 1
(13,13) rock_tin        mining lvl 1
(11,11) rock_iron       needs mining 15
(14,8)  fishing_spot_1  shrimp, never depletes
(13,3)  furnace         smelt bars
(7,7)   quest_giver     accept/turn in fetch quests
```

Quests (talk to quest_giver):
- shrimp_fetch: 5 cooked shrimps -> +300 cooking xp +50 coins
- logs_fetch: 10 logs -> +500 woodcutting xp +80 coins

Run mode: set_run(True) doubles travel speed but drains ~1 energy/tile;
energy regenerates 0.5/tick while not moving.

You must stand adjacent (chebyshev distance <= 1) to a node to interact with it.
game.walk("name") moves you right next to it automatically.
