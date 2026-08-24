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

    if game.inventory().get("bird_snare", 0) == 0:
        ensure_coins(120)
        game.walk("shop")
        while game.coins() >= 27 and \
                game.inventory().get("bird_snare", 0) < 3:
            try:
                game.buy("bird_snare")
            except Exception:
                break
    while game.ticks_left() > 100:
        game.walk("hunting_ground")
        inv = game.inventory()
        snares = inv.get("bird_snare", 0)
        active = len(game.state().get("traps", {}))
        for _ in range(max(0, min(snares, 2 - active))):
            try:
                game.lay_trap()
            except Exception:
                break
        for _ in range(8):
            st = game.state()
            traps = st.get("traps", {})
            ready = [k for k, t in traps.items()
                     if st["tick"] >= t["ready_at"]]
            if ready:
                break
            game.wait(2)
        for _ in range(4):
            try:
                game.check_trap()
            except Exception:
                break
        loot = game.inventory()
        feathers = sum(v for k, v in loot.items()
                       if k.endswith("_feather"))
        if feathers or loot.get("raw_bird_meat"):
            game.walk("shop")
            for item in list(game.inventory()):
                if item.endswith("_feather") or item == "raw_bird_meat":
                    try:
                        game.sell(item)
                    except Exception:
                        pass
