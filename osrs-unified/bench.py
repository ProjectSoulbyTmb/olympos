import argparse
import json
import os
import sys
import time

if getattr(sys, "frozen", False):
    base = os.path.dirname(sys.executable)
    candidate = os.path.join(base, "osrs-llm-agent")
    ROOT = candidate if os.path.isdir(candidate) else base
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("OSRS_ROOT") or ROOT

from agent.llm import LLMClient
from agent.loop import KnowledgeBase, run_loop
from game.world import World

TASKS = {
    "wc_xp": "Maximize Woodcutting experience. Score = total WC xp gained.",
    "gold": "Maximize coins gained. Sell everything you gather at the shop; "
            "buying better tools can pay for itself. Score = net coins gained.",
    "total_xp": "Maximize TOTAL experience across all skills in any combination.",
    "cook_xp": "Maximize Cooking experience: fish shrimp, cook them at the range.",
    "uim_total_xp": "ULTIMATE IRONMAN mode: the bank is permanently locked. "
                    "Manage your 28 slots with drop strategies and tool upgrades. "
                    "Maximize TOTAL experience. Score = total xp.",
}


def manual_mode(task_name, code_path, tick_budget, uim=False,
                resume=None, save_every=0):
    import json
    from agent.runner import run_snippet
    from game.sdk import GameSDK

    world = World(seed=1337, tick_budget=tick_budget, uim=uim)
    if resume:
        try:
            with open(resume, "r", encoding="utf-8") as f:
                snap = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            bad = resume + ".corrupt-%d" % int(time.time())
            os.replace(resume, bad)
            print(f"AUTOFIX: session corrupt ({e}) - moved to {bad}, "
                  "starting fresh")
            snap = None
        if snap is not None:
            try:
                world.load_snapshot(snap)
            except Exception as e:
                bad = resume + ".incompatible-%d" % int(time.time())
                os.replace(resume, bad)
                print(f"AUTOFIX: snapshot incompatible ({e}) - moved to "
                      f"{bad}, starting fresh")
            else:
                print(f"resumed session at tick {world.tick} "
                      f"({world.ticks_left} ticks left)")
        print(f"resumed session at tick {world.tick} "
              f"({world.ticks_left} ticks left)")

    session_dir = os.path.join(ROOT, "runs", task_name)
    os.makedirs(session_dir, exist_ok=True)
    session_path = os.path.join(session_dir, "session.json")

    def autosave(tick):
        tmp = session_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(world.save(), f)
        os.replace(tmp, session_path)

    if save_every > 0:
        world.on_tick = lambda t: (autosave(t) if t % save_every == 0 else None)

    with open(code_path, "r", encoding="utf-8") as f:
        code = f.read()
    ok, out, err = run_snippet(code, GameSDK(world))
    print(out)
    if err:
        print("note:", err)
    result = world.score_task(task_name)
    print(json.dumps(result, indent=2))
    autosave(world.tick)
    print(f"session saved -> {session_path}")
    return 0


def llm_mode(args):
    task_desc = TASKS[args.task]
    kb = KnowledgeBase(os.path.join(ROOT, "wiki"))
    gt_path = os.path.join(ROOT, "knowledge", "digest.md")
    if os.path.exists(gt_path):
        with open(gt_path, "r", encoding="utf-8") as f:
            kb.docs["ground_truth"] = f.read()
        print("loaded OSRS ground-truth knowledge "
              f"(fetched {kb.docs['ground_truth'].splitlines()[2] if len(kb.docs['ground_truth'].splitlines()) > 2 else '?'})")
    else:
        print("note: no knowledge/digest.md yet - run tools/update_knowledge.py")

    briefing = None
    bus = None
    try:
        from mind.bus import EventBus
        from mind import moderator
        import time as _time
        bus = EventBus(ROOT)
        ages = {}
        for label, rel in (("digest", os.path.join("knowledge", "digest.md")),
                           ("prices", os.path.join("knowledge", "live",
                                                   "ge_prices.json"))):
            p = os.path.join(ROOT, rel)
            if os.path.exists(p):
                ages[label] = round((_time.time() - os.path.getmtime(p))
                                    / 3600, 1)
            else:
                ages[label] = None
        findings = moderator.check_world_integrity(ROOT)
        briefing = (f"world integrity findings: {len(findings)}; "
                    f"knowledge age(h): {ages}; "
                    f"claims/notes: stronghold chest is a one-time +500 "
                    f"coins opener - use it.")
        bus.publish("mind.briefing", {"task": args.task,
                                      "briefing": briefing,
                                      "knowledge_age_hours": ages})
    except Exception as e:
        print(f"note: relay offline ({e})")

    out_dir = os.path.join(ROOT, "runs")
    os.makedirs(out_dir, exist_ok=True)
    make_world = lambda budget: World(seed=args.seed, tick_budget=budget,
                                      uim=(args.task == "uim_total_xp"))
    llm = LLMClient(model=args.model, base_url=args.base_url,
                    api_key=args.api_key, temperature=args.temperature)
    result = run_loop(llm, kb, make_world, args.task, task_desc,
                      rounds=args.rounds, tick_budget=args.ticks,
                      state_path=os.path.join(out_dir, "loop_state.json"),
                      briefing=briefing)
    best_path = os.path.join(out_dir, f"{args.task}_best.json")
    with open(best_path, "w", encoding="utf-8") as f:
        json.dump(result["best"], f, indent=2)

    if bus is not None:
        try:
            ok_rounds = sum(1 for h in result["history"] if h.get("ok"))
            bus.publish(
                "thoth.result.run",
                {"task": args.task, "rounds": len(result["history"]),
                 "ok_rounds": ok_rounds, "aborted": result["aborted"],
                 "best_score": (result["best"] or {}).get("score"),
                 "last_error": result["history"][-1]["error"]
                 if result["history"] else None},
                source="thoth")
            marker = os.path.join(out_dir, "thoth_last_result.json")
            with open(marker, "w", encoding="utf-8") as f:
                json.dump({"task": args.task, **{k: result[k] for k in
                            ("aborted",)}, "best_score":
                           (result["best"] or {}).get("score")},
                          f)
        except Exception as e:
            print(f"note: relay publish failed ({e})")
    if result["best"]:
        print(f"\nbest score {result['best']['score']} "
              f"(saved to {best_path})")
    else:
        print("\nno successful round")
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="LLM strategic agent benchmark "
                                             "for the local skilling MMO sim")
    ap.add_argument("--task", choices=list(TASKS), default="wc_xp")
    ap.add_argument("--ticks", type=int, default=3000)
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--code-file", help="run a strategy file directly (no LLM)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--temperature", type=float, default=0.25)
    ap.add_argument("--resume", help="resume a saved session file (manual mode)")
    ap.add_argument("--save-every", type=int, default=0,
                    help="autosave session every N ticks (manual mode)")
    args = ap.parse_args()

    if args.code_file:
        sys.exit(manual_mode(args.task, args.code_file, args.ticks,
                             uim=(args.task == "uim_total_xp"),
                             resume=args.resume, save_every=args.save_every))
    sys.exit(llm_mode(args))


if __name__ == "__main__":
    main()
