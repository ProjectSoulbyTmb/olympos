import os


class KnowledgeBase:
    def __init__(self, wiki_dir):
        self.docs = {}
        for fn in os.listdir(wiki_dir):
            if fn.endswith(".md"):
                path = os.path.join(wiki_dir, fn)
                with open(path, "r", encoding="utf-8") as f:
                    self.docs[fn[:-3]] = f.read()

    def relevant(self, query):
        q = query.lower()
        scores = {}
        for name, text in self.docs.items():
            score = 0
            for token in set(q.replace(",", " ").split()):
                if token in name.lower():
                    score += 5
                if token in text.lower():
                    score += 1
            scores[name] = score
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        picked = [n for n, s in ranked[:3] if s > 0]
        return [self.docs[n] for n in picked]

    def core(self):
        parts = []
        for key in ("overview", "sdk", "map", "skills", "economy"):
            if key in self.docs:
                parts.append(self.docs[key])
        if "ground_truth" in self.docs:
            gt = self.docs["ground_truth"]
            cut = gt.find("## Wiki article digests")
            if cut != -1:
                gt = gt[:cut]
            parts.append(gt)
        return "\n\n---\n\n".join(parts)


def state_summary(state):
    skills = ", ".join(f"{s} {v['level']}" for s, v in state["skills"].items())
    return (f"tick {state['tick']}/{state['ticks_left']} left | pos {state['position']} "
            f"| coins {state['coins']}\nskills: {skills}\n"
            f"inventory ({state['inventory_slots_used']}/28): {state['inventory']}\n"
            f"tools: {', '.join(state['tools'])}\nbank: "
            f"{state['bank_contents'] or '(empty)'}\nevents: {'; '.join(state['events'][-6:])}")


def build_system_prompt(task_desc):
    return (
        "You are an autonomous agent playing a simplified RuneScape-like "
        "skilling MMO. Each round you write ONE python strategy snippet that "
        "the server executes.\n"
        "Rules:\n"
        "- The snippet must define `def run(game):` and use only the "
        "documented SDK methods - inventing methods or place names raises "
        "errors.\n"
        "- No imports. No filesystem or network access.\n"
        "- Wrap risky actions in try/except Exception so one error does not "
        "kill your whole run.\n"
        "- The tick budget (BudgetExceeded) ends episodes cleanly mid-loop.\n\n"
        "Example of a valid snippet:\n"
        "```python\n"
        "def run(game):\n"
        "    game.set_run(True)\n"
        "    game.walk(\"tree_1\")\n"
        "    while game.ticks_left() > 40:\n"
        "        try:\n"
        "            game.chop()\n"
        "        except Exception:\n"
        "            game.walk(\"tree_2\")\n"
        "```\n"
    )


def mind_docs(kb):
    """Live registry-derived docs (always current) + hand-written strategy
    tips + trimmed ground-truth prices. Replaces the stale wiki core."""
    from game.knowledge import render_markdown
    parts = [render_markdown()]
    if "strategy_basics" in kb.docs:
        parts.append(kb.docs["strategy_basics"])
    if "ground_truth" in kb.docs:
        gt = kb.docs["ground_truth"]
        cut = gt.find("## Wiki article digests")
        parts.append(gt[:cut] if cut != -1 else gt)
    return "\n\n---\n\n".join(parts)


def build_user_prompt(state, sdk_docs, extra_docs, last_error, last_score,
                      core_docs, task_desc, briefing=None):
    sections = [f"TASK: {task_desc}"]
    if briefing:
        sections.append("## MIND briefing (live system status)\n" + briefing)
    if core_docs:
        sections.append("## Game reference docs\n" + core_docs)
    if extra_docs:
        sections.append("## Wiki excerpts\n" + "\n\n".join(extra_docs))
    sections.append(f"## Current state\n{state_summary(state)}")
    sections.append(f"## SDK reference (the ONLY methods that exist)\n{sdk_docs}")
    if last_score is not None:
        sections.append(f"## Previous attempt score\n{last_score}")
    if last_error:
        sections.append(f"## Previous attempt FAILED with:\n{last_error}\nFix it.")
    sections.append(
        "Write your improved strategy now. Output ONLY one ```python code block "
        "containing `def run(game):`."
    )
    return "\n\n".join(sections)


def run_loop(llm, kb, make_world, task_name, task_desc, rounds=8,
             tick_budget=3000, verbose=True, state_path=None,
             briefing=None):
    import json
    from agent.llm import extract_code
    from agent.runner import run_snippet
    from game.sdk import build_sdk_docs, GameSDK

    history, best = [], None
    last_error = None
    last_score = None
    if state_path and os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        history = saved.get("history", [])
        best = saved.get("best")
        last_error = saved.get("last_error")
        last_score = saved.get("last_score")
        if verbose:
            print(f"resumed loop state: {len(history)} previous rounds")

    def persist():
        if state_path:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump({"history": history, "best": best,
                           "last_error": last_error,
                           "last_score": last_score}, f)

    target_total = len(history) + rounds
    no_code_streak = 0
    llm_fail_streak = 0
    aborted = False
    while len(history) < target_total:
        rnd = len(history) + 1
        world = make_world(tick_budget)
        state = world.state()
        try:
            reply = llm.chat(
                build_system_prompt(task_desc),
                build_user_prompt(state, build_sdk_docs(),
                                  None,
                                  last_error, last_score,
                                  mind_docs(kb), task_desc,
                                  briefing=briefing))
            llm_fail_streak = 0
        except (RuntimeError, TimeoutError, OSError) as e:
            last_error = f"LLM call failed: {e}"
            if verbose:
                print(f"[round {rnd}] {last_error}")
            llm_fail_streak += 1
            persist()
            if llm_fail_streak >= 3:
                if verbose:
                    print("aborting: LLM unreachable after 3 consecutive "
                          "failures - progress saved")
                aborted = True
                break
            continue
        code = extract_code(reply)
        if code is None:
            last_error = "no python code block found in response"
            if verbose:
                print(f"[round {rnd}] {last_error}")
            no_code_streak += 1
            persist()
            if no_code_streak >= 3:
                history.append({"round": rnd, "ok": False, "error": last_error,
                                "output": "", "score": None, "details": None})
                no_code_streak = 0
                persist()
            continue
        no_code_streak = 0
        ok, out, err = run_snippet(code, GameSDK(world), forgiving=True)
        score = world.score_task(task_name)
        entry = {"round": rnd, "ok": ok, "error": err, "output": out,
                 "score": score["score"], "details": score}
        history.append(entry)
        if ok and (best is None or entry["score"] > best["score"]):
            best = entry
        last_error = err or None
        clean_err = err.replace("tick budget exhausted (clean stop)", "").strip() or None
        last_error = clean_err
        last_score = {k: score[k] for k in ("score", "total_xp", "coins_gained",
                                            "peak_xp_per_tick", "levels")}
        if verbose:
            status = "OK " if ok else "ERR"
            tail = err.strip().splitlines()[-1] if err and clean_err else ""
            print(f"[round {rnd}] {status} score={entry['score']} "
                  f"xp={score['total_xp']} coins+{score['coins_gained']} "
                  f"peak={score['peak_xp_per_tick']}/t{(' err=' + tail) if tail else ''}")
        persist()
        if aborted:
            break
    return {"best": best, "history": history, "aborted": aborted}
