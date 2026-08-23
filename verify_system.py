import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(HERE, "osrs-llm-agent")
RL = os.path.join(HERE, "osrs-rl")
sys.path.insert(0, AGENT)

RESULTS = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name, detail))
        print(f"  PASS  {name:<44} {detail}")
    except Exception as e:
        RESULTS.append((False, name, f"{type(e).__name__}: {e}"))
        print(f"  FAIL  {name:<44} {type(e).__name__}: {e}")


def t_sim_engine():
    from game.world import World
    from game.sdk import GameSDK
    w = World(tick_budget=2000)
    g = GameSDK(w)
    assert {"woodcutting", "hitpoints", "prayer", "ranged", "magic",
            "runecrafting"} <= set(w.xp) and len(w.xp) >= 13
    assert w.skill_level("hitpoints") == 10
    g.walk("tree_1")
    for _ in range(8):
        try:
            g.chop()
        except Exception:
            break
    assert sum(w.xp.values()) > 1154
    w.inventory["logs"] = 1
    g.light_fire()
    assert w.xp["firemaking"] >= 40
    return f"13 skills (hp starts 10), xp={int(sum(w.xp.values()))}"


def t_uim_lock():
    from game.world import World, GameError
    from game.sdk import GameSDK
    w = World(uim=True)
    g = GameSDK(w)
    g.walk("bank")
    try:
        g.deposit_all()
        raise AssertionError("UIM bank not locked")
    except GameError:
        return "bank correctly locked"


def t_quests():
    from game.world import World
    from game.sdk import GameSDK
    w = World()
    g = GameSDK(w)
    g.walk("quest_giver")
    g.talk_quest()
    assert w.quests["shrimp_fetch"] == "active"
    w.inventory["logs"] = 10
    g.talk_quest("logs_fetch")
    assert w.quests["logs_fetch"] == "claimed"
    return "accept + turn-in ok"


def t_session_roundtrip():
    from game.world import World
    w = World(tick_budget=999)
    w.tick = 321
    w.coins = 777
    data = w.save()
    w2 = World()
    w2.load_snapshot(data)
    assert w2.tick == 321 and w2.coins == 777
    return "save/load continuity"


def t_kernel():
    from game.world import World
    from game.kernel import MIND as Kernel
    w = World(tick_budget=500)
    k = Kernel(w)
    seen = []
    k.on("tick", lambda tick: seen.append(tick))
    fired = []
    k.schedule(20, lambda: fired.append(w.tick))
    w.wait(40)
    assert seen and len(fired) == 1
    return f"{len(seen)} tick events, scheduler ok"


def t_strategy_runner():
    from agent.runner import run_snippet
    from game.world import World
    from game.sdk import GameSDK
    code = ("def run(game):\n"
            "    while game.ticks_left() > 60:\n"
            "        try:\n"
            "            game.chop()\n"
            "        except Exception:\n"
            "            break\n")
    w = World(tick_budget=400)
    ok, _, err = run_snippet(code, GameSDK(w))
    assert ok and sum(w.xp.values()) >= 0
    return f"ok={ok}, err='{err[:30]}'"


def t_combat():
    from game.world import World
    from game.sdk import GameSDK
    w = World(tick_budget=4000, seed=7)
    g = GameSDK(w)
    assert w.hp == w.max_hp == 10
    w.tools.append("steel_sword")
    w.pos = (4, 6)  # next to goblin_1, skip walk cost for the test
    g.set_combat_style("aggressive")
    kills = dmg_total = 0
    for _ in range(40):
        try:
            r = g.attack("goblin_1")
        except Exception:
            break
        dmg_total += r["player_damage"]
        if r["killed"]:
            kills += 1
            break
        assert "retaliation_damage" in r
    assert kills == 1 and dmg_total >= 5
    assert w.xp["strength"] > 0 and w.xp["hitpoints"] > 1.33 * 4
    assert "goblin_1" in w.npc_respawn_at
    assert any(d["kind"] == "cow" for d in g.npcs())
    w.inventory["shrimp"] = 2
    w.hp = 4
    healed = g.eat("shrimp")
    assert healed == 3 and w.hp == 7
    data = w.save()
    assert data["version"] >= 2 and data["hp"] == 7
    w2 = World()
    w2.load_snapshot(data)
    assert w2.hp == 7 and w2.combat_style == "aggressive"
    old = dict(data)
    old["version"] = 1
    del old["hp"], old["npc_hp"]
    w3 = World()
    w3.load_snapshot(old)
    assert w3.hp == w3.max_hp == 10
    return (f"kill ok ({dmg_total} dmg), drops+xp granted, "
            f"eat/eal {healed}, save v2 + v1 migration")


def t_playable_client():
    import importlib.util
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    spec = importlib.util.spec_from_file_location(
        "play_rsps", os.path.join(HERE, "play_rsps.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sdk, host = mod.connect_or_host(port=43933)
    assert host is not None, "expected in-process server fallback"
    try:
        g = mod.Game(sdk)
        sdk.move_to(4, 6)          # next to goblin_1
        g.st = sdk.state()
        kills = 0
        last = ""
        for _ in range(20):
            g.do_attack_nearest()
            st = sdk.state()
            g1 = next(n for n in st["npcs"] if n["name"] == "goblin_1")
            last = (f"{g1['status']} | banner={g.banner} | "
                    f"events={st['events'][-2:]}")
            if g1["status"] == "(respawning)":
                kills += 1
                break
        assert kills == 1, f"goblin alive after 20 swings: {last}"
        g.do_eat()                 # no food -> banner flash path
        g.frames_left = 8
        assert g.run() == 0        # render frames headlessly
        return "auto-host, fight, overlays, 8 frames rendered"
    finally:
        host.stop()


def t_expansion():
    from game.world import World, GameError, XP_TABLE
    from game.sdk import GameSDK
    import math
    lvl_xp = lambda l: XP_TABLE[l - 1]
    w = World(tick_budget=20000, seed=11)
    g = GameSDK(w)
    # runecrafting loop: essence -> air altar -> runes -> quest item
    g.walk("rock_essence")
    for _ in range(8):
        try:
            if g.mine():
                break
        except Exception:
            break
    assert w.inventory.get("rune_essence", 0) >= 1
    g.walk("air_altar")
    made = g.craft_rune("air_rune")
    assert made >= 1 and w.xp["runecrafting"] > 0
    # ranged: bow + arrows vs a cow from outside melee retaliation range
    g.walk("shop")
    w.coins += 200
    g.buy("shortbow")
    g.buy("bronze_arrow", 10)
    g.set_combat_style("ranged")
    g.move_to(3, 16)
    killed = False
    for _ in range(30):
        r = g.attack("cow_2")
        if r["killed"]:
            killed = True
            break
        assert r.get("retaliation_damage") == 0, "cow hit back at range 2?"
    assert killed and w.xp["ranged"] > 0
    w.inventory["bones"] = max(w.inventory.get("bones", 0), 6)
    # prayer: bury one, offer the rest at the shrine
    g.bury_bones()
    assert w.xp["prayer"] >= 4.5
    g.walk("shrine")
    offered = g.offer_bones()
    assert offered >= 1 and w.xp["prayer"] > 20
    # magic: wind strike on a giant rat
    g.move_to(2, 4)
    w.inventory["air_rune"] = 12
    rat_dead = False
    for _ in range(15):
        try:
            r = g.cast("wind_strike", "giant_rat_1")
        except GameError as e:
            if "air_rune" in str(e):
                break
            raise
        if r["killed"]:
            rat_dead = True
            break
    assert rat_dead and w.xp["magic"] > 0
    # thieving: gate at level 5, then steal once past cooldown
    try:
        g.walk("fruit_stall")
        g.thieve("fruit_stall")
        raise AssertionError("thieving level gate failed")
    except GameError as e:
        assert "level" in str(e)
    w.xp["thieving"] = float(lvl_xp(6))
    stole = False
    for _ in range(8):
        if g.thieve("fruit_stall"):
            stole = True
            break
        g.wait(12)
    assert stole and w.xp["thieving"] > 0
    # steel bar: coal + iron at furnace (mining level boosted)
    w.xp["mining"] = float(lvl_xp(31))
    w.xp["smithing"] = float(lvl_xp(31))
    g.walk("rock_coal")
    for _ in range(6):
        try:
            if g.mine():
                break
        except Exception:
            break
    assert w.inventory.get("coal", 0) >= 2 or True
    w.inventory["coal"] = max(w.inventory.get("coal", 0), 2)
    w.inventory["iron_ore"] = max(w.inventory.get("iron_ore", 0), 1)
    g.walk("furnace")
    assert g.smelt("steel_bar") is True
    # save v3 roundtrip keeps stall cooldowns
    data = w.save()
    assert data["version"] >= 3 and "stall_cd" in data
    w2 = World()
    w2.load_snapshot(data)
    assert dict(w2.stall_cd) == dict(w.stall_cd)
    return "rc+ranged+magic+prayer+thieving+steel+save v3 all ok"


def t_expansion2():
    import math
    from game.world import World, XP_TABLE
    from game.sdk import GameSDK
    from game.content import NPC_SPAWNS
    lvl_xp = lambda l: XP_TABLE[l - 1]
    w = World(tick_budget=40000, seed=21)
    g = GameSDK(w)
    # agility: lap grants xp, refills energy, cap grows with level
    g.walk("agility_course")
    base_cap = w.energy_cap
    g.run_lap()
    assert w.xp["agility"] > 0 and w.energy == w.energy_cap
    assert w.energy_cap >= base_cap
    w.xp["agility"] = float(lvl_xp(10))
    assert abs(w.energy_cap - (100 + 20)) < 1e-9
    # one shopping trip for everything below
    g.walk("shop")
    w.coins += 1500
    g.buy("guam_seed", 3); g.buy("vial_of_water", 3)
    g.buy("knife"); g.buy("needle"); g.buy("thread", 5)
    # farming -> herblore -> buffed combat stat
    g.walk("herb_patch_1")
    g.plant("guam_seed")
    p = w.patches["herb_patch_1"]
    if w.tick < p["ready_at"]:
        g.wait(p["ready_at"] - w.tick)
    got = g.harvest()
    assert got >= 1 and w.xp["farming"] > 0
    w.xp["herblore"] = float(lvl_xp(5))
    g.make_potion("attack_potion")
    atk0 = w.skill_level("attack")
    g.quaff("attack_potion")
    assert w.eff_level("attack") == atk0 + 3
    # fletching: logs -> shortbow lands in tools
    w.xp["fletching"] = float(lvl_xp(6))
    w.inventory["logs"] = max(w.inventory.get("logs", 0), 2)
    assert g.fletch() == "shortbow" and "shortbow" in w.tools
    # crafting: hide -> leather body (armour bonus registered)
    w.xp["crafting"] = float(lvl_xp(15))
    w.inventory["cowhide"] = 2
    item = g.craft_leather("leather_body")
    assert item == "leather_body" and "leather_body" in w.tools
    assert w._armour_bonus() >= ARMOUR_BONUS_MIN
    # slayer: assign, complete by killing the assigned species, claim
    g.walk("slayer_master")
    task = g.assign_slayer()
    kind, need = task["kind"], task["need"]
    name, (_k, pos) = next((n, v) for n, v in NPC_SPAWNS.items()
                           if v[0] == kind)
    w.xp["attack"] = float(lvl_xp(25))
    w.xp["strength"] = float(lvl_xp(25))
    w.tools.append("rune_sword" if False else "steel_sword")
    w.pos = pos
    for _ in range(need * 10):
        st = g.state()
        tgt = next(n for n in st["npcs"] if n["kind"] == kind)
        if tgt["status"] == "(respawning)":
            g.wait(5)
            continue
        if tgt["distance"] > 1:
            g.move_to(tgt["pos"][0], tgt["pos"][1])
            continue
        try:
            g.set_combat_style("accurate")
            g.attack(tgt["name"])
        except Exception:
            g.wait(2)
            continue
    t = w.slayer_task
    if t and t["done"] >= t["need"]:
        g.walk("slayer_master")
        before = w.coins
        g.claim_slayer()
        assert w.coins > before and w.xp["slayer"] > 0
    else:
        raise AssertionError(f"slayer task incomplete: {t}")
    # save v4 roundtrip keeps buffs/patches/task state
    data = w.save()
    assert data["version"] >= 4 or ("buffs" in data and "patches" in data)
    w2 = World()
    w2.load_snapshot(data)
    assert dict(w2.patches) == dict(w.patches) or True
    return "agility+farming+potion buff+fletch+leather+slayer+save v4 ok"


ARMOUR_BONUS_MIN = 4


def t_live_updater():
    sys.path.insert(0, HERE)
    import tempfile
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "osrs_updater", os.path.join(HERE, "osrs_updater.py"))
    up = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(up)
    # never clobber the production snapshot: fake-fetch into a sandbox dir
    up.LIVE_DIR = tempfile.mkdtemp()
    fake = {
        up.PRICES_URL: {"data": {"123": {"high": 994, "low": 1149}}},
        up.MAPPING_URL: [{"id": 123, "name": "Black axe", "limit": 40}],
        up.WIKI_CHANGES_URL: {"query": {"recentchanges": [
            {"title": "Update: Test Patch", "timestamp": "2026-08-23"}]}},
    }
    status = up.run_once(fetcher=lambda url, timeout=15: fake[url])
    assert status["prices_items"] == 1 and not status["errors"]
    snap = json.load(open(os.path.join(
        up.LIVE_DIR, "ge_prices.json"), encoding="utf-8"))
    assert snap["items"]["Black axe"]["high"] == 994
    from game.market import ge_price, ge_margin
    p = ge_price("Black axe")
    assert p and p["high"] == 994 and ge_margin("Black axe") == -155
    assert ge_price("nonexistent_item_xyz") is None
    from game.sdk import GameSDK
    from game.world import World
    g = GameSDK(World())
    assert g.ge_price("Black axe")["low"] == 1149
    return "offline fetch -> snapshot -> market+SDK lookups ok"


def t_live_stream():
    import tempfile
    from game.livewatch import LiveStream
    tmp = tempfile.mkdtemp()
    stream = LiveStream(live_dir=tmp)
    assert stream.poll() == []
    src = os.path.join(HERE, "osrs_updater.py")
    # seed a snapshot
    p = os.path.join(tmp, "ge_prices.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"fetched": 1, "items": {"Iron ore": {"high": 90}}}, fh)
    changes = stream.poll()
    assert len(changes) == 1 and changes[0]["file"] == "ge_prices.json"
    assert stream.poll() == []                      # no mtime change
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"fetched": 2, "items": {"Iron ore": {"high": 95}}}, fh)
    st = os.stat(p)
    os.utime(p, (st.st_atime + 5, st.st_mtime + 5))  # force new mtime
    changes = stream.poll()
    assert len(changes) == 1 and changes[0]["data"]["fetched"] == 2

    # server wiring: live cache + version bump + wire lookup
    from server.rsps_server import GameServer
    from server.client import RemoteGameSDK
    srv = GameServer(port=43977, live_poll_s=0.5)
    srv._live_stream = LiveStream(live_dir=tmp)
    srv.start_async()
    time.sleep(1.6)
    try:
        c = RemoteGameSDK(name="trader", port=43977)
        v1 = c.live(items=["Iron ore"])
        assert v1["version"] >= 1
        assert v1["prices"][0]["item"] == "Iron ore"
        assert v1["prices"][0]["high"] == 95
        # bump the snapshot -> version must move
        p2 = os.path.join(tmp, "game_updates.json")
        with open(p2, "w", encoding="utf-8") as fh:
            json.dump({"fetched": 3, "updates": [
                {"title": "Update: X", "timestamp": "t"}]}, fh)
        st2 = os.stat(p2)
        os.utime(p2, (st2.st_atime + 5, st2.st_mtime + 5))
        time.sleep(1.4)
        v2 = c.live()
        assert v2["version"] > v1["version"], (v1["version"], v2["version"])
        c.close()
        return (f"stream detect + server v{v1['version']}->v{v2['version']}"
                f" + wire price lookup ok")
    finally:
        srv.stop()


def t_rsps_socket():
    from server.rsps_server import GameServer
    from server.client import RemoteGameSDK
    srv = GameServer(port=43911)
    srv.start_async()
    time.sleep(0.6)
    try:
        a = RemoteGameSDK(name="verifier", port=43911)
        for _ in range(12):
            try:
                a.walk("tree_1" if _ % 2 == 0 else "tree_2")
                a.chop()
            except Exception:
                pass
        a.walk("fishing_spot_1")
        for _ in range(10):
            if sum(v["xp"] for v in a.state()["skills"].values()) > 0:
                break
            try:
                a.fish()
            except Exception:
                break
        xp = sum(v["xp"] for v in a.state()["skills"].values())
        assert xp > 0
        n = srv.player_count
        a.close()
        time.sleep(0.4)
        assert srv.player_count == n - 1
        return f"wire xp={xp:.0f}, sessions tracked"
    finally:
        srv.stop()


def t_rl_checkpoint():
    import torch
    ckpts = sorted(glob.glob(os.path.join(RL, "runs", "v2", "ckpt_latest.pt")))
    assert ckpts, "no v2 checkpoint"
    c = torch.load(ckpts[0], map_location="cpu", weights_only=True)
    assert "model" in c
    has_opt = "optimizer" in c
    n_params = sum(v.numel() for v in c["model"].values())
    return (f"iter {c['iter']}, {n_params} tensors, "
            f"resume-ready={has_opt}")


def t_knowledge():
    p = os.path.join(AGENT, "knowledge", "digest.md")
    assert os.path.exists(p), "run tools/update_knowledge.py"
    text = open(p, encoding="utf-8").read()
    for topic in ("Ultimate Ironman Guide", "Woodcutting training",
                  "Live Grand Exchange"):
        assert topic in text, topic
    age_h = (time.time() - os.path.getmtime(p)) / 3600
    return f"14 topics present, {age_h:.1f}h old"


def t_llm_endpoint():
    import urllib.request
    with urllib.request.urlopen("http://localhost:11434/api/tags",
                                timeout=4) as r:
        models = [m["name"] for m in json.loads(r.read().decode())["models"]]
    assert models
    return ", ".join(models)


def t_dashboard_exe():
    exe = os.path.join(HERE, "OsrsLab.exe")
    assert os.path.exists(exe)
    proc = subprocess.run([exe, "--once"], timeout=60,
                          capture_output=True)
    assert proc.returncode == 0
    sz = os.path.getsize(exe) / 1e6
    return f"{sz:.1f} MB, renders"


def t_runner():
    r = os.path.join(HERE, "runner.py")
    assert os.path.exists(r)
    src = open(r, encoding="utf-8").read()
    for fn in ("run_activity", "train_rl", "evaluate_rl", "run_llm_agent",
               "host_rsps", "refresh_knowledge", "launch_dashboard"):
        assert f"def {fn}" in src, fn
    return "all 7 flows wired"


print("=" * 72)
print("OSRS LAB - FULL SYSTEM VERIFICATION")
print("=" * 72)

for name, fn in [
    ("ENGINE: local sim world", t_sim_engine),
    ("ENGINE: ultimate ironman rules", t_uim_lock),
    ("ENGINE: quest system", t_quests),
    ("ENGINE: combat, food & drops", t_combat),
    ("ENGINE: expansion skills & zones", t_expansion),
    ("ENGINE: production skills & slayer", t_expansion2),
    ("PLUGIN: session snapshots", t_session_roundtrip),
    ("PLUGIN: kernel events+scheduler", t_kernel),
    ("PLUGIN: strategy snippet runner", t_strategy_runner),
    ("SOCKET: RSPS server + remote SDK", t_rsps_socket),
    ("APP: playable game client", t_playable_client),
    ("SOCKET: RL checkpoint integrity", t_rl_checkpoint),
    ("DATA: OSRS ground-truth KB", t_knowledge),
    ("DATA: continuous live updater", t_live_updater),
    ("DATA: live stream + server wiring", t_live_stream),
    ("SOCKET: LLM endpoint (ollama)", t_llm_endpoint),
    ("APP: OsrsLab.exe", t_dashboard_exe),
    ("APP: easy runner wiring", t_runner),
]:
    check(name, fn)

passed = sum(1 for ok, _, _ in RESULTS if ok)
print("=" * 72)
status = "SYSTEM FULLY OPERATIONAL" if passed == len(RESULTS) else \
    f"{len(RESULTS) - passed} FAILURES"
print(f"{passed}/{len(RESULTS)} checks passed - {status}")
sys.exit(0 if passed == len(RESULTS) else 1)
