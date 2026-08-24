def run(game):
    def ensure_coins(target):
        while game.coins() < target and game.ticks_left() > 150:
            game.walk("tree_1")
            for _ in range(5):
                try:
                    if not game.chop():
                        break
                except Exception:
                    break
            game.walk("shop")
            for _ in range(8):
                if "logs" not in game.inventory() or \
                        game.coins() >= target:
                    break
                try:
                    game.sell("logs")
                except Exception:
                    break

    if "saw" not in game.tools():
        ensure_coins(60)
        game.walk("shop")
        try:
            game.buy("saw")
        except Exception:
            return
    if "hammer" not in game.tools():
        game.walk("shop")
        try:
            game.buy("hammer")
        except Exception:
            pass
    while game.ticks_left() > 120:
        if game.coins() < 40:
            ensure_coins(80)
        game.walk("tree_1")
        for _ in range(6):
            if sum(game.inventory().values()) >= 26:
                break
            try:
                game.chop()
            except Exception:
                break
        game.walk("workshop")
        while any(i in ("logs", "oak_logs", "willow_logs")
                  for i in game.inventory()) and game.coins() >= 20:
            try:
                if not game.cut_planks():
                    break
            except Exception:
                break
        inv = game.inventory()
        furniture = None
        lvl = game.skills("construction")
        for name, req in (("wooden_chair", 8),
                          ("wooden_bookcase", 4),
                          ("crude_wooden_chair", 1)):
            if lvl >= req and inv.get("plank"):
                furniture = name
                break
        if furniture:
            if game.inventory().get("steel_nails", 0) < 2:
                game.walk("shop")
                while game.coins() >= 6 and \
                        game.inventory().get("steel_nails", 0) < 8:
                    try:
                        game.buy("steel_nails")
                    except Exception:
                        break
                game.walk("workshop")
        while furniture:
            try:
                game.build(furniture)
            except Exception:
                break
        game.walk("shop")
        for item in list(game.inventory()):
            if item.endswith(("_chair", "_bookcase")) or \
                    (item == "plank" and game.coins() < 200):
                try:
                    game.sell(item)
                except Exception:
                    pass
