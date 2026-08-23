def run(game):
    def safe(fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception:
            return None

    if "stronghold_chest" not in game.claims():
        print("phase 0: stronghold of security for starting capital")
        safe(game.walk, "stronghold_of_security")
        try:
            if game.search_chest():
                print(f"chest claimed, coins={game.coins()}")
        except Exception as e:
            print("chest skipped:", e)

    safe(game.set_energy_regen, 1.5)
    safe(game.set_run, True)

    prices = game.shop_prices()

    def upgrade_tools():
        owned = set(game.tools()["axes"] + game.tools()["pickaxes"])
        wanted = []
        if "steel_axe" in prices and "steel_axe" not in owned:
            wanted.append(("iron_axe", "steel_axe"))
        elif "iron_axe" in prices and "iron_axe" not in owned:
            wanted.append((None, "iron_axe"))
        if "steel_pickaxe" in prices and "steel_pickaxe" not in owned \
                and "iron_pickaxe" in owned:
            wanted.append((None, "steel_pickaxe"))
        elif "iron_pickaxe" in prices and "iron_pickaxe" not in owned:
            wanted.append((None, "iron_pickaxe"))
        for _dep, tool in wanted:
            cost = prices.get(tool)
            if cost is not None and game.coins() >= cost + 50:
                before = game.coins()
                if safe(game.buy, tool):
                    print(f"upgraded {tool} ({before}->{game.coins()}c)")

    def do_quests():
        inv = game.inventory()
        if sum(1 for i in inv if i == "cooked_shrimp") >= 5 or \
                inv.get("logs", 0) >= 10:
            safe(game.walk, "quest_giver")
            safe(game.talk_quest)

    def liquidate(keep=("bronze_axe",)):
        safe(game.walk, "shop")
        for item in list(game.inventory()):
            if item in keep:
                continue
            safe(game.sell, item)

    wc = game.skills("woodcutting")
    mining = game.skills("mining")
    print(f"start: wc={wc} mining={mining} coins={game.coins()}")

    while game.ticks_left() > 60:
        upgrade_tools()
        do_quests()

        if wc >= 20 and game.ticks_left() > 120 and mining < 40:
            print("mining phase: copper/tin -> bronze bars")
            safe(game.walk, "rock_copper")
            for _ in range(5):
                if game.ticks_left() <= 60:
                    break
                if not safe(game.mine):
                    safe(game.walk, "rock_tin")
                    if not safe(game.mine):
                        break
            safe(game.walk, "furnace")
            for _ in range(4):
                if "copper_ore" in game.inventory() and \
                        "tin_ore" in game.inventory():
                    safe(game.smelt, "bronze_bar")
            safe(game.walk, "shop")
            safe(game.sell, "bronze_bar")

        target = "tree_willow" if wc >= 20 else \
            ("tree_oak" if wc >= 15 else "tree_1")
        safe(game.walk, target)
        chopped = 0
        while game.ticks_left() > 60 and chopped < 24:
            if len(game.inventory()) >= 27:
                break
            result = safe(game.chop)
            if result is False:
                safe(game.walk, "tree_2" if target != "tree_2" else "tree_1")
                continue
            if result is None:
                break
            chopped += 1

        do_quests()
        logs = game.inventory().get("logs", 0)
        if logs >= 10:
            safe(game.walk, "quest_giver")
            safe(game.talk_quest)
        liquidate()
        wc = game.skills("woodcutting")
        mining = game.skills("mining")

    print(f"done: {game.get_score('total_xp')['total_xp']} total xp, "
          f"{game.coins()} coins")
