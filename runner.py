import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RL_DIR = os.path.join(HERE, "osrs-rl")
AGENT_DIR = os.path.join(HERE, "osrs-llm-agent")
sys.path.insert(0, AGENT_DIR)

PY = sys.executable
OLLAMA_TAGS = "http://localhost:11434/api/tags"

TASKS = {
    "wc_xp": "Maximize Woodcutting XP",
    "gold": "Maximize net coins",
    "total_xp": "Maximize total XP",
    "cook_xp": "Maximize Cooking XP (fish -> cook)",
    "uim_total_xp": "ULTIMATE IRONMAN total XP (bank locked)",
}


def ask(prompt, default=None):
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or default


def choose(title, options, default_index=0):
    print(f"\n{title}")
    for i, opt in enumerate(options, 1):
        marker = "*" if i - 1 == default_index else " "
        print(f"  {i}){marker} {opt}")
    raw = ask("Choose", str(default_index + 1))
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx], idx
    except ValueError:
        pass
    print("invalid choice, using default")
    return options[default_index], default_index


def hr():
    print("-" * 62)


def find_strategies():
    d = os.path.join(AGENT_DIR, "strategies")
    return sorted(glob.glob(os.path.join(d, "*.py")))


def find_checkpoints():
    out = []
    for p in sorted(glob.glob(os.path.join(RL_DIR, "runs", "*", "ckpt_*.pt"))
                    + glob.glob(os.path.join(RL_DIR, "runs", "*",
                                             "ckpt_latest.pt")),
                    key=os.path.getmtime, reverse=True):
        out.append(p)
    return out


def ollama_models():
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=3) as r:
            data = json.loads(r.read().decode())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def run_activity():
    task, _ = choose("Task:", list(TASKS.keys()))
    print(f"  -> {TASKS[task]}")
    target, ti = choose("Target:", ["local simulator", "RSPS server"], 0)
    strategies = find_strategies()
    if not strategies:
        print("no strategies found"); return
    strat, _ = choose("Strategy:", [os.path.basename(s) for s in strategies])
    strat_path = os.path.join(AGENT_DIR, "strategies", strat)
    ticks = int(ask("Tick budget", "3000"))

    if ti == 0:
        from bench import manual_mode
        print()
        manual_mode(task, strat_path, ticks,
                    uim=(task == "uim_total_xp"), save_every=max(100, ticks // 10))
    else:
        host = ask("Host", "127.0.0.1")
        port = int(ask("Port", "43590"))
        name = ask("Character name", "runner")
        from server.client import RemoteGameSDK
        from agent.runner import run_snippet
        game = RemoteGameSDK(host=host, port=port, name=name,
                             uim=(task == "uim_total_xp"), budget=ticks)
        with open(strat_path, encoding="utf-8") as f:
            code = f.read()
        t0 = time.time()
        ok, out, err = run_snippet(code, game, forgiving=True)
        state = game.state()
        xp = sum(v["xp"] for v in state["skills"].values())
        print(f"\n{'OK' if ok else 'ERR'} in {time.time() - t0:.1f}s | "
              f"tick {state['tick']} | total xp {xp:.0f} | "
              f"coins {state['coins']}")
        if err:
            print("note:", err)
        levels = {s: v["level"] for s, v in state["skills"].items()}
        print("levels:", levels)
        game.close()


def train_rl():
    name = ask("Run name", "v3")
    iters = int(ask("Iterations", "200"))
    episodes = int(ask("Episodes/iter", "40"))
    resume = ask("Resume latest checkpoint? y/N", "n").lower().startswith("y")
    cmd = [PY, "train.py", "--name", name, "--iters", str(iters),
           "--episodes", str(episodes)]
    if resume:
        cmd.append("--resume")
    print("\ntraining (Ctrl+C stops safely; resume anytime)\n")
    try:
        subprocess.run(cmd, cwd=RL_DIR)
    except KeyboardInterrupt:
        print(f"\nstopped - resume later with --resume --name {name}")


def evaluate_rl():
    ckpts = find_checkpoints()
    if not ckpts:
        print("no checkpoints found - train first"); return
    opts = [os.path.relpath(c, RL_DIR) for c in ckpts]
    _, i = choose("Checkpoint:", opts[:12])
    matches = int(ask("Matches per opponent", "150"))
    print()
    subprocess.run([PY, "evaluate.py", ckpts[i], "--matches", str(matches)],
                   cwd=RL_DIR)


def run_llm_agent():
    task, _ = choose("Task:", list(TASKS.keys()))
    models = ollama_models()
    if models:
        model, _ = choose("Model (detected):", models)
    else:
        print("(could not reach Ollama - entering manually)")
        model = ask("Model name", "llama3.2:3b")
    rounds = int(ask("Rounds", "5"))
    ticks = int(ask("Tick budget per round", "3000"))
    import bench
    ns = type("NS", (), {})()
    ns.task = task
    ns.ticks = ticks
    ns.rounds = rounds
    ns.seed = 1337
    ns.model = model
    ns.base_url = None
    ns.api_key = None
    ns.temperature = 0.25
    ns.code_file = None
    print()
    bench.llm_mode(ns)


def host_rsps():
    from server.rsps_server import GameServer
    port = int(ask("Port", "43590"))
    srv = GameServer(port=port)
    srv.start_async()
    print(f"\nRSPS engine live on port {port} - connect with:")
    print(f"  RemoteGameSDK(name='you', port={port})")
    print("Ctrl+C to stop\n")
    try:
        while True:
            time.sleep(5)
            print(f"  players online: {srv.player_count}")
    except KeyboardInterrupt:
        srv.stop()
        print("server stopped")


def refresh_knowledge():
    print("\npulling live GE prices + wiki articles...\n")
    subprocess.run([PY, os.path.join(AGENT_DIR, "tools",
                                     "update_knowledge.py")])


def launch_dashboard():
    print("opening dashboard (close its window to return)")
    subprocess.run([PY, os.path.join(HERE, "dashboard.py")])


def perf_benchmark():
    print()
    subprocess.run([PY, os.path.join(HERE, "perf_bench.py")])


def refresh_live():
    print("\nrefreshing live GE prices + update feed...\n")
    subprocess.run([PY, os.path.join(HERE, "osrs_updater.py")])
    subprocess.run([PY, os.path.join(HERE, "osrs_updater.py"), "--status"])


def supervised_server():
    print("\nArgus supervisor: health probes, auto-restart, content tracking.")
    port = int(ask("Port", "43590"))
    sys.path.insert(0, AGENT_DIR)
    from server.supervisor import MindSupervisor
    sup = MindSupervisor(port=port)
    try:
        sup.run_forever()
    except KeyboardInterrupt:
        sup.stop()
        print("supervisor stopped")




def play_client():
    """Launch the graphical playable client (auto-hosts a server)."""
    print("\\nlaunching the playable client (auto-hosts if needed)...\\n")
    subprocess.run([PY, os.path.join(HERE, "play_rsps.py")])


MENU = [
    ("Play now (graphical client)", play_client),
    ("Run an activity (sim or RSPS)", run_activity),
    ("Train combat agent (RL)", train_rl),
    ("Evaluate a trained combat agent", evaluate_rl),
    ("Run the LLM strategic agent", run_llm_agent),
    ("Host your RSPS server", host_rsps),
    ("Keep RSPS online 24/7 (Argus supervisor)", supervised_server),
    ("Refresh OSRS knowledge base", refresh_knowledge),
    ("Launch desktop dashboard", launch_dashboard),
    ("Performance benchmark", perf_benchmark),
]


def main():
    while True:
        print()
        hr()
        print("YGGDRASIL - EASY RUNNER")
        hr()
        for i, (label, _) in enumerate(MENU, 1):
            print(f"  {i}) {label}")
        print("  0) Quit")
        choice = ask("\nSelect", "0")
        try:
            n = int(choice)
        except ValueError:
            continue
        if n == 0:
            print("bye")
            break
        if 1 <= n <= len(MENU):
            print()
            MENU[n - 1][1]()
            input("\n[Enter to continue]")


if __name__ == "__main__":
    main()
