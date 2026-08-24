"""PTAH condenser - keep the conversation inside a token budget.

Long agent runs grow without bound; the condenser keeps the dialogue
useful and bounded:

  - head: the first user message is always preserved (the mission)
  - tail: the most recent turns are preserved verbatim
  - middle: dropped and replaced by one CondensationEvent summary

Pure, deterministic, heuristic (~4 chars per token). No LLM call is
spent on summarization - the event log itself remains complete.
"""

from ptah import content

DIALOGUE_TYPES = ("user_message", "agent_message", "agent_thought",
                  "action", "observation", "denied_action",
                  "confirmation_required")


def estimate_tokens(text):
    return max(1, len(text or "") // content.CHARS_PER_TOKEN)


def _event_text(event):
    d = event.to_dict()
    if d["type"] == "action":
        return f"action {d.get('tool')}: {d.get('args')}"
    if d["type"] == "observation":
        body = d.get("output") or d.get("error") or ""
        return f"observation {d.get('tool')}: {body}"
    if d["type"] == "agent_thought":
        return f"assistant: {d.get('text', '')}"
    if d["type"] == "user_message":
        return f"user: {d.get('text', '')}"
    return str(d)


def condense(events, budget_tokens=None):
    """Split dialogue events into (kept, dropped) under the budget.

    The returned `kept` list always starts with the first user message
    (when present) and ends with the newest events. A CondensationEvent
    is NOT inserted here - the caller decides how to mark the cut so
    the raw log stays pure.
    """
    budget = budget_tokens or content.CONDENSER_TOKEN_BUDGET
    dialogue = [e for e in events if e.TYPE in DIALOGUE_TYPES]

    if not dialogue:
        return list(events), []

    # walk backwards collecting the tail that fits
    kept_rev = []
    spent = 0
    for event in reversed(dialogue):
        cost = estimate_tokens(_event_text(event))
        if spent + cost > budget and kept_rev:
            break
        kept_rev.append(event)
        spent += cost

    kept = list(reversed(kept_rev))

    # guarantee the mission statement survives even when it alone busts
    # the budget on absurdly small budgets (tests use tiny ones)
    first_user = next((e for e in dialogue
                       if e.TYPE == "user_message"), None)
    if first_user is not None and first_user not in kept:
        kept = [first_user] + kept

    dropped = [e for e in dialogue if e not in kept]
    return kept, dropped


def summarize_dropped(dropped):
    """Deterministic plain-language summary of a dropped span."""
    if not dropped:
        return ""
    tools = {}
    users = 0
    for e in dropped:
        if e.TYPE == "action":
            tools[e.tool] = tools.get(e.tool, 0) + 1
        elif e.TYPE == "user_message":
            users += 1
    bits = []
    if users:
        bits.append(f"{users} earlier user message(s)")
    for tool, n in sorted(tools.items()):
        bits.append(f"{n} {tool} action(s)")
    return ("[Earlier context condensed: " + ", ".join(bits)
            + ". Full history is in the event log.]")
