def run(game):
    while game.ticks_left() > 80:
        game.walk("fishing_spot_1")
        for _ in range(6):
            if sum(game.inventory().values()) >= 28:
                break
            try:
                game.fish()
            except Exception:
                break
        game.walk("range")
        while any(i.startswith("raw_") for i in game.inventory()):
            try:
                game.cook()
            except Exception:
                break
        game.walk("shop")
        for item in list(game.inventory()):
            if item != "bronze_axe":
                try:
                    game.sell(item)
                except Exception:
                    pass
