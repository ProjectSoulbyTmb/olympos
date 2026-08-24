"""OsrsLab Play - a graphical client for the local OSRS Lab RSPS engine.

Connects to the authoritative JSON-lines game server on 127.0.0.1:43590
and starts one automatically if none is running. All art is procedural -
no external assets, nothing from Jagex.

Controls:
  WASD / arrows   move one tile
  Left click      interact with an adjacent entity (or walk there)
  C chop   M mine   F fish   R cook at range   T smelt
  K attack nearest NPC        E eat best food
  B bank deposit-all          G talk to quest giver
  U bury bones                O offer bones at shrine
  Y thieve adjacent stall     I cast spell at nearest NPC
  L agility lap               Q plant/harvest herbs
  N fletch best bow           X craft leather best
  Z quaff best potion         J slayer master (assign/claim)
  C cut planks (workshop)     F build furniture (workshop)
  V lay/check bird snare      P toggle run
  H help overlay              ESC quit
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(HERE, "osrs-llm-agent")
sys.path.insert(0, AGENT)
sys.path.insert(0, HERE)

from server.rsps_server import GameServer            # noqa: E402
from server.client import RemoteGameSDK, RspsError   # noqa: E402
from game.world import GRID                          # noqa: E402
from rsps_audio import Audio                         # noqa: E402

DEFAULT_PORT = 43590
TILE = 28
PANEL = 330
FPS = 30

FOODS = ("cooked_meat", "cake", "shrimp")

COLORS = {
    "grass_a": (46, 92, 46), "grass_b": (52, 100, 50),
    "grid": (40, 78, 40),
    "panel": (24, 24, 30), "panel_edge": (70, 70, 90),
    "text": (230, 230, 235), "dim": (150, 150, 165),
    "good": (120, 220, 120), "bad": (235, 110, 110),
    "gold": (235, 200, 80),
    "tree": (30, 120, 60), "trunk": (90, 60, 30),
    "rock": (130, 130, 140), "water": (48, 96, 190),
    "range": (200, 90, 40), "bank": (210, 175, 60),
    "shop": (150, 90, 200), "furnace": (170, 70, 40),
    "quest": (240, 220, 90),
    "npc": (200, 70, 70), "player": (240, 240, 255),
}


def connect_or_host(port=DEFAULT_PORT):
    try:
        return RemoteGameSDK(name="adventurer", port=port), None
    except OSError:
        pass
    srv = GameServer(port=port)
    srv.start_async()
    time.sleep(0.7)
    try:
        return RemoteGameSDK(name="adventurer", port=port), srv
    except RspsError:
        srv.stop()
        raise


class XpDrop:
    def __init__(self, skill, amount, pos):
        self.skill, self.amount, self.pos = skill, amount, list(pos)
        self.born = time.time()

    @property
    def alive(self):
        return time.time() - self.born < 1.6


class Floater:
    def __init__(self, text, color, pos):
        self.text, self.color, self.pos = text, color, list(pos)
        self.born = time.time()

    @property
    def alive(self):
        return time.time() - self.born < 1.1


def tile_center_px(pos):
    return (pos[0] * TILE + TILE // 2, pos[1] * TILE + TILE // 2)


class Game:
    def __init__(self, sdk):
        import pygame
        self.pg = pygame
        pygame.init()
        self.audio = Audio(pygame)
        w = GRID * TILE + PANEL
        h = max(GRID * TILE, 560)
        self.screen = pygame.display.set_mode((w, h))
        pygame.display.set_caption("OsrsLab - local RSPS")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 15)
        self.big = pygame.font.SysFont("consolas", 19, bold=True)
        self.small = pygame.font.SysFont("consolas", 12)
        self.sdk = sdk
        self.st = sdk.state()
        self.prev_xp = {s: v["xp"] for s, v in self.st["skills"].items()}
        self.prev_levels = {s: v["level"] for s, v in self.st["skills"].items()}
        self.render_pos = [float(x) for x in self.st["position"]]
        self.drops, self.floaters = [], []
        self.banner, self.banner_until = "", 0.0
        self.show_help = False
        self.frames_left = None
        if os.environ.get("RSPS_CLIENT_FRAMES"):
            self.frames_left = int(os.environ["RSPS_CLIENT_FRAMES"])
        self._sync_render_pos(True)
        self.ticker, self._ticker_v, self._last_live_poll = [], -1, 0.0

    # ---------- helpers ----------

    def _sync_render_pos(self, snap=False):
        tx, ty = self.st["position"]
        rx, ry = self.render_pos
        if snap:
            self.render_pos = [float(tx), float(ty)]
        else:
            k = 0.35
            self.render_pos[0] += (tx - rx) * min(1.0, k)
            self.render_pos[1] += (ty - ry) * min(1.0, k)

    def _diff_xp(self):
        gain_sfx = {"woodcutting": "chop", "mining": "mine",
                    "fishing": "splash", "runecrafting": "cast",
                    "thieving": "steal", "prayer": "eat"}
        for skill, cur in self.st["skills"].items():
            delta = cur["xp"] - self.prev_xp.get(skill, 0)
            if delta > 0:
                self.drops.append(XpDrop(skill, int(delta),
                                         self.render_pos))
                sfx = gain_sfx.get(skill)
                if sfx and skill not in ("attack", "strength", "defence",
                                         "hitpoints", "ranged", "magic"):
                    self.audio.play(sfx)
            if cur["level"] > self.prev_levels.get(skill, 1):
                self.banner = f"LEVEL UP! {skill} -> {cur['level']}"
                self.banner_until = time.time() + 2.5
                self.audio.play("levelup")
            self.prev_xp[skill], self.prev_levels[skill] = \
                cur["xp"], cur["level"]

    def act(self, fn, *a):
        try:
            res = fn(*a)
        except (RspsError, Exception) as e:
            self.banner = str(e).splitlines()[0][:58]
            self.banner_until = time.time() + 1.8
            return None
        before_pos = tuple(self.st["position"])
        self.st = self.sdk.state()
        self._diff_xp()
        return res, before_pos

    def nearest_npc(self):
        cands = [n for n in self.st["npcs"]
                 if n["status"] != "(respawning)"]
        if not cands:
            return None
        return min(cands, key=lambda n: n["distance"])

    # ---------- actions ----------

    def do_move(self, dx, dy=None):
        x, y = self.st["position"]
        if dy is None:
            x, y = dx
        else:
            x, y = x + dx, y + dy
        self.act(self.sdk.move_to, int(x), int(y))

    def do_attack_nearest(self):
        npc = self.nearest_npc()
        if not npc:
            self._flash("no npcs in the world")
            return
        if npc["distance"] > 1:
            self.do_move(npc["pos"])
        r = self.act(self.sdk.attack, npc["name"])
        if r and r[0]:
            res = r[0]
            px = tile_center_px(self.st["position"])
            if res.get("player_damage"):
                self.audio.play("hit")
                self.floaters.append(
                    Floater(f"-{res['player_damage']}", COLORS["good"], px))
            if res.get("retaliation_damage"):
                self.floaters.append(
                    Floater(f"OUCH -{res['retaliation_damage']}",
                            COLORS["bad"], px))
            if res.get("killed"):
                self.audio.play("kill")
                if res.get("drops"):
                    self.floaters.append(
                        Floater("+ " + ", ".join(res["drops"]),
                                COLORS["gold"], (px[0], px[1] - 18)))
                    if any(d.startswith("coins") for d in res["drops"]):
                        self.audio.play("coin")

    def do_cast(self):
        npc = self.nearest_npc()
        if not npc:
            self._flash("no npcs in the world")
            return
        inv = self.sdk.inventory()
        skills = self.sdk.skills()
        spell = None
        if (skills.get("magic", 0) >= 17 and inv.get("fire_rune")):
            spell = "fire_strike"
        elif inv.get("air_rune"):
            spell = "wind_strike"
        if spell is None:
            self._flash("need air/fire runes - buy or craft them")
            return
        if npc["distance"] > 4:
            self.do_move(npc["pos"])
        self.audio.play("cast")
        r = self.act(self.sdk.cast, spell, npc["name"])
        if r and r[0]:
            res = r[0]
            px = tile_center_px(self.st["position"])
            if res.get("player_damage"):
                self.audio.play("hit")
                self.floaters.append(
                    Floater(f"{spell[:3]} -{res['player_damage']}",
                            COLORS["good"], px))
            if res.get("killed") and res.get("drops"):
                self.audio.play("kill")
                self.floaters.append(
                    Floater("+ " + ", ".join(res["drops"]),
                            COLORS["gold"], (px[0], px[1] - 18)))

    def do_bury(self):
        r = self.act(self.sdk.bury_bones)
        if r:
            self.audio.play("eat")

    def do_offer(self):
        self.act(self.sdk.offer_bones)

    def do_thieve(self):
        stalls = [n for n in self.st["nodes"]
                  if n["kind"] == "stall" and n["distance"] <= 1
                  and n["status"] != "(owner watching)"]
        if not stalls:
            self._flash("stand next to an unguarded stall")
            return
        stalls.sort(key=lambda s: s["name"] != "cake_stall")
        r = self.act(self.sdk.thieve, stalls[0]["name"])
        if r and r[0]:
            self.audio.play("coin")

    def do_lap(self):
        r = self.act(self.sdk.run_lap)
        if r:
            self.audio.play("steal")

    def do_patch(self):
        st = self.st
        adj = [n for n in st["nodes"] if n["kind"] == "patch"
               and n["distance"] <= 1]
        inv = self.sdk.inventory()
        seeds = [s for s in ("guam_seed", "tarromin_seed", "ranarr_seed")
                 if inv.get(s)]
        if seeds:
            r = self.act(self.sdk.plant, seeds[-1])
            if r is not None:
                return
        self.act(self.sdk.harvest)

    def do_fletch(self):
        r = self.act(self.sdk.fletch)
        if r:
            self.audio.play("chop")

    def do_leather(self):
        inv = self.sdk.inventory()
        item = "leather_body" if inv.get("cowhide") else "leather_gloves"
        r = self.act(self.sdk.craft_leather, item)
        if r:
            self.audio.play("chop")

    def do_quaff(self):
        inv = self.sdk.inventory()
        for p in ("defence_potion", "strength_potion", "attack_potion"):
            if inv.get(p):
                self.audio.play("eat")
                self.act(self.sdk.quaff, p)
                return
        self._flash("no potions in inventory")

    def do_slayer(self):
        task = self.st.get("slayer_task")
        if task and (task["done"] >= task["need"]):
            self.act(self.sdk.claim_slayer)
        else:
            self.act(self.sdk.assign_slayer)

    def do_planks(self):
        r = self.act(self.sdk.cut_planks)
        if r:
            self.audio.play("chop")

    def do_build(self):
        inv = self.sdk.inventory()
        lvl = self.sdk.skills("construction")
        for name, req in (("wooden_chair", 8),
                          ("wooden_bookcase", 4),
                          ("crude_wooden_chair", 1)):
            if lvl >= req and inv.get("plank"):
                r = self.act(self.sdk.build, name)
                if r:
                    self.audio.play("chop")
                    return
        self._flash("need planks + nails + saw/hammer at the workshop")

    def do_trap(self):
        st = self.st
        adj = [n for n in st["nodes"] if n["kind"] == "hunting"
               and n["distance"] <= 1]
        if not adj:
            self._flash("stand next to the hunting ground")
            return
        traps = st.get("traps", {})
        ready = [k for k, t in traps.items()
                 if st["tick"] >= t.get("ready_at", 0)]
        if ready:
            if self.act(self.sdk.check_trap):
                self.audio.play("steal")
        elif self.sdk.inventory().get("bird_snare"):
            self.act(self.sdk.lay_trap)
        else:
            self._flash("no bird snares (buy one at the shop)")

    def do_eat(self):
        inv = self.sdk.inventory()
        for f in FOODS:
            if inv.get(f):
                self.audio.play("eat")
                self.act(self.sdk.eat, f)
                return
        self._flash("no food in inventory")

    def do_smelt(self):
        inv = self.sdk.inventory()
        if inv.get("copper_ore") and inv.get("tin_ore"):
            self.act(self.sdk.smelt, "bronze_bar")
        elif inv.get("iron_ore"):
            self.act(self.sdk.smelt, "iron_bar")
        else:
            self._flash("need copper+tin or iron ore")

    def do_cook(self):
        self.act(self.sdk.cook)

    def _flash(self, msg):
        self.banner = msg
        self.banner_until = time.time() + 1.8

    def click_world(self, mx, my):
        tx, ty = mx // TILE, my // TILE
        clicked = {"nodes": [], "npcs": []}
        for n in self.st["nodes"]:
            if tuple(n["pos"]) == (tx, ty):
                clicked["nodes"].append(n)
        for n in self.st["npcs"]:
            if tuple(n["pos"]) == (tx, ty):
                clicked["npcs"].append(n)
        node = next(iter(clicked["nodes"]), None)
        npc = next(iter(clicked["npcs"]), None)
        if node is None and npc is not None:
            if npc["distance"] > 1 or npc["status"] == "(respawning)":
                self.do_move((tx, ty))
                return
            r = self.act(self.sdk.attack, npc["name"])
            if r and r[0]:
                res = r[0]
                px = tile_center_px(self.st["position"])
                if res.get("retaliation_damage"):
                    self.floaters.append(
                        Floater(f"OUCH -{res['retaliation_damage']}",
                                COLORS["bad"], px))
            return
        if node is None:
            self.do_move((tx, ty))
            return
        if node["distance"] > 1:
            self.do_move((tx, ty))
            return
        kind = node["kind"]
        name = node["name"]
        if kind == "tree":
            self.act(self.sdk.chop)
        elif kind == "rock":
            self.act(self.sdk.mine)
        elif kind == "spot":
            self.act(self.sdk.fish)
        elif kind == "range":
            self.do_cook()
        elif kind == "bank":
            self.act(self.sdk.deposit_all)
        elif kind == "furnace":
            self.do_smelt()
        elif kind == "altar":
            rune = node["resource"]
            r = self.act(self.sdk.craft_rune, rune)
            if r and r[0]:
                self.audio.play("cast")
            elif kind == "shrine":
                self.do_offer()
            elif kind == "stall":
                self.do_thieve()
            elif kind == "course":
                self.do_lap()
            elif kind == "patch":
                self.do_patch()
            elif kind == "master":
                self.do_slayer()
            elif name == "quest_giver":
                self.act(self.sdk.talk_quest)
        elif kind == "shop":
            self._flash("press 1/2/3 to buy sword tiers here")

    # ---------- drawing ----------

    def draw_world(self):
        pg = self.pg
        scr = self.screen.subsurface((0, 0, GRID * TILE, GRID * TILE))
        for y in range(GRID):
            for x in range(GRID):
                c = COLORS["grass_a"] if (x + y) % 2 else COLORS["grass_b"]
                pg.draw.rect(scr, c, (x * TILE, y * TILE, TILE, TILE))
                pg.draw.rect(scr, COLORS["grid"],
                             (x * TILE, y * TILE, TILE, TILE), 1)
        for n in self.st["nodes"]:
            cx, cy = tile_center_px(n["pos"])
            kind, res, name = n["kind"], n["resource"], n["name"]
            depleted = "respawn" in n["status"]
            if kind == "tree":
                col = COLORS["trunk"] if depleted else COLORS["tree"]
                pg.draw.circle(scr, col, (cx, cy - 4), TILE // 3)
                pg.draw.rect(scr, COLORS["trunk"],
                             (cx - 3, cy + 4, 6, 10))
            elif kind == "rock":
                col = (70, 70, 75) if depleted else COLORS["rock"]
                pg.draw.polygon(scr, col,
                                [(cx - 11, cy + 9), (cx, cy - 10),
                                 (cx + 11, cy + 9)])
            elif kind == "spot":
                pg.draw.circle(scr, COLORS["water"], (cx, cy), TILE // 3)
                pg.draw.circle(scr, (120, 170, 240), (cx, cy), 4)
            elif kind == "range":
                pg.draw.rect(scr, COLORS["range"],
                             (cx - 12, cy - 8, 24, 16), border_radius=4)
            elif kind == "altar":
                col = (170, 200, 240) if res == "air_rune" else (240, 150, 90)
                pg.draw.circle(scr, col, (cx, cy), 11, 3)
                pg.draw.circle(scr, col, (cx, cy), 4)
            elif kind == "shrine":
                pg.draw.circle(scr, COLORS["quest"], (cx, cy), 10, 2)
                pg.draw.line(scr, COLORS["quest"], (cx - 4, cy - 4),
                             (cx + 4, cy + 4), 2)
                pg.draw.line(scr, COLORS["quest"], (cx + 4, cy - 4),
                             (cx - 4, cy + 4), 2)
            elif kind == "stall":
                awning = (120, 180, 90) if res == "fruit_stall" \
                    else (220, 160, 100)
                watched = n["status"] == "(owner watching)"
                pg.draw.rect(scr, (110, 80, 50),
                             (cx - 12, cy - 6, 24, 14))
                pg.draw.polygon(scr, awning,
                                [(cx - 13, cy - 6), (cx + 13, cy - 6),
                                 (cx + 9, cy - 12), (cx - 9, cy - 12)])
                if watched:
                    pg.draw.circle(scr, COLORS["bad"], (cx + 10, cy - 12), 4)
            elif kind == "course":
                pg.draw.rect(scr, (90, 140, 200),
                             (cx - 12, cy - 4, 24, 10), border_radius=5)
                for i in range(3):
                    pg.draw.line(scr, (200, 220, 250),
                                 (cx - 8 + i * 8, cy - 2),
                                 (cx - 4 + i * 8, cy + 2), 2)
            elif kind == "patch":
                grown = "(growing)" not in n["status"] and \
                        n["status"] != ""
                pg.draw.rect(scr, (100, 70, 40), (cx - 11, cy - 7, 22, 14))
                col = (110, 200, 110) if grown else (70, 130, 70)
                pg.draw.circle(scr, col, (cx, cy), 5 if grown else 3)
            elif kind == "master":
                pg.draw.circle(scr, (60, 60, 80), (cx, cy), 11)
                pg.draw.circle(scr, COLORS["gold"], (cx, cy), 11, 2)
            elif kind == "bank":
                pg.draw.rect(scr, COLORS["bank"],
                             (cx - 13, cy - 9, 26, 18), border_radius=4)
                pg.draw.rect(scr, (120, 95, 20),
                             (cx - 13, cy - 9, 26, 18), 2, border_radius=4)
            elif kind == "shop":
                pg.draw.rect(scr, COLORS["shop"],
                             (cx - 12, cy - 9, 24, 18), border_radius=6)
            elif kind == "furnace":
                pg.draw.rect(scr, COLORS["furnace"],
                             (cx - 11, cy - 11, 22, 22), border_radius=3)
                pg.draw.circle(scr, (250, 160, 60), (cx, cy + 2), 5)
            elif name == "quest_giver":
                pg.draw.circle(scr, COLORS["quest"], (cx, cy), 10)
            lbl = {"tree": "T", "rock": "R", "spot": "~", "range": "C",
                   "bank": "$", "shop": "S", "furnace": "F"}.get(kind, "?")
            if name == "quest_giver":
                lbl = "!"
            img = self.small.render(lbl, True, (20, 20, 20))
            scr.blit(img, (cx - img.get_width() // 2,
                           cy - img.get_height() // 2))
        for n in self.st["npcs"]:
            cx, cy = tile_center_px(n["pos"])
            respawning = n["status"] == "(respawning)"
            kind_col = {"goblin": (150, 170, 60), "cow": (230, 230, 225),
                        "giant_rat": (140, 120, 100),
                        "zombie": (90, 150, 80), "guard": (80, 110, 210)}
            col = (110, 110, 115) if respawning else \
                kind_col.get(n["kind"], COLORS["npc"])
            pg.draw.circle(scr, col, (cx, cy), 11)
            hp = 0 if respawning else int(n["status"].split()[1][:-1])
            max_hp = {"goblin": 5, "cow": 8, "giant_rat": 6}.get(n["kind"], 5)
            frac = max(0.0, min(1.0, hp / max_hp)) if max_hp else 0
            pg.draw.rect(scr, (40, 40, 40), (cx - 12, cy - 18, 24, 4))
            pg.draw.rect(scr, (220, 60, 60),
                         (cx - 12, cy - 18, int(24 * frac), 4))
            tag = self.small.render(f"{n['kind']} {n['level']}", True,
                                    COLORS["dim"])
            scr.blit(tag, (cx - tag.get_width() // 2, cy + 12))
        px, py = self.render_pos
        cx = px * TILE + TILE // 2
        cy = py * TILE + TILE // 2
        pg.draw.circle(self.screen, COLORS["player"], (int(cx), int(cy)), 11)
        pg.draw.circle(self.screen, (80, 110, 240), (int(cx), int(cy)), 11, 2)
        hp_cur = self.st["hp"]["current"]
        hp_max = self.st["hp"]["max"]
        frac = max(0.0, min(1.0, hp_cur / hp_max))
        pg.draw.rect(self.screen, (40, 40, 40), (cx - 12, cy - 18, 24, 4))
        pg.draw.rect(self.screen, (90, 220, 90),
                     (cx - 12, cy - 18, int(24 * frac), 4))

    def draw_panel(self):
        pg = self.pg
        scr = self.screen
        ox = GRID * TILE
        pg.draw.rect(scr, COLORS["panel"], (ox, 0, PANEL, scr.get_height()))
        pg.draw.line(scr, COLORS["panel_edge"], (ox, 0),
                     (ox, scr.get_height()), 2)
        x = ox + 14

        def line(txt, y, col=None, font=None):
            img = (font or self.font).render(txt, True, col or COLORS["text"])
            scr.blit(img, (x, y))
            return y + img.get_height() + 4

        y = 12
        y = line("OSRS LAB", y, COLORS["gold"], self.big)
        hp = self.st["hp"]
        y = line(f"HP {hp['current']}/{hp['max']}    "
                 f"style: {self.st['combat_style']}", y)
        bar_w, bar_h = PANEL - 28, 10
        frac = max(0.0, min(1.0, hp["current"] / hp["max"]))
        pg.draw.rect(scr, (40, 40, 45), (x, y, bar_w, bar_h),
                     border_radius=3)
        pg.draw.rect(scr, (90, 220, 90), (x, y, int(bar_w * frac), bar_h),
                     border_radius=3)
        y += bar_h + 6
        y = line(f"coins {self.st['coins']}    energy "
                 f"{int(self.st['energy'])}%    run {'on' if self.st['run'] else 'off'}",
                 y, COLORS["dim"])

        y += 6
        y = line("-- skills --", y, COLORS["dim"])
        skills = self.st["skills"]
        names = list(skills)
        colw = (PANEL - 28) // 2
        for i, s in enumerate(names):
            row, col = divmod(i, 2)
            sx = x + col * colw
            sy = y + row * 17
            img = self.small.render(
                f"{s[:9]:<9} {skills[s]['level']:>2}", True,
                COLORS["text"] if skills[s]["level"] > 1 else COLORS["dim"])
            scr.blit(img, (sx, sy))
        y += ((len(names) + 1) // 2) * 17 + 8

        y = line("-- inventory --", y, COLORS["dim"])
        inv_txt = self.st["inventory"]
        for chunk in [inv_txt[i:i + 44]
                      for i in range(0, len(inv_txt), 44)]:
            y = line(chunk, y, COLORS["dim"])
        y += 6

        y = line("-- log --", y, COLORS["dim"])
        for ev in self.st["events"][-9:]:
            y = line(ev[-52:], y, COLORS["dim"])

        help_y = scr.get_height() - 118
        pg.draw.line(scr, COLORS["panel_edge"], (x, help_y - 8),
                     (ox + PANEL - 14, help_y - 8))
        hy = help_y
        hy = line("WASD move | click interact", hy, COLORS["dim"],
                  self.small)
        hy = line("K attack  E eat  B bank", hy, COLORS["dim"], self.small)
        hy = line("R cook  T smelt  G quest", hy, COLORS["dim"], self.small)
        hy = line("P run  H help  ESC quit", hy, COLORS["dim"], self.small)

    def draw_overlays(self):
        pg = self.pg
        now = time.time()
        for d in self.drops[:]:
            if not d.alive:
                self.drops.remove(d)
                continue
            age = now - d.born
            alpha = max(0, 255 - int(age * 180))
            txt = self.small.render(f"+{d.amount} {d.skill[:4]} xp", True,
                                    COLORS["good"])
            txt.set_alpha(alpha)
            self.screen.blit(txt, (d.pos[0] - 20, d.pos[1] - 14 - age * 22))
        for f in self.floaters[:]:
            if not f.alive:
                self.floaters.remove(f)
                continue
            age = now - f.born
            txt = self.small.render(f.text, True, f.color)
            txt.set_alpha(max(0, 255 - int(age * 240)))
            self.screen.blit(txt, (f.pos[0] - 20, f.pos[1] - 10 - age * 26))
        if now < self.banner_until and self.banner:
            img = self.big.render(self.banner, True, COLORS["gold"])
            w = img.get_width()
            pg.draw.rect(self.screen, (20, 20, 25),
                         (GRID * TILE // 2 - w // 2 - 10, 8, w + 20, 30),
                         border_radius=6)
            self.screen.blit(img, (GRID * TILE // 2 - w // 2, 12))
        if self.show_help:
            pg.draw.rect(self.screen, (15, 15, 22),
                         (40, 60, GRID * TILE - 80, 300), border_radius=8)
            pg.draw.rect(self.screen, COLORS["panel_edge"],
                         (40, 60, GRID * TILE - 80, 300), 2, border_radius=8)
            lines = [
                "HOW TO PLAY",
                "",
                "Move: WASD or arrow keys (or click a tile)",
                "Click adjacent things to use them:",
                "  tree->chop  rock->mine  water->fish",
                "  range->cook  furnace->smelt  bank->deposit all",
                "  altar->craft runes  shrine->offer bones",
                "  stall->thieve  course->agility lap",
                "  patch->plant/harvest herbs  master->slayer task",
                "  quest giver (!)->talk   NPC->attack",
                "",
                "Keys:",
                "  K attack (bow to 3 tiles)   I cast spell",
                "  E eat   Z quaff potion   B bank   G quests",
                "  U bury bones   O offer shrine   Y thieve stall",
                "  L agility lap   Q plant/harvest herbs",
                "  N fletch bow   X craft leather   J slayer task",
                "  R cook   T smelt   P run   H close this",
                "",
                "Shop keys: 1-3 swords, 4 shortbow, 5 arrows x10",
                "East zone: willows, coal, essence, altars, stalls.",
                "Loop idea: kill cows -> hide -> leather armour;",
                "farm herbs -> potions; slayer tasks for coins.",
                "Death is safe: you respawn with items.",
            ]
            yy = 74
            for ln in lines:
                fnt = self.big if ln.startswith("HOW") else self.small
                col = COLORS["gold"] if ln.startswith("HOW") \
                    else COLORS["text"]
                img = fnt.render(ln, True, col)
                self.screen.blit(img, (56, yy))
                yy += 17 if not ln.startswith("HOW") else 26

    def draw_buy_hints(self):
        hints = {"1": ("bronze_sword", 20), "2": ("iron_sword", 90),
                 "3": ("steel_sword", 400), "4": ("shortbow", 25),
                 "5": ("bronze_arrow x10", 20)}
        at_shop = any(n["kind"] == "shop" and n["distance"] <= 1
                      for n in self.st["nodes"])
        if not at_shop:
            return
        y = GRID * TILE - 82
        for key, (item, price) in hints.items():
            img = self.small.render(f"[{key}] {item} {price}c", True,
                                    COLORS["gold"])
            self.screen.blit(img, (8, y))
            y += 16

    WATCHLIST = ("Abyssal whip", "Rune pickaxe", "Iron ore", "Cowhide")

    def poll_live(self):
        now = time.time()
        if now - self._last_live_poll < 10:
            return
        self._last_live_poll = now
        try:
            live = self.sdk.live(items=list(self.WATCHLIST))
        except Exception:
            return
        v = live.get("version", 0)
        if v != self._ticker_v:
            self._ticker_v = v
            self.ticker = [(p["item"], p.get("high"), p.get("low"))
                           for p in live.get("prices", [])]

    def draw_ticker(self):
        if not self.ticker:
            return
        x = 8
        y = GRID * TILE - 18
        for item, hi, lo in self.ticker:
            txt = f"{item[:14]} {('buy ' + format(hi, ',')) if hi else '-'}"
            img = self.small.render(txt, True, COLORS["good"])
            self.screen.blit(img, (x, y))
            x += img.get_width() + 6
            txt2 = f"sell {format(lo, ',')}" if lo else "-"
            img2 = self.small.render(txt2, True, COLORS["bad"])
            self.screen.blit(img2, (x, y))
            x += img2.get_width() + 14

    # ---------- loop ----------

    def run(self):
        while True:
            if self.frames_left is not None:
                if self.frames_left <= 0:
                    self.pg.quit()
                    return 0
                self.frames_left -= 1
            for e in self.pg.event.get():
                if e.type == self.pg.QUIT:
                    self.pg.quit()
                    return 0
                if e.type == self.pg.KEYDOWN:
                    k = e.key
                    if k == self.pg.K_ESCAPE:
                        self.pg.quit()
                        return 0
                    elif k in (self.pg.K_h,):
                        self.show_help = not self.show_help
                    elif k in (self.pg.K_UP, self.pg.K_w):
                        self.do_move(0, -1)
                    elif k in (self.pg.K_DOWN, self.pg.K_s):
                        self.do_move(0, 1)
                    elif k in (self.pg.K_LEFT, self.pg.K_a):
                        self.do_move(-1, 0)
                    elif k in (self.pg.K_RIGHT, self.pg.K_d):
                        self.do_move(1, 0)
                    elif k == self.pg.K_k:
                        self.do_attack_nearest()
                    elif k == self.pg.K_e:
                        self.do_eat()
                    elif k == self.pg.K_r:
                        self.do_cook()
                    elif k == self.pg.K_t:
                        self.do_smelt()
                    elif k == self.pg.K_b:
                        self.act(self.sdk.deposit_all)
                    elif k == self.pg.K_g:
                        self.act(self.sdk.talk_quest)
                    elif k == self.pg.K_i:
                        self.do_cast()
                    elif k == self.pg.K_u:
                        self.do_bury()
                    elif k == self.pg.K_o:
                        self.do_offer()
                    elif k == self.pg.K_y:
                        self.do_thieve()
                    elif k == self.pg.K_l:
                        self.do_lap()
                    elif k == self.pg.K_q:
                        self.do_patch()
                    elif k == self.pg.K_n:
                        self.do_fletch()
                    elif k == self.pg.K_x:
                        self.do_leather()
                    elif k == self.pg.K_z:
                        self.do_quaff()
                    elif k == self.pg.K_j:
                        self.do_slayer()
                    elif k == self.pg.K_c:
                        self.do_planks()
                    elif k == self.pg.K_f:
                        self.do_build()
                    elif k == self.pg.K_v:
                        self.do_trap()
                    elif k == self.pg.K_p:
                        new_run = not self.st["run"]
                        self.act(self.sdk.set_run, new_run)
                    elif k in (self.pg.K_1, self.pg.K_2, self.pg.K_3,
                               self.pg.K_4, self.pg.K_5):
                        item = {self.pg.K_1: ("bronze_sword", 1),
                                self.pg.K_2: ("iron_sword", 1),
                                self.pg.K_3: ("steel_sword", 1),
                                self.pg.K_4: ("shortbow", 1),
                                self.pg.K_5: ("bronze_arrow", 10)}[k]
                        self.audio.play("coin")
                        self.act(self.sdk.buy, item[0], item[1])
                if e.type == self.pg.MOUSEBUTTONDOWN and e.button == 1:
                    if e.pos[0] < GRID * TILE:
                        self.click_world(*e.pos)
            self._sync_render_pos()
            self.poll_live()
            self.screen.fill(COLORS["panel"])
            self.draw_world()
            self.draw_panel()
            self.draw_buy_hints()
            self.draw_ticker()
            self.draw_overlays()
            self.pg.display.flip()
            self.clock.tick(FPS)


def main():
    sdk, host = connect_or_host()
    code = Game(sdk).run()
    sys.exit(code)


if __name__ == "__main__":
    main()
