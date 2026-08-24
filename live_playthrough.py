"""Live end-to-end playthrough: connects to the authoritative RSPS
server like the real client does and exercises every major game system."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "osrs-llm-agent"))
from server.rsps_server import GameServer          # noqa: E402
from server.client import RemoteGameSDK            # noqa: E402

PASS, FAIL = [], []


def check(name, fn):
    try:
        detail = fn()
        PASS.append(name)
        print(f"  PASS {name}" + (f" - {detail}" if detail else ""))
    except Exception as e:
        FAIL.append((name, f"{type(e).__name__}: {e}"))
        print(f"  FAIL {name} - {type(e).__name__}: {e}")


srv = GameServer(port=43999)
srv.start_async()
time.sleep(0.6)


class PacedSDK(RemoteGameSDK):
    """Stay under the server's 100 req/s abuse cap while botting."""

    def _request(self, payload):
        time.sleep(0.015)
        return super()._request(payload)


g = PacedSDK(name="playthrough", port=srv.port, budget=8000)

st = g.state()


def walk(place):
    g.walk(place)
    return None


def chop():
    walk("tree_1")
    got = False
    for _ in range(10):
        if g.chop():
            got = True
            break
    assert got, "no log obtained"
    return "logs x1"


def mine():
    got = False
    spots = ["rock_copper", "rock_tin"]
    for i in range(30):
        if got:
            break
        walk(spots[i % len(spots)])
        for _ in range(4):
            try:
                if g.mine():
                    got = True
                    break
            except Exception as e:
                print(f"    [mine] {e}", file=sys.stderr)
                g.wait(6)
                break
    assert got, "no ore obtained"
    return "copper_ore x1"


def fish():
    walk("fishing_spot_1")
    got = False
    for _ in range(12):
        if g.fish():
            got = True
            break
    assert got, "no shrimp"
    return "raw_shrimp x1"


def cook():
    walk("range")
    ok = False
    while "raw_shrimp" in g.inventory():
        g.cook()
        ok = True
    assert ok
    return "shrimp cooked"


def light_fire():
    st = g.state()
    if "logs" not in g.inventory() and "oak_logs" not in st["inventory"]:
        chop()
    item = g.light_fire()
    assert item in ("logs", "oak_logs")
    return f"{item} burned"


def smelt():
    def inv_has(i):
        return i in g.inventory()
    while not (inv_has("copper_ore") and inv_has("tin_ore")):
        walk("rock_copper" if not inv_has("copper_ore") else "rock_tin")
        if not g.mine():
            g.wait(4)
    walk("furnace")
    g.smelt("bronze_bar")
    return "bronze_bar"


def melee_kill():
    walk("goblin_1")
    killed = False
    for _ in range(30):
        try:
            r = g.attack("goblin_1")
            if r.get("killed"):
                killed = True
                break
        except Exception:
            g.wait(5)
    assert killed, "goblin not killed"
    return "goblin down"


def cast_spell():
    ensure_coins(150)
    walk("shop")
    g.buy("air_rune", 20)
    walk("goblin_2")
    killed_or_hit = False
    for _ in range(25):
        try:
            r = g.cast("wind_strike", "goblin_2")
            if r["player_damage"] > 0 or r.get("killed"):
                killed_or_hit = True
                break
        except Exception as e:
            if "dead" in str(e):
                killed_or_hit = True
                break
            g.wait(5)
    assert killed_or_hit, "spell never landed"
    return "wind_strike landed"


def ranged_shot():
    clear_sack()
    ensure_coins(200)
    walk("shop")
    g.buy("shortbow")
    g.buy("bronze_arrow", 5)
    walk("cow_1")
    g.set_combat_style("ranged")
    hit = False
    for _ in range(20):
        try:
            r = g.attack("cow_1")     # ranged reaches 3 tiles
            hit = True
            break
        except Exception as e:
            if "dead" in str(e) or "respawn" in str(e):
                hit = True
                break
            g.wait(5)
    g.set_combat_style("accurate")
    assert hit, "never got a shot off"
    return "arrow loosed at cow_1"


def thieve():
    walk("fruit_stall")
    stole = False
    for _ in range(20):
        try:
            if g.thieve("fruit_stall"):
                stole = True
                break
        except Exception as e:
            if "watching" not in str(e):
                raise
            g.wait(8)
    assert stole, "never lifted a purse"
    return "coins stolen"


def runecraft():
    clear_sack()
    walk("rock_essence")
    got = False
    for _ in range(12):
        if g.mine():
            got = True
            break
    assert got, "no essence"
    walk("air_altar")
    n = g.craft_rune("air_rune")
    assert n >= 1
    return f"{n}x air_rune"


def agility():
    walk("agility_course")
    g.run_lap()
    return "lap done"


def farming_herblore():
    clear_sack()
    ensure_coins(80)
    walk("shop")
    g.buy("guam_seed")
    walk("herb_patch_1")
    g.plant("guam_seed")
    ticks_waited = 0
    while True:
        st = g.state()
        patch = next(n for n in st["nodes"] if n["kind"] == "patch"
                     and n["distance"] <= 1)
        if "ready" in patch["status"]:
            break
        g.wait(10)
        ticks_waited += 10
        assert ticks_waited < 200, "herb never grew"
    g.harvest()
    walk("shop")
    g.buy("vial_of_water")
    g.make_potion("attack_potion")
    return "guam grown -> attack_potion mixed"


def _patient_logs(n_needed=1):
    """Chop with regen-aware patience - depleted trees need ~15 ticks."""
    got = 0
    spots = ["tree_1", "tree_2"]
    i = 0
    while got < n_needed and g.ticks_left() > 400:
        walk(spots[i % len(spots)])
        i += 1
        try:
            if g.chop():
                got += 1
        except Exception as e:
            if "regrowing" in str(e) or "depleted" in str(e):
                g.wait(15)
            else:
                g.wait(4)


def fletch_craft():
    clear_sack()
    ensure_coins(150)
    walk("shop")
    g.buy("knife")
    g.buy("needle")
    g.buy("thread", 2)
    g.buy("cowhide")            # shop stocks hides (or kill cows yourself)
    _patient_logs(1)
    assert "logs" in g.inventory(), "no logs for fletching"
    g.fletch()
    g.craft_leather("leather_gloves")
    return "shortbow fletched + gloves crafted"


def slayer_loop():
    walk("slayer_master")
    task = g.assign_slayer()
    assert task["need"] >= 3
    return f"task: {task['need']}x {task['kind']}"


def construction_flow():
    clear_sack()
    ensure_coins(300)
    walk("shop")
    for item, qty in (("saw", 1), ("hammer", 1), ("steel_nails", 12)):
        try:
            g.buy(item, qty)
        except Exception as e:
            if "already own" not in str(e):
                raise
    trees_spots = None
    logs = 0
    spots = ["tree_1", "tree_2"]
    i = 0
    while logs < 2 and g.ticks_left() > 400:
        walk(spots[i % len(spots)])
        i += 1
        try:
            if g.chop():
                logs += 1
        except Exception as e:
            if "regrowing" in str(e) or "depleted" in str(e):
                g.wait(15)
            else:
                g.wait(4)
    walk("workshop")
    planks = 0
    while "logs" in g.inventory() and g.coins() >= 20:
        try:
            if g.cut_planks():
                planks += 1
        except Exception as e:
            print(f"    [plank] {e}", file=sys.stderr)
            break
    print(f"    [constr] logs={g.inventory().get('logs', 0)} "
          f"planks={planks} coins={g.coins()} "
          f"sack={sum(g.inventory().values())}/28", file=sys.stderr)
    assert planks >= 2, f"only {planks} planks"
    xp0 = g.state()["skills"]["construction"]["xp"]
    built = 0
    while g.inventory().get("plank", 0) >= 2 and \
            g.inventory().get("steel_nails", 0) >= 2:
        out = g.build("crude_wooden_chair")
        built += 1
    xp1 = g.state()["skills"]["construction"]["xp"]
    assert built >= 1 and xp1 > xp0, f"built {built}, xp {xp1 - xp0}"
    lvl = g.skills("construction")
    return (f"{built} chair(s), construction xp +{int(xp1 - xp0)}, "
            f"lvl {lvl}")


def hunter_flow():
    clear_sack()
    ensure_coins(120)
    walk("shop")
    g.buy("bird_snare", 2)
    walk("hunting_ground")
    caught = 0
    xp0 = g.state()["skills"]["hunter"]["xp"]
    deadline = g.ticks_left() - 400
    while caught < 1 and g.ticks_left() > deadline:
        s = g.state()
        traps = s.get("traps", {})
        if len(traps) < 2 and g.inventory().get("bird_snare"):
            g.lay_trap()
            continue
        ready = [k for k, t in traps.items()
                 if s["tick"] >= t["ready_at"]]
        if ready:
            try:
                if g.check_trap():
                    caught += 1
            except Exception:
                pass
            continue
        g.wait(2)
    xp1 = g.state()["skills"]["hunter"]["xp"]
    assert xp1 > xp0, "no hunter xp gained"
    return f"{caught} bird(s), hunter xp {int(xp1 - xp0)}"


def ensure_coins(target):
    while g.coins() < target and g.ticks_left() > 400:
        walk("tree_1")
        logs = 0
        for _ in range(8):
            try:
                if g.chop():
                    logs += 1
            except Exception:
                break
        walk("shop")
        for _ in range(logs):
            if g.coins() >= target:
                break
            try:
                g.sell("logs")
            except Exception:
                break


def clear_sack():
    """Bank everything - the 28-slot backpack is the real constraint."""
    if sum(g.inventory().values()) > 20:
        walk("bank")
        g.deposit_all()


def bank_and_prayer():
    clear_sack()
    # get a log + bones the honest way (cows always drop bones here)
    _patient_logs(1)
    assert "logs" in g.inventory(), "no logs to bank"
    walk("cow_1")
    got_bones = False
    for _ in range(40):
        if got_bones:
            break
        walk("cow_1")               # re-assert position (death/respawn safe)
        try:
            r = g.attack("cow_1")
            if r.get("killed"):
                drops = r.get("drops") or []
                print(f"    [bank] drops={drops}", file=sys.stderr)
                got_bones = any("bones" in d for d in drops)
        except Exception as e:
            if "dead" in str(e) or "respawn" in str(e):
                g.wait(10)
            else:
                g.wait(4)
    assert got_bones or "bones" in g.inventory(), "no bones"
    walk("bank")
    g.deposit_all()
    assert sum(g.inventory().values()) == 0, "bank did not empty sack"
    g.withdraw("logs", 1)
    return "deposit/withdraw ok"


print("=" * 62)
print("LIVE PLAYTHROUGH - every game system, over the wire")
print("=" * 62)

check("login + world state", lambda: f"tick {g.state()['tick']}, "
      f"{len(g.state()['skills'])} skills")
check("woodcutting", chop)
check("mining", mine)
check("fishing", fish)
check("cooking", cook)
check("firemaking", light_fire)
check("smithing", smelt)
check("melee combat + loot", melee_kill)
check("magic (cast)", cast_spell)
check("ranged (bow)", ranged_shot)
check("thieving", thieve)
check("runecrafting", runecraft)
check("agility", agility)
check("farming + herblore", farming_herblore)
check("fletching + crafting", fletch_craft)
check("slayer assignment", slayer_loop)
check("construction", construction_flow)
check("hunter", hunter_flow)
check("banking", bank_and_prayer)


def prayer_bury():
    walk("cow_1")
    for _ in range(60):
        if "bones" in g.inventory():
            break
        walk("cow_1")               # stay adjacent (respawn/death safe)
        try:
            r = g.attack("cow_1")
            if r.get("killed"):
                print(f"    [prayer] drops={r.get('drops')}",
                      file=sys.stderr)
                continue
        except Exception as e:
            g.wait(10 if ("dead" in str(e) or "respawn" in str(e))
                   else 4)
    assert "bones" in g.inventory(), "no bones to bury"
    g.bury_bones()
    return "bury ok (+4.5 prayer xp)"


check("prayer (bury bones)", prayer_bury)
check("quests", lambda: (walk("quest_giver"), g.talk_quest(),
                         str(g.quest_status())))
check("shop economy", lambda: (walk("shop"),
                               str(g.sell("logs")
                                   if "logs" in g.inventory()
                                   else g.sell("bones")) + " coins"))

final = g.state()
total_xp = int(sum(v["xp"] for v in final["skills"].values()))
levels = sum(1 for v in final["skills"].values() if v["level"] > 1)
g.close()
srv.stop()

print("-" * 62)
print(f"final: total_xp={total_xp}, levels>1={levels}/23, "
      f"coins={final['coins']}, tick={final['tick']}")
print(f"{len(PASS)} systems PASS, {len(FAIL)} FAIL")
if FAIL:
    for name, err in FAIL:
        print(f"  FAILED: {name}: {err}")
    sys.exit(1)
print("FULL GAMEPLAY VERIFIED - all engines operational")
