def run(game):
    while game.ticks_left() > 60:
        if sum(game.inventory().values()) >= 28:
            game.walk("bank")
            game.deposit_all()
        game.walk("tree_1")
        try:
            game.chop()
        except Exception:
            game.walk("tree_2")
