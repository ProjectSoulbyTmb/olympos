"""OsrsLab Play - a graphical client for the local OSRS Lab RSPS engine.

Connects to the authoritative JSON-lines game server on 127.0.0.1:43590
and starts one automatically if none is running. All art and audio are
procedural - no external assets, nothing from Jagex.

Controls:
  WASD / arrows   move one tile
  Left click      interact with an adjacent entity (or walk there)
  Right click     context menu for anything (world, inventory, ground)
  ENTER           open chat box (shared channel)
  G               pick up items under your feet
  C chop   M mine   F fish   R cook at range   T smelt
  K attack nearest NPC        E eat best food
  B bank deposit-all          G talk to quest giver (adjacent)
  U bury bones                O offer bones at shrine
  Y thieve adjacent stall     I cast selected spell at nearest NPC
  L agility lap               Q plant/harvest herbs
  N fletch best bow           X craft leather best
  Z quaff best potion         J slayer master (assign/claim)
  V lay/check bird snare      P toggle run
  H help overlay              ESC quit / close menu

Panel tabs (click): Stats Inv Quests Magic Prayer Bank Shop
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(HERE, "osrs-llm-agent")
sys.path.insert(0, AGENT)
sys.path.insert(0, HERE)

from server.rsps_server import GameServer            # noqa: E402
from server.client import RemoteGameSDK, RspsError   # noqa: E402
from game.world import GRID                          # noqa: E402
from game import content as GC                       # noqa: E402
from rsps_audio import Audio                         # noqa: E402

DEFAULT_PORT = 43590
TILE = 28
PANEL = 330
FPS = 30
CATACOMBS_RECT = getattr(GC, "CATACOMBS_RECT", None)

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
    "dungeon": (26, 22, 34),
}

NPC_BODY = {
    "goblin": (150, 170, 60), "cow": (230, 230, 225),
    "giant_rat": (140, 120, 100), "zombie": (90, 150, 80),
    "guard": (80, 110, 210), "skeleton": (225, 222, 205),
    "hobgoblin": (170, 90, 60), "vulcan_guardian": (190, 60, 40),
}
NPC_MAX_HP = {k: v["hp"] for k, v in GC.NPCS.items()}


def connect_or_host(port=DEFAULT_PORT):
    try:
        return RemoteGameSDK(name="adventurer", port=port,
                             channel="main"), None
    except OSError:
        pass
    srv = GameServer(port=port)
    srv.start_async()
    time.sleep(0.7)
    try:
        return RemoteGameSDK(name="adventurer", port=port,
                             channel="main"), srv
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


class Splat:
    """OSRS-style hit splat: a small rounded diamond with a number."""

    def __init__(self, amount, pos, taken=False):
        self.amount, self.pos, self.taken = int(amount), list(pos), taken
        self.born = time.time()

    @property
    def alive(self):
        return time.time() - self.born < 0.75


def tile_center_px(pos):
    return (pos[0] * TILE + TILE // 2, pos[1] * TILE + TILE // 2)


def wrap_text(font, text, width):
    words = text.split()
    lines, cur = [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if font.size(trial)[0] <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


class Game:
    def __init__(self, sdk):
        import pygame
        self.pg = pygame
        pygame.init()
        pygame.mixer.set_reserved(1)
        self.audio = Audio(pygame)
        self.amb_channel = pygame.mixer.Channel(0)
        self.amb_kind = None
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
        self.prev_levels = {s: v["level"] for s, v in
                            self.st["skills"].items()}
        self.render_pos = [float(x) for x in self.st["position"]]
        self.drops, self.floaters, self.splats = [], [], []
        self.banner, self.banner_until = "", 0.0
        self.show_help = False
        self.frames_left = None
        if os.environ.get("RSPS_CLIENT_FRAMES"):
            self.frames_left = int(os.environ["RSPS_CLIENT_FRAMES"])
        self._sync_render_pos(True)
        self.ticker, self._ticker_v, self._last_live_poll = [], -1, 0.0
        # --- new client systems ---
        self.menu = None                 # {"items":[(label,fn)],"pos":..}
        self.tab = "stats"
        self.tabs = ["stats", "inv", "quests", "magic", "prayer",
                     "bank", "shop"]
        self.facing = [1, 0]
        self.last_move_t = 0.0
        self.lunge = None                # (t0, dx, dy)
        self.chat_lines = []             # {"from","text"}
        self.chat_input = ""
        self.chat_mode = False
        self.selected_spell = None
        self.sprites = {}
        self._shop_prices_cache = None
        self._amb_update()

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
        after_pos = tuple(self.st["position"])
        if max(abs(after_pos[0] - before_pos[0]),
               abs(after_pos[1] - before_pos[1])) > 2:
            self.audio.play("teleport")
        self._diff_xp()
        self._amb_update()
        return res, before_pos

    def _amb_update(self):
        if not self.audio.enabled:
            return
        x, y = self.st["position"]
        kind = "catacombs" if CATACOMBS_RECT and \
            CATACOMBS_RECT[0] <= x <= CATACOMBS_RECT[2] and \
            CATACOMBS_RECT[1] <= y <= CATACOMBS_RECT[3] else "surface"
        if kind == self.amb_kind:
            return
        self.amb_kind = kind
        try:
            self.amb_channel.stop()
            snd = self.audio.ambience(self.pg, kind)
            if snd:
                snd.set_volume(0.35)
                self.amb_channel.play(snd, loops=-1)
        except Exception:
            pass

    def nearest_npc(self):
        cands = [n for n in self.st["npcs"]
                 if n["status"] != "(respawning)"]
        if not cands:
            return None
        return min(cands, key=lambda n: n["distance"])

    def drain_chat(self):
        try:
            got = self.sdk._drain_chat()
        except Exception:
            got = []
        for c in got:
            frm = c.get("from", "?")
            self.chat_lines.append(f"{frm}: {c.get('text', '')}")
        del self.chat_lines[:-9]

    # ---------- actions ----------

    def do_move(self, dx, dy=None):
        x, y = self.st["position"]
        if dy is None:
            nx, ny = dx
        else:
            nx, ny = x + dx, y + dy
        if nx != x or ny != y:
            self.facing = [1 if nx > x else -1 if nx < x else 0,
                           1 if ny > y else -1 if ny < y else 0]
            self.last_move_t = time.time()
        self.act(self.sdk.move_to, int(nx), int(ny))

    def _attack_common(self, npc):
        if npc["distance"] > 1:
            self.do_move(npc["pos"])
        r = self.act(self.sdk.attack, npc["name"])
        px = tile_center_px(npc["pos"])
        if r and r[0]:
            res = r[0]
            pd = res.get("player_damage") or 0
            rd = res.get("retaliation_damage") or 0
            if pd:
                self.splats.append(Splat(pd, npc["pos"]))
                self.audio.play("hit")
            if rd:
                pp = tile_center_px(self.st["position"])
                self.splats.append(Splat(rd, self.st["position"],
                                         taken=True))
                self.floaters.append(
                    Floater("OUCH", COLORS["bad"], pp))
            self.lunge = (time.time(),
                          npc["pos"][0] - self.st["position"][0],
                          npc["pos"][1] - self.st["position"][1])
            if res.get("killed"):
                self.audio.play("kill")
                if res.get("drops"):
                    self.floaters.append(
                        Floater("+ " + ", ".join(res["drops"]),
                                COLORS["gold"], (px[0], px[1] - 18)))
                    if any(d.startswith("coins") for d in res["drops"]):
                        self.audio.play("coin")

    def do_attack_nearest(self):
        npc = self.nearest_npc()
        if not npc:
            self._flash("no npcs in the world")
            return
        self._attack_common(npc)

    def do_cast(self):
        npc = self.nearest_npc()
        if not npc:
            self._flash("no npcs in the world")
            return
        inv = self.sdk.inventory()
        skills = self.sdk.skills()
        spell = self.selected_spell
        if spell is None:
            spell = None
            if (skills.get("magic", 0) >= 17 and inv.get("fire_rune")):
                spell = "fire_strike"
            elif (skills.get("magic", 0) >= 9
                  and inv.get("earth_rune") and inv.get("air_rune")):
                spell = "earth_strike"
            elif (skills.get("magic", 0) >= 5 and inv.get("water_rune")):
                spell = "water_strike"
            elif inv.get("air_rune"):
                spell = "wind_strike"
        if spell is None:
            self._flash("need runes - buy or craft them")
            return
        spec = GC.SPELLS.get(spell)
        missing = [r for r, n in (spec or {}).get("runes", {}).items()
                   if inv.get(r, 0) < n]
        if spec is None or missing:
            self._flash(f"{spell} needs "
                        f"{', '.join(missing) or 'higher magic'}")
            return
        if npc["distance"] > 4:
            self.do_move(npc["pos"])
        self.audio.play("cast")
        r = self.act(self.sdk.cast, spell, npc["name"])
        if r and r[0]:
            res = r[0]
            pd = res.get("player_damage") or 0
            if pd:
                self.splats.append(Splat(pd, npc["pos"]))
                self.audio.play("hit")
            if res.get("killed") and res.get("drops"):
                self.audio.play("kill")
                px = tile_center_px(npc["pos"])
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
        for f in GC.FOOD:
            if f.startswith("raw"):
                continue
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

    def do_pickup(self):
        r = self.act(self.sdk.pickup)
        if r:
            self.audio.play("coin")

    def do_prayer(self, name):
        was = name in (self.st.get("prayers", {}).get("active", []))
        r = self.act(self.sdk.toggle_prayer, name)
        if r is not None and not was:
            self.audio.play("pray")

    def _flash(self, msg):
        self.banner = msg
        self.banner_until = time.time() + 1.8

    # ---------- context menus ----------

    def close_menu(self):
        self.menu = None

    def open_menu(self, items, pos):
        if not items:
            return
        self.menu = {"items": items[:14], "pos": pos}

    def world_menu_at(self, tx, ty, mx, my):
        items = [("Walk here",
                  lambda t=(tx, ty): self.do_move(t))]
        for g in self.st.get("ground", []):
            if tuple(g["pos"]) == (tx, ty):
                items.append((f"Take {g['item']} x{g['n']}",
                              lambda gi=g: self._take_ground(gi)))
        for n in self.st["nodes"]:
            if tuple(n["pos"]) != (tx, ty):
                continue
            verb = NODE_VERBS.get(n["kind"])
            label = verb[0].format(name=n["name"], res=n.get("resource"))
            if n["distance"] <= 1:
                items.append((label,
                              lambda nn=n, fn=verb[1]: fn(self, nn)))
            elif verb:
                items.append((f"{n['name']} ({n['distance']} tiles away)",
                              lambda nn=n: self.do_move(nn["pos"])))
        for n in self.st["npcs"]:
            if tuple(n["pos"]) != (tx, ty):
                continue
            if n["status"] == "(respawning)":
                continue
            rng_ok = self.st["combat_style"] == "ranged" \
                and n["distance"] <= 3
            if n["distance"] <= 1 or rng_ok:
                items.append((f"Attack {n['kind']} (lvl {n['level']})",
                              lambda nn=n: self._attack_common(nn)))
            else:
                items.append((f"Attack {n['kind']} - move closer",
                              lambda nn=n: self.do_move(nn["pos"])))
        for p in self.st.get("players", []):
            if tuple(p["pos"]) == (tx, ty):
                items.append((f"{p['name']} (adventurer)",
                              lambda: None))
        self.open_menu(items, (mx, my))

    def _take_ground(self, g):
        if tuple(self.st["position"]) != tuple(g["pos"]):
            self.do_move(g["pos"])
        self.act(self.sdk.pickup)

    def inv_item_verbs(self, item):
        verbs = []
        if item in GC.FOOD and not item.startswith("raw"):
            verbs.append(("Eat " + item,
                          lambda it=item: (self.audio.play("eat"),
                                           self.act(self.sdk.eat, it))))
        if item.endswith("bones"):
            verbs.append(("Bury " + item,
                          lambda it=item: (self.audio.play("eat"),
                                           self.act(self.sdk.bury_bones))))
        if item in GC.POTIONS:
            verbs.append(("Quaff " + item,
                          lambda it=item: (self.audio.play("eat"),
                                           self.act(self.sdk.quaff, it))))
        if item in GC.WEAPONS or item in GC.BOWS:
            verbs.append((f"Wield {item} (auto-best)",
                          lambda it=item: self._flash(
                              "your best gear is always wielded here")))
        if item in GC.ARMOURS:
            verbs.append((f"Wear {item} (auto-best)",
                          lambda it=item: self._flash(
                              "your best armour is always worn here")))
        if item in GC.TREES or item.endswith("_logs"):
            verbs.append(("Fletch best bow",
                          lambda: self.do_fletch()))
            verbs.append(("Light a fire",
                          lambda it=item: self.act(self.sdk.light_fire)))
        verbs.append(("Drop " + item,
                      lambda it=item: self.act(self.sdk.drop, it)))
        verbs.append(("Drop all " + item,
                      lambda it=item: self.act(self.sdk.drop, it,
                                               self.sdk.inventory().get(it,
                                                                        0))))
        return verbs

    # ---------- click routing ----------

    def click_world(self, mx, my, button=1):
        tx, ty = mx // TILE, my // TILE
        if button == 3:
            self.world_menu_at(tx, ty, mx, my)
            return
        for g in self.st.get("ground", []):
            if tuple(g["pos"]) == (tx, ty):
                self.do_move((tx, ty))
                self.act(self.sdk.pickup)
                return
        for n in self.st["npcs"]:
            if tuple(n["pos"]) == (tx, ty) \
                    and n["status"] != "(respawning)":
                self._attack_common(n)
                return
        node = next((n for n in self.st["nodes"]
                     if tuple(n["pos"]) == (tx, ty)), None)
        if node is not None and node["distance"] <= 1:
            verb = NODE_VERBS.get(node["kind"])
            if verb:
                verb[1](self, node)
                return
        self.do_move((tx, ty))

    NODE_VERBS = {
        "tree": ("Chop down tree", lambda s, n: s.act(s.sdk.chop)),
        "rock": ("Mine rock", lambda s, n: s.act(s.sdk.mine)),
        "spot": ("Net fishing spot", lambda s, n: s.act(s.sdk.fish)),
        "range": ("Cook at range", lambda s, n: s.do_cook()),
        "bank": ("Bank everything", lambda s, n: s.act(s.sdk.deposit_all)),
        "furnace": ("Smelt ores", lambda s, n: s.do_smelt()),
        "altar": ("Craft runes",
                  lambda s, n: s.act(s.sdk.craft_rune,
                                     n.get("resource"))),
        "shrine": ("Offer bones", lambda s, n: s.do_offer()),
        "stall": ("Steal from stall", lambda s, n: s.do_thieve()),
        "course": ("Run agility lap", lambda s, n: s.do_lap()),
        "patch": ("Plant/harvest herbs", lambda s, n: s.do_patch()),
        "master": ("Slayer master", lambda s, n: s.do_slayer()),
        "workshop": ("Use workshop", lambda s, n: s.do_planks()),
        "ladder": ("Climb ladder",
                   lambda s, n: s.do_move(tuple(n["pos"]))),
        "npc_talker": ("Talk to wise man",
                       lambda s, n: s.act(s.sdk.talk_to, "wise_man")),
    }

    # ---------- drawing ----------

    def _sprite(self, key, builder):
        img = self.sprites.get(key)
        if img is None:
            img = builder()
            self.sprites[key] = img
        return img

    def draw_world(self):
        pg = self.pg
        W = GRID * TILE
        scr = self.screen.subsurface((0, 0, W, W))
        for y in range(GRID):
            for x in range(GRID):
                base = COLORS["grass_a"] if (x + y) % 2 else \
                    COLORS["grass_b"]
                if CATACOMBS_RECT and \
                        CATACOMBS_RECT[0] <= x <= CATACOMBS_RECT[2] and \
                        CATACOMBS_RECT[1] <= y <= CATACOMBS_RECT[3]:
                    base = COLORS["dungeon"] if (x + y) % 2 else \
                        (32, 27, 42)
                pg.draw.rect(scr, base, (x * TILE, y * TILE, TILE, TILE))
                if not (CATACOMBS_RECT and
                        CATACOMBS_RECT[0] <= x <= CATACOMBS_RECT[2]):
                    pg.draw.rect(scr, COLORS["grid"],
                                 (x * TILE, y * TILE, TILE, TILE), 1)
        for g in self.st.get("ground", []):
            cx, cy = tile_center_px(g["pos"])
            pg.draw.circle(scr, (120, 100, 60), (cx, cy + 4), 6)
            pg.draw.circle(scr, (160, 135, 80), (cx, cy + 2), 5)
            tag = self.small.render(str(g["n"]), True, COLORS["gold"])
            scr.blit(tag, (cx - 3, cy - 10))
        for n in self.st["nodes"]:
            cx, cy = tile_center_px(n["pos"])
            kind, res, name = n["kind"], n["resource"], n["name"]
            depleted = "respawn" in n["status"]
            if kind == "tree":
                col = COLORS["trunk"] if depleted else COLORS["tree"]
                pg.draw.circle(scr, col, (cx, cy - 6), TILE // 3)
                pg.draw.circle(scr, (40, 145, 72), (cx - 3, cy - 8),
                               TILE // 4)
                pg.draw.rect(scr, COLORS["trunk"],
                             (cx - 3, cy + 4, 6, 10))
            elif kind == "rock":
                col = (70, 70, 75) if depleted else COLORS["rock"]
                pg.draw.polygon(scr, col,
                                [(cx - 11, cy + 9), (cx - 4, cy - 11),
                                 (cx + 3, cy - 4), (cx + 11, cy + 9)])
                pg.draw.polygon(scr, (160, 160, 168),
                                [(cx - 4, cy - 11), (cx + 3, cy - 4),
                                 (cx - 1, cy + 2)])
            elif kind == "spot":
                pg.draw.circle(scr, COLORS["water"], (cx, cy), TILE // 3)
                pg.draw.arc(scr, (120, 170, 240),
                            (cx - 8, cy - 4, 16, 8), 3.34, 6.28, 2)
            elif kind == "range":
                pg.draw.rect(scr, COLORS["range"],
                             (cx - 12, cy - 8, 24, 16), border_radius=4)
                pg.draw.circle(scr, (250, 180, 80), (cx + 6, cy - 2), 4)
            elif kind == "altar":
                col = (170, 200, 240) if res == "air_rune" else \
                    (240, 150, 90)
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
                    pg.draw.circle(scr, COLORS["bad"], (cx + 10, cy - 12),
                                   4)
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
                pg.draw.line(scr, (120, 95, 20), (cx, cy - 9), (cx, cy + 9),
                             2)
            elif kind == "shop":
                pg.draw.rect(scr, COLORS["shop"],
                             (cx - 12, cy - 9, 24, 18), border_radius=6)
                pg.draw.rect(scr, (210, 190, 240), (cx - 6, cy - 3, 12, 8))
            elif kind == "furnace":
                pg.draw.rect(scr, COLORS["furnace"],
                             (cx - 11, cy - 11, 22, 22), border_radius=3)
                pg.draw.circle(scr, (250, 160, 60), (cx, cy + 2), 5)
            elif kind == "ladder":
                pg.draw.rect(scr, (90, 65, 40), (cx - 10, cy - 12, 20, 24),
                             border_radius=3)
                for i in (-6, 0, 6):
                    pg.draw.line(scr, (150, 120, 80),
                                 (cx - 8, cy + i), (cx + 8, cy + i), 2)
            elif kind == "npc_talker":
                pg.draw.circle(scr, (120, 160, 220), (cx, cy), 10)
                pg.draw.circle(scr, (60, 60, 90), (cx, cy), 10, 2)
                pg.draw.circle(scr, (240, 240, 250), (cx - 3, cy - 2), 2)
                pg.draw.circle(scr, (240, 240, 250), (cx + 3, cy - 2), 2)
            lbl = {"tree": "T", "rock": "R", "spot": "~", "range": "C",
                   "bank": "$", "shop": "S", "furnace": "F"}.get(kind, "?")
            if name == "quest_giver":
                lbl = "!"
            if lbl and kind not in ("npc_talker", "ladder"):
                img = self.small.render(lbl, True, (20, 20, 20))
                scr.blit(img, (cx - img.get_width() // 2,
                               cy - img.get_height() // 2))
            if name == "quest_giver":
                pg.draw.circle(scr, COLORS["quest"], (cx, cy), 10)
        moving = max(abs(self.render_pos[0] - self.st["position"][0]),
                     abs(self.render_pos[1] - self.st["position"][1])) > 0.08
        bob = int(abs(time.time() * 8 % 2 - 1) * 2) if moving else 0
        for n in self.st["npcs"]:
            cx, cy = tile_center_px(n["pos"])
            respawning = n["status"] == "(respawning)"
            col = (110, 110, 115) if respawning else \
                NPC_BODY.get(n["kind"], COLORS["npc"])
            body_off = bob if not respawning else 0
            pg.draw.circle(scr, col, (cx, cy + body_off // 2), 11)
            pg.draw.circle(scr, (30, 25, 25), (cx - 3, cy - 3), 2)
            pg.draw.circle(scr, (30, 25, 25), (cx + 3, cy - 3), 2)
            hp = 0 if respawning else \
                int(n["status"].split()[1][:-1]) if \
                n["status"].startswith("(hp") else 0
            max_hp = NPC_MAX_HP.get(n["kind"], 5)
            frac = max(0.0, min(1.0, hp / max_hp)) if max_hp else 0
            pg.draw.rect(scr, (40, 40, 40), (cx - 12, cy - 18, 24, 4))
            pg.draw.rect(scr, (220, 60, 60),
                         (cx - 12, cy - 18, int(24 * frac), 4))
            boss = n["kind"] == "vulcan_guardian"
            tag = self.small.render(
                f"{n['kind']} {n['level']}" + (" BOSS" if boss else ""),
                True, COLORS["gold"] if boss else COLORS["dim"])
            scr.blit(tag, (cx - tag.get_width() // 2, cy + 12))
        px, py = self.render_pos
        cx = px * TILE + TILE // 2
        cy = py * TILE + TILE // 2 - bob
        lunge_dx = lunge_dy = 0
        if self.lunge:
            age = time.time() - self.lunge[0]
            if age < 0.18:
                mag = 5 * (1 - abs(age / 0.09 - 1))
                norm = max(1, abs(self.lunge[1]) + abs(self.lunge[2]))
                lunge_dx = int(5 * self.lunge[1] / norm * mag) // 1
                lunge_dy = int(5 * self.lunge[2] / norm * mag) // 1
            else:
                self.lunge = None
        pg.draw.circle(self.screen, COLORS["player"],
                       (int(cx) + lunge_dx, int(cy) + lunge_dy), 11)
        pg.draw.circle(self.screen, (80, 110, 240),
                       (int(cx) + lunge_dx, int(cy) + lunge_dy), 11, 2)
        fx, fy = self.facing
        if fx or fy:
            pg.draw.circle(self.screen, (40, 40, 90),
                           (int(cx) + fx * 4 + lunge_dx,
                            int(cy) + fy * 4 + lunge_dy - 2), 2)
        hp_cur = self.st["hp"]["current"]
        hp_max = self.st["hp"]["max"]
        frac = max(0.0, min(1.0, hp_cur / hp_max))
        pg.draw.rect(self.screen, (40, 40, 40),
                     (cx - 12, cy - 18, 24, 4))
        pg.draw.rect(self.screen, (90, 220, 90),
                     (cx - 12, cy - 18, int(24 * frac), 4))

    def draw_minimap(self):
        pg = self.pg
        size = 100
        ox = GRID * TILE - size - 8
        oy = 8
        s = size / GRID
        panel = self.screen.subsurface((ox, oy, size, size))
        pg.draw.rect(panel, (18, 30, 18), (0, 0, size, size))
        for n in self.st["nodes"]:
            col = {"tree": (40, 160, 80), "rock": (150, 150, 158),
                   "spot": (70, 120, 220), "bank": (220, 190, 80),
                   "shop": (170, 110, 220), "range": (210, 110, 60),
                   "furnace": (190, 90, 50), "ladder": (160, 120, 70),
                   "altar": (190, 200, 250)}.get(
                n["kind"], (90, 140, 90))
            pg.draw.circle(panel, col,
                           (int(n["pos"][0] * s + s / 2),
                            int(n["pos"][1] * s + s / 2)), 2)
        for n in self.st["npcs"]:
            if n["status"] == "(respawning)":
                continue
            col = COLORS["gold"] if n["kind"] == "vulcan_guardian" \
                else (230, 80, 80)
            pg.draw.circle(panel, col,
                           (int(n["pos"][0] * s + s / 2),
                            int(n["pos"][1] * s + s / 2)), 2)
        for p in self.st.get("players", []):
            pg.draw.circle(panel, (120, 220, 240),
                           (int(p["pos"][0] * s + s / 2),
                            int(p["pos"][1] * s + s / 2)), 3)
        me = self.st["position"]
        pg.draw.circle(panel, (255, 255, 255),
                       (int(me[0] * s + s / 2), int(me[1] * s + s / 2)), 3)
        pg.draw.rect(self.screen, COLORS["panel_edge"],
                     (ox, oy, size, size), 2)

    def minimap_click(self, mx, my):
        size = 100
        ox = GRID * TILE - size - 8
        oy = 8
        if not (ox <= mx <= ox + size and oy <= my <= oy + size):
            return False
        s = size / GRID
        tx = int((mx - ox) / s)
        ty = int((my - oy) / s)
        self.do_move((max(0, min(GRID - 1, tx)),
                      max(0, min(GRID - 1, ty))))
        return True

    def draw_panel(self):
        pg = self.pg
        scr = self.screen
        ox = GRID * TILE
        pg.draw.rect(scr, COLORS["panel"], (ox, 0, PANEL, scr.get_height()))
        pg.draw.line(scr, COLORS["panel_edge"], (ox, 0),
                     (ox, scr.get_height()), 2)
        x = ox + 14
        y = 10
        for t in self.tabs:
            label = t.upper()
            img = self.small.render(label, True,
                                    COLORS["gold"] if t == self.tab
                                    else COLORS["dim"])
            rect = pg.Rect(x - 2, y - 2, img.get_width() + 6, 17)
            hot = rect.collidepoint(pg.mouse.get_pos())
            if t == self.tab:
                pg.draw.rect(scr, (45, 45, 58), rect, border_radius=3)
            elif hot:
                pg.draw.rect(scr, (36, 36, 46), rect, border_radius=3)
            scr.blit(img, (x, y))
            x += rect.width + 6
        y += 24
        drawer = getattr(self, f"_tab_{self.tab}", None)
        if drawer:
            drawer(scr, ox + 14, y)
        hy = scr.get_height() - 44
        hints = ["L-click interact | R-click menu | G take | ENTER chat",
                 "K attack  E eat  B bank  H help  ESC quit"]
        for i, txt in enumerate(hints):
            img = self.small.render(txt, True, COLORS["dim"])
            scr.blit(img, (ox + 14, hy + i * 15))

    def _clickable(self, scr, rect, label, cb, col=None, font=None):
        pg = self.pg
        hot = rect.collidepoint(pg.mouse.get_pos())
        if hot:
            pg.draw.rect(scr, (38, 38, 48), rect, border_radius=3)
        scr.blit((font or self.font).render(label, True,
                                            col or COLORS["text"]),
                 (rect.x + 2, rect.y + 1))
        self._hot[rect.topleft] = (rect.copy(), cb)

    _hot = {}

    def _tab_stats(self, scr, x, y):
        hp = self.st["hp"]
        pr = self.st.get("prayers", {})
        y = self._line(scr, x, y,
                       f"HP {hp['current']}/{hp['max']}  style "
                       f"{self.st['combat_style']}")
        bar_w = PANEL - 28
        frac = max(0.0, min(1.0, hp["current"] / hp["max"]))
        self.pg.draw.rect(scr, (40, 40, 45), (x, y, bar_w, 9),
                          border_radius=3)
        self.pg.draw.rect(scr, (90, 220, 90),
                          (x, y, int(bar_w * frac), 9), border_radius=3)
        y += 13
        pfrac = 0.0
        if pr.get("cap"):
            pfrac = max(0.0, min(1.0, pr.get("points", 0) / pr["cap"]))
        self.pg.draw.rect(scr, (40, 40, 45), (x, y, bar_w, 9),
                          border_radius=3)
        self.pg.draw.rect(scr, (120, 180, 240),
                          (x, y, int(bar_w * pfrac), 9), border_radius=3)
        y += 13
        y = self._line(scr, x, y,
                       f"coins {self.st['coins']}   energy "
                       f"{int(self.st['energy'])}%   run "
                       f"{'on' if self.st['run'] else 'off'}",
                       COLORS["dim"])
        skills = self.st["skills"]
        names = list(skills)
        colw = (PANEL - 28) // 2
        for i, s in enumerate(names):
            row, col = divmod(i, 2)
            img = self.small.render(
                f"{s[:9]:<9} {skills[s]['level']:>2}", True,
                COLORS["text"] if skills[s]["level"] > 1 else COLORS["dim"])
            scr.blit(img, (x + col * colw, y + row * 16))
        y += ((len(names) + 1) // 2) * 16 + 8
        self._line(scr, x, y, "-- log --", COLORS["dim"])
        y += 18
        for ev in self.st["events"][-8:]:
            y = self._line(scr, x, y, ev[-52:], COLORS["dim"])

    def _line(self, scr, x, y, txt, col=None, font=None):
        img = (font or self.font).render(txt, True,
                                         col or COLORS["text"])
        scr.blit(img, (x, y))
        return y + img.get_height() + 4

    def _tab_inv(self, scr, x, y):
        inv = self._inv_dict()
        slots = [(i, n) for i, n in sorted(inv.items()) for _ in range(n)]
        cols, cw, ch = 4, (PANEL - 28) // 4, 34
        used = min(len(slots), 28)
        self._hot_local = {}
        for idx in range(28):
            row, col = divmod(idx, cols)
            r = self.pg.Rect(x + col * cw, y + row * ch, cw - 4, ch - 4)
            self.pg.draw.rect(scr, (33, 33, 41), r, border_radius=4)
            if idx >= used:
                continue
            item = slots[idx][0]
            short = item[:9]
            img = self.small.render(short, True, COLORS["text"])
            scr.blit(img, (r.x + 3, r.y + 3))
            cnt = self._line_count(item)
            if cnt > 1:
                img2 = self.small.render(f"x{cnt}", True, COLORS["gold"])
                scr.blit(img2, (r.right - img2.get_width() - 3, r.y + 3))
            mouse = self.pg.mouse.get_pos()
            if r.collidepoint(mouse):
                self.pg.draw.rect(scr, COLORS["panel_edge"], r, 1,
                                  border_radius=4)
        hint_y = y + 7 * ch + 4
        self._line(scr, x, hint_y,
                   "L-click: use/eat/wield | R-click: menu",
                   COLORS["dim"], self.small)

    def _inv_dict(self):
        raw = self.st["inventory"]
        if isinstance(raw, dict):
            return raw
        out = {}
        for part in raw.split(","):
            part = part.strip()
            if not part or part == "(empty)":
                continue
            if " x" in part:
                name, _, num = part.rpartition(" x")
                try:
                    out[name] = int(num)
                except ValueError:
                    pass
            else:
                out[part] = out.get(part, 0) + 1
        return out

    def _line_count(self, item):
        return self._inv_dict().get(item, 0)

    def _tab_quests(self, scr, x, y):
        y = self._line(scr, x, y, "-- quest journal --", COLORS["dim"])
        for q, status in self.st["quests"].items():
            spec = GC.QUESTS.get(q, {})
            col = {"claimed": COLORS["good"],
                   "active": COLORS["gold"]}.get(status, COLORS["dim"])
            mark = {"claimed": "[done]", "active": "[in progress]",
                    "not_started": "[not started]"}.get(
                status, status)
            y = self._line(scr, x, y, f"{q} {mark}", col)
            desc = spec.get("description", "")
            for ln in wrap_text(self.small, desc, PANEL - 30)[:2]:
                y = self._line(scr, x + 12, y, ln, COLORS["dim"],
                               self.small)
        y = self._line(scr, x, y + 4,
                       "accept/turn-in: talk to ! or the wise man",
                       COLORS["dim"], self.small)

    def _tab_magic(self, scr, x, y):
        y = self._line(scr, x, y, "-- spellbook -- (click to select, "
                                  "then I casts at nearest)", COLORS["dim"])
        inv = self._inv_dict()
        m_lvl = self.st["skills"].get("magic", {}).get("level", 1)
        for name, spec in sorted(GC.SPELLS.items()):
            runes = ", ".join(f"{r}x{n}" for r, n
                              in spec["runes"].items())
            ok = m_lvl >= spec["req"]
            sel = self.selected_spell == name
            label = f"{name} (lvl {spec['req']}) {runes}" \
                    f"{' SELECTED' if sel else ''}"
            r = self.pg.Rect(x - 2, y, PANEL - 28, 18)
            self._clickable(scr, r, label,
                            lambda nm=name: setattr(self, "selected_spell",
                                                    nm),
                            COLORS["good"] if ok and sel else
                            COLORS["text"] if ok else COLORS["dim"])
            y += 20
        castable = self.selected_spell is not None
        y = self._line(scr, x, y + 6, "press I to cast at nearest NPC"
                                      if castable else
                                      "select a spell above, then I",
                       COLORS["dim"], self.small)

    def _tab_prayer(self, scr, x, y):
        pr = self.st.get("prayers", {})
        y = self._line(scr, x, y, f"-- prayer -- points "
                                  f"{pr.get('points', 0)}/"
                                  f"{pr.get('cap', 0)} (recharge: shrine)",
                       COLORS["dim"])
        active = set(pr.get("active", []))
        p_lvl = self.st["skills"].get("prayer", {}).get("level", 1)
        for name, spec in sorted(GC.PRAYERS.items()):
            ok = p_lvl >= spec["req"]
            on = name in active
            label = f"{'[ON] ' if on else ''}{name} (lvl {spec['req']})" \
                    f"" if ok else f"{name} - needs prayer {spec['req']}"
            r = self.pg.Rect(x - 2, y, PANEL - 28, 18)
            self._clickable(scr, r, label,
                            lambda nm=name: self.do_prayer(nm),
                            COLORS["good"] if on else
                            COLORS["text"] if ok else COLORS["dim"])
            y += 20

    def _tab_bank(self, scr, x, y):
        near = any(n["kind"] == "bank" and n["distance"] <= 1
                   for n in self.st["nodes"])
        y = self._line(scr, x, y, "-- bank chest --" +
                       ("" if near else " (stand next to the bank!)"),
                       COLORS["dim"])
        bank = self.st.get("bank_contents") or {}
        if isinstance(bank, str):
            bank = {}
        y = self._line(scr, x, y, "bank: L-click withdraw 1 / "
                                  "R-click all", COLORS["dim"], self.small)
        for i, (item, n) in enumerate(sorted(bank.items())):
            r = self.pg.Rect(x - 2 + (i % 2) * ((PANEL - 28) // 2),
                             y + (i // 2) * 19, (PANEL - 28) // 2 - 4, 17)
            self._clickable(scr, r, f"{item[:12]} x{n}",
                            lambda it=item: self.act(self.sdk.withdraw,
                                                     it),
                            COLORS["gold"], self.small)
            self._rclick[(r.x, r.y)] = (
                r, lambda it=item: self.act(self.sdk.withdraw, it, None))
            y_row = y + (i // 2) * 19
            if i > 11:
                break
        y += 12 * 19 + 6
        y = self._line(scr, x, y, "inventory: L-click deposit 1",
                       COLORS["dim"], self.small)
        for i, (item, n) in enumerate(sorted(self._inv_dict().items())):
            r = self.pg.Rect(x - 2 + (i % 2) * ((PANEL - 28) // 2),
                             y + (i // 2) * 19, (PANEL - 28) // 2 - 4, 17)
            self._clickable(scr, r, f"{item[:12]} x{n}",
                            lambda it=item: self.act(self.sdk.deposit,
                                                     it),
                            COLORS["text"], self.small)
            if i > 11:
                break

    _rclick = {}

    def _tab_shop(self, scr, x, y):
        near = any(n["kind"] == "shop" and n["distance"] <= 1
                   for n in self.st["nodes"])
        y = self._line(scr, x, y, "-- general store --" +
                       ("" if near else " (stand next to the shop!)"),
                       COLORS["dim"])
        prices = self._fetch_prices()
        for i, item in enumerate(GC.SHOP_STOCK):
            price = prices.get(item, "?")
            afford = isinstance(price, int) and price <= self.st["coins"]
            r = self.pg.Rect(x - 2, y, PANEL - 28, 17)
            self._clickable(scr, r,
                            f"buy {item:<16} {price}c",
                            lambda it=item: self._buy(it),
                            COLORS["gold"] if afford else COLORS["dim"],
                            self.small)
            y += 18

    def _fetch_prices(self):
        if self._shop_prices_cache is None:
            try:
                self._shop_prices_cache = dict(self.sdk.shop_prices())
            except Exception:
                self._shop_prices_cache = {}
        return self._shop_prices_cache

    def _buy(self, item):
        self.audio.play("coin")
        self.act(self.sdk.buy, item)

    def draw_dialogue(self):
        dlg = self.st.get("dialogue")
        if not dlg:
            return None
        pg = self.pg
        W = GRID * TILE
        bw = min(430, W - 40)
        lines = wrap_text(self.font, dlg.get("text", ""), bw - 24)
        bh = 56 + len(lines) * 17 + len(dlg["options"]) * 22 + 10
        bx, by = (W - bw) // 2, W - bh - 60
        pg.draw.rect(self.screen, (18, 18, 26), (bx, by, bw, bh),
                     border_radius=8)
        pg.draw.rect(self.screen, COLORS["gold"], (bx, by, bw, bh), 2,
                     border_radius=8)
        title = self.big.render(dlg["npc"].replace("_", " ").title(),
                                True, COLORS["gold"])
        self.screen.blit(title, (bx + 12, by + 8))
        yy = by + 34
        for ln in lines:
            self.screen.blit(self.font.render(ln, True, COLORS["text"]),
                             (bx + 12, yy))
            yy += 17
        yy += 4
        hits = []
        for i, opt in enumerate(dlg["options"]):
            r = self.pg.Rect(bx + 10, yy, bw - 20, 20)
            hot = r.collidepoint(pg.mouse.get_pos())
            pg.draw.rect(self.screen, (34, 34, 46) if hot
                         else (26, 26, 36), r, border_radius=4)
            self.screen.blit(self.font.render(f"> {opt}", True,
                                              COLORS["gold"]),
                             (r.x + 8, r.y + 2))
            hits.append((r, i))
            yy += 22
        return {"hits": hits, "box": (bx, by, bw, bh)}

    def draw_chat(self):
        pg = self.pg
        hgt = 96
        wid = GRID * TILE // 2
        x0, y0 = 6, GRID * TILE - hgt - 24
        overlay = self.pg.Surface((wid, hgt), self.pg.SRCALPHA)
        overlay.fill((10, 10, 16, 150))
        self.screen.blit(overlay, (x0, y0))
        yy = y0 + 2
        for ln in self.chat_lines[-6:]:
            self.screen.blit(self.small.render(ln[:70], True,
                                               COLORS["text"]), (x0 + 4,
                                                                 yy))
            yy += 14
        if self.chat_mode:
            pg.draw.rect(self.screen, (30, 30, 40),
                         (x0, GRID * TILE - 22, wid, 20), border_radius=3)
            self.screen.blit(self.font.render(
                f">{self.chat_input}_", True, COLORS["gold"]),
                (x0 + 4, GRID * TILE - 21))
        elif not self.chat_lines:
            self.screen.blit(self.small.render(
                "ENTER to chat (channel main)", True, COLORS["dim"]),
                (x0 + 4, GRID * TILE - 18))

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
        for sp in self.splats[:]:
            if not sp.alive:
                self.splats.remove(sp)
                continue
            cx, cy = tile_center_px(sp.pos)
            col = (200, 60, 60) if sp.taken else (70, 160, 230)
            pg.draw.circle(self.screen, col, (cx, cy), 11)
            pg.draw.circle(self.screen, (25, 25, 25), (cx, cy), 11, 2)
            num = self.small.render(str(sp.amount), True, (255, 255, 255))
            self.screen.blit(num, (cx - num.get_width() // 2,
                                   cy - num.get_height() // 2))
        if now < self.banner_until and self.banner:
            img = self.big.render(self.banner, True, COLORS["gold"])
            w = img.get_width()
            pg.draw.rect(self.screen, (20, 20, 25),
                         (GRID * TILE // 2 - w // 2 - 10, 8, w + 20, 30),
                         border_radius=6)
            self.screen.blit(img, (GRID * TILE // 2 - w // 2, 12))
        self.draw_minimap()
        self.draw_chat()
        if self.menu:
            self._draw_menu()
        dlg = self.draw_dialogue()
        self._dialogue_hits = dlg
        if self.show_help:
            self._draw_help()

    def _draw_menu(self):
        pg = self.pg
        mx, my = self.menu["pos"]
        wmax = max((self.font.size(lbl)[0] for lbl, _ in self.menu["items"]
                    ), default=100) + 16
        hgt = len(self.menu["items"]) * 20 + 8
        pg.draw.rect(self.screen, (16, 16, 22),
                     (mx, my, wmax, hgt), border_radius=4)
        pg.draw.rect(self.screen, COLORS["panel_edge"],
                     (mx, my, wmax, hgt), 1, border_radius=4)
        self._menu_hits = []
        yy = my + 4
        for lbl, cb in self.menu["items"]:
            r = self.pg.Rect(mx + 4, yy, wmax - 8, 18)
            hot = r.collidepoint(pg.mouse.get_pos())
            if hot:
                pg.draw.rect(self.screen, (40, 40, 54), r,
                             border_radius=3)
            self.screen.blit(self.font.render(lbl, True, COLORS["text"]),
                             (r.x + 4, r.y + 1))
            self._menu_hits.append((r, cb))
            yy += 20

    def _draw_help(self):
        pg = self.pg
        pg.draw.rect(self.screen, (15, 15, 22),
                     (40, 60, GRID * TILE - 80, 330), border_radius=8)
        pg.draw.rect(self.screen, COLORS["panel_edge"],
                     (40, 60, GRID * TILE - 80, 330), 2, border_radius=8)
        lines = [
            "HOW TO PLAY",
            "",
            "Move: WASD/arrows, click a tile, or click the minimap",
            "Left click things to use them; RIGHT CLICK for options",
            "Right-click inventory tabs items for Eat/Drop/etc.",
            "G picks up items under you; drops land on the ground",
            "",
            "Tabs (top of panel): Stats Inv Quests Magic Prayer Bank Shop",
            "Magic: pick a spell, press I to cast at nearest",
            "Prayer: click prayers to toggle (drain points, shrine refills)",
            "Bank/Shop: click rows to withdraw/buy (stand adjacent!)",
            "",
            "The catacombs (dark NE corner) hold skeletons, hobgoblins",
            "and the Vulcan Guardian boss. Climb the ladder at (16,2).",
            "Talk to the wise man (blue) for work; ! for quests.",
            "ENTER opens chat - you share the 'main' channel with others.",
            "Death is safe: you respawn with your items.",
        ]
        yy = 74
        for ln in lines:
            fnt = self.big if ln.startswith("HOW") else self.small
            col = COLORS["gold"] if ln.startswith("HOW") else COLORS["text"]
            img = fnt.render(ln, True, col)
            self.screen.blit(img, (56, yy))
            yy += 17 if not ln.startswith("HOW") else 26

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

    WATCHLIST = ("Abyssal whip", "Rune pickaxe", "Iron ore", "Cowhide")

    def draw_ticker(self):
        if not self.ticker:
            return
        x = 116
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

    # ---------- input dispatch ----------

    def _menu_hit(self, pos):
        if not getattr(self, "_menu_hits", None):
            return False
        for r, cb in self._menu_hits:
            if r.collidepoint(pos):
                if cb:
                    try:
                        cb()
                    except Exception as exc:
                        self._flash(str(exc).splitlines()[0][:50])
                self.close_menu()
                return True
        self.close_menu()
        return True

    def _tab_click(self, pos):
        for r, cb in list(self._hot.values()):
            if r.collidepoint(pos):
                try:
                    cb()
                except Exception as exc:
                    self._flash(str(exc).splitlines()[0][:50])
                return True
        return False

    def run(self):
        while True:
            if self.frames_left is not None:
                if self.frames_left <= 0:
                    self.pg.quit()
                    return 0
                self.frames_left -= 1
            self._hot = {}
            self._rclick = {}
            self._menu_hits = getattr(self, "_menu_hits", [])
            for e in self.pg.event.get():
                if e.type == self.pg.QUIT:
                    self.pg.quit()
                    return 0
                if e.type == self.pg.KEYDOWN:
                    if self.chat_mode:
                        if e.key == self.pg.K_RETURN:
                            txt = self.chat_input.strip()
                            if txt:
                                try:
                                    self.sdk.chat(txt[:200])
                                    self.chat_lines.append(
                                        f"me: {txt}")
                                    del self.chat_lines[:-9]
                                except Exception as exc:
                                    self._flash(str(exc)[:50])
                            self.chat_input = ""
                            self.chat_mode = False
                        elif e.key == self.pg.K_ESCAPE:
                            self.chat_mode = False
                            self.chat_input = ""
                        elif e.key == self.pg.K_BACKSPACE:
                            self.chat_input = self.chat_input[:-1]
                        continue
                    k = e.key
                    if k == self.pg.K_ESCAPE:
                        if self.menu:
                            self.close_menu()
                        else:
                            self.pg.quit()
                            return 0
                    elif k == self.pg.K_RETURN:
                        self.chat_mode = True
                        self.chat_input = ""
                    elif k in (self.pg.K_h,):
                        self.show_help = not self.show_help
                    elif k == self.pg.K_g:
                        self.do_pickup()
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
                    elif k == self.pg.K_v:
                        self.do_trap()
                    elif k == self.pg.K_p:
                        self.act(self.sdk.set_run,
                                 not self.st["run"])
                elif e.type == self.pg.TEXTINPUT and self.chat_mode:
                    self.chat_input += e.text
                elif e.type == self.pg.MOUSEBUTTONDOWN:
                    mx, my = e.pos
                    if getattr(self, "_menu_hits", None):
                        if e.button in (1, 3):
                            if self._menu_hit((mx, my)):
                                continue
                    if getattr(self, "_dialogue_hits", None):
                        if e.button == 1:
                            hit = False
                            for r, i in self._dialogue_hits["hits"]:
                                if r.collidepoint((mx, my)):
                                    self.act(self.sdk.dialogue_choose, i)
                                    self.audio.play("steal")
                                    hit = True
                                    break
                            if hit:
                                continue
                        bx, by, bw, bh = self._dialogue_hits["box"]
                        if not (bx <= mx <= bx + bw and
                                by <= my <= by + bh):
                            continue
                    if e.button == 3:
                        if mx < GRID * TILE:
                            self.click_world(mx, my, 3)
                            continue
                        for r, cb in list(self._rclick.values()):
                            if r.collidepoint((mx, my)):
                                cb()
                                break
                        continue
                    if e.button == 1:
                        if self.minimap_click(mx, my):
                            continue
                        if mx < GRID * TILE:
                            if self.menu:
                                self.close_menu()
                            else:
                                self.click_world(mx, my, 1)
                            continue
                        self.st = self.sdk.state()
                        if self._tab_click((mx, my)):
                            continue
            self._sync_render_pos()
            self.poll_live()
            self.drain_chat()
            self.screen.fill(COLORS["panel"])
            self.draw_world()
            self.draw_panel()
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
