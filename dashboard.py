import argparse
import csv
import json
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = (Path(sys.executable).parent if getattr(sys, "frozen", False)
        else Path(__file__).parent)
RL_RUNS = ROOT / "osrs-rl" / "runs"
AGENT_RUNS = ROOT / "osrs-llm-agent" / "runs"
AGENT_DIR = ROOT / "osrs-llm-agent"
DIGEST = ROOT / "osrs-llm-agent" / "knowledge" / "digest.md"

sys.path.insert(0, str(AGENT_DIR))

TASKS = ["wc_xp", "gold", "total_xp", "cook_xp", "uim_total_xp"]

BG = "#14171c"
FG = "#d8dee9"
ACCENT = "#88c0d0"
DIM = "#6b7280"


def latest_csv():
    if not RL_RUNS.exists():
        return None
    files = sorted(RL_RUNS.glob("*/log.csv"), key=os.path.getmtime)
    return files[-1] if files else None


def read_log(path):
    rows = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    except OSError:
        pass
    return rows


def draw_series(canvas, xs, ys, color, pad=8, label=""):
    if len(xs) < 2 or max(ys) == min(ys) == 0:
        return
    w = canvas.winfo_width() or 400
    h = canvas.winfo_height() or 120
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    span_x = (x1 - x0) or 1
    span_y = (y1 - y0) or 1
    pts = []
    for x, y in zip(xs, ys):
        px = pad + (x - x0) / span_x * (w - 2 * pad)
        py = h - pad - (y - y0) / span_y * (h - 2 * pad)
        pts.extend((px, py))
    canvas.create_line(*pts, fill=color, width=2)
    canvas.create_text(pad, pad, anchor="nw", text=label,
                       fill=DIM, font=("Consolas", 8))


NODE_COLORS = {
    "tree": "#4c9a4c", "rock": "#8a8f98", "spot": "#5b9bd5",
    "range": "#d08770", "bank": "#ebcb8b", "shop": "#b48ead",
    "furnace": "#bf616a", "npc": "#e5c07b",
}


def draw_world_map(canvas, session):
    canvas.delete("all")
    tile = 14
    size = 16 * tile
    for gx in range(17):
        c = "#1b2027"
        canvas.create_line(gx * tile, 0, gx * tile, size, fill=c)
        canvas.create_line(0, gx * tile, size, gx * tile, fill=c)
    if not session:
        return
    for node in session.get("nodes", []):
        x, y = node.get("pos", (-1, -1))
        kind = node.get("kind")
        color = NODE_COLORS.get(kind, "#666666")
        depleted = "respawn" in str(node.get("status", "")) or \
            "depleted" in str(node.get("status", ""))
        cx, cy = x * tile + tile // 2, y * tile + tile // 2
        r = tile // 2 - 2
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                           outline=color, fill=("" if depleted else color))
        if depleted:
            canvas.create_text(cx, cy, text="x", fill="#bf616a",
                               font=("Consolas", 8))
    px, py = session.get("position", (-1, -1))
    cx, cy = px * tile + tile // 2, py * tile + tile // 2
    canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                       fill=ACCENT, outline=ACCENT)


class Dashboard(tk.Tk):
    def __init__(self, once=False):
        super().__init__()
        self.title("OsrsLab - local training & agent monitor")
        self.configure(bg=BG)
        self.geometry("900x700")

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(header, text="OSRS LAB", bg=BG, fg=ACCENT,
                 font=("Consolas", 16, "bold")).pack(side="left")
        tk.Label(header, text="local sim only - never connects to Jagex services",
                 bg=BG, fg=DIM, font=("Consolas", 8)).pack(side="right")

        controls = tk.Frame(self, bg=BG)
        controls.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(controls, text="Activity:", bg=BG, fg=FG,
                 font=("Consolas", 9)).pack(side="left")
        self.task_var = tk.StringVar(value=TASKS[0])
        ttk.Combobox(controls, textvariable=self.task_var, values=TASKS,
                     width=14, state="readonly").pack(side="left", padx=(4, 10))
        tk.Label(controls, text="Ticks:", bg=BG, fg=FG,
                 font=("Consolas", 9)).pack(side="left")
        self.ticks_var = tk.StringVar(value="3000")
        ttk.Entry(controls, textvariable=self.ticks_var, width=7).pack(
            side="left", padx=(4, 10))
        self.run_btn = tk.Button(controls, text="Run example activity",
                                 command=self.run_activity,
                                 bg="#2e3440", fg=FG, relief="flat")
        self.run_btn.pack(side="left")
        tk.Label(controls, text="   RSPS port:", bg=BG, fg=FG,
                 font=("Consolas", 9)).pack(side="left")
        self.port_var = tk.StringVar(value="43590")
        ttk.Entry(controls, textvariable=self.port_var, width=6).pack(
            side="left", padx=(4, 6))
        self.host_btn = tk.Button(controls, text="Host RSPS",
                                  command=self.host_server,
                                  bg="#2e3440", fg=FG, relief="flat")
        self.host_btn.pack(side="left")
        self.status = tk.Label(controls, text="", bg=BG, fg=ACCENT,
                               font=("Consolas", 8))
        self.status.pack(side="left", padx=10)
        self._server = None

        self.rl_title = tk.Label(self, bg=BG, fg=FG,
                                 font=("Consolas", 11, "bold"))
        self.rl_title.pack(anchor="w", padx=12)
        self.chart = tk.Canvas(self, height=140, bg="#0e1116",
                               highlightthickness=0)
        self.chart.pack(fill="x", padx=12, pady=4)
        self.rl_stats = tk.Label(self, bg=BG, fg=DIM, justify="left",
                                 font=("Consolas", 9))
        self.rl_stats.pack(anchor="w", padx=12)

        map_frame = tk.Frame(self, bg=BG)
        map_frame.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(map_frame, text="WORLD VIEW (sim)  ·  MIND kernel v1.0",
                 bg=BG, fg=FG, font=("Consolas", 11, "bold")).pack(anchor="w")
        self.map = tk.Canvas(map_frame, width=16 * 14, height=16 * 14,
                             bg="#0e1116", highlightthickness=0)
        self.map.pack(side="left")

        tk.Label(self, text="GAME SESSIONS / AGENT LOOPS", bg=BG, fg=FG,
                 font=("Consolas", 11, "bold")).pack(anchor="w", padx=12,
                                                     pady=(10, 2))
        self.sessions = tk.Text(self, height=18, bg="#0e1116", fg=FG,
                                relief="flat", font=("Consolas", 9))
        self.sessions.pack(fill="both", expand=True, padx=12, pady=4)

        self.knowledge = tk.Label(self, bg=BG, fg=DIM, font=("Consolas", 8))
        self.knowledge.pack(anchor="w", padx=12, pady=(2, 8))

        self.once = once
        self.refresh()

    def host_server(self):
        if self._server is not None:
            return
        try:
            port = int(self.port_var.get())
            from server.rsps_server import GameServer
            srv = GameServer(port=port)
            srv.start_async()
            self._server = srv
            self.host_btn.config(state="disabled",
                                  text=f"Hosting :{port}")
            self.status.config(text=f"RSPS engine live on port {port}")
        except Exception as e:
            self.status.config(text=f"host failed: {e}")

    def run_activity(self):
        def worker():
            try:
                self.run_btn.config(state="disabled")
                self.status.config(text="running...")
                os.chdir(AGENT_DIR)
                from bench import manual_mode
                task = self.task_var.get()
                ticks = int(self.ticks_var.get() or 3000)
                code_file = ("strategies\\uim_fisher.py"
                             if task == "uim_total_xp"
                             else "strategies\\example_bot.py")
                sys.stdout = open(os.devnull, "w")
                try:
                    manual_mode(task, code_file, ticks,
                                uim=(task == "uim_total_xp"))
                finally:
                    sys.stdout = sys.__stdout__
                self.status.config(text=f"{task} finished - see sessions below")
            except Exception as e:
                sys.stdout = sys.__stdout__
                self.status.config(text=f"failed: {e}")
            finally:
                os.chdir(ROOT)
                self.run_btn.config(state="normal")
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        self.chart.delete("all")
        path = latest_csv()
        if path:
            run_name = path.parent.name
            rows = read_log(path)
            iters = [float(r["iter"]) for r in rows]
            win = [float(r["win_rate"]) for r in rows]
            rew = [float(r["avg_reward"]) for r in rows]
            self.rl_title.config(text=f"RL TRAINING  ({run_name})")
            draw_series(self.chart, iters, win, ACCENT, label="win rate")
            draw_series(self.chart, iters,
                        [max(0.0, min(1.0, (r + 5) / 10)) for r in rew],
                        "#a3be8c", label="reward (scaled)")
            if rows:
                last = rows[-1]
                self.rl_stats.config(text=(
                    f"iter {last['iter']} | win {float(last['win_rate']):.2f} "
                    f"loss {float(last['loss_rate']):.2f} "
                    f"draw {float(last['draw_rate']):.2f} "
                    f"R {float(last['avg_reward']):+.2f} "
                    f"ent {float(last['entropy']):.3f}"))
        else:
            self.rl_title.config(text="RL TRAINING  (no runs found)")

        lines = []
        latest_session = None
        if AGENT_RUNS.exists():
            for d in sorted(AGENT_RUNS.iterdir()):
                sess = d / "session.json"
                loop = d / "loop_state.json"
                if sess.exists():
                    try:
                        s = json.loads(sess.read_text())
                        if latest_session is None or \
                                s.get("tick", 0) >= latest_session.get("tick", 0):
                            latest_session = s
                        lines.append(
                            f"[activity] {d.name}: tick {s.get('tick')} | "
                            f"xp {int(s.get('total_xp', 0) if 'total_xp' in s else sum(s.get('xp', {}).values()))}"
                            f" | coins {s.get('coins')} | pos {tuple(s.get('pos', ()))}"
                            f" | quests {s.get('quests', {})}")
                    except (json.JSONDecodeError, OSError):
                        pass
                if loop.exists():
                    try:
                        l = json.loads(loop.read_text())
                        best = l.get("best") or {}
                        hist = l.get("history", [])
                        lines.append(
                            f"[llm-loop] {d.name}: rounds {len(hist)} | "
                            f"best score {best.get('score', '-')} | "
                            f"levels {best.get('details', {}).get('levels', '-')}")
                    except (json.JSONDecodeError, OSError):
                        pass
        status_file = AGENT_RUNS / "server_status.json"
        if status_file.exists():
            try:
                st = json.loads(status_file.read_text())
                lines.append(
                    f"[supervisor] online={st.get('online')} port {st.get('port')} "
                    f"| players {st.get('players')} | uptime {st.get('uptime_seconds', 0)//60}m "
                    f"| restarts {st.get('restarts')} | health {st.get('health')}")
            except (json.JSONDecodeError, OSError):
                pass
        self.sessions.delete("1.0", "end")
        self.sessions.insert("1.0", "\n".join(lines) or
                             "(no sessions yet - start one with bench.py)")
        if self._server is not None:
            self.status.config(
                text=f"RSPS engine live on port {self._server.port} | "
                     f"{self._server.player_count} player(s) online")
        draw_world_map(self.map, latest_session)

        if DIGEST.exists():
            age_h = (time.time() - DIGEST.stat().st_mtime) / 3600
            self.knowledge.config(
                text=f"ground-truth knowledge: refreshed {age_h:.1f}h ago "
                     f"(run tools\\update_knowledge.py to refresh)")
        else:
            self.knowledge.config(text="ground-truth knowledge: missing")

        if not self.once:
            self.after(2000, self.refresh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="render one frame and exit (for testing)")
    args = ap.parse_args()
    app = Dashboard(once=args.once)
    if args.once:
        app.after(600, app.destroy)
    app.mainloop()


if __name__ == "__main__":
    main()
