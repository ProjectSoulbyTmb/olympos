"""PTAH agent - the reasoning-action loop.

One run():

  1. record the mission (UserMessage)
  2. assemble the system prompt (identity + protocol + tools + skills)
  3. loop up to max_iterations:
       - render condensed history as chat messages
       - ask the brain for exactly one JSON object
       - classify the requested action through security
       - execute, or pause for human confirmation, or refuse
       - feed the observation back
  4. finish on {"answer": ...}, stuck detection, budget or error

Fail-safe properties:
  - DESTRUCTIVE actions always pause for explicit confirmation; a
    confirmed turn executes exactly one privileged action, then the
    gate re-arms for the next one.
  - DENIED patterns are never executed, confirmation cannot override.
  - Repeating an identical action STUCK_REPEAT_LIMIT times stops the run.
"""

import json

from ptah import condenser, content, events
from ptah.security import ConfirmationPolicy, RiskAnalyzer
from ptah.tools import ToolContext


class ProtocolError(ValueError):
    pass


def extract_json(text):
    """Return the first balanced JSON object embedded in `text`."""
    start = text.find("{")
    if start < 0:
        raise ProtocolError("no JSON object found")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start:i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError as exc:
                    raise ProtocolError(f"invalid JSON: {exc}") from None
    raise ProtocolError("unbalanced JSON object")


def parse_reply(text):
    """Classify a model reply -> ('answer', str) | ('action', tool, args)."""
    obj = extract_json(text)
    if not isinstance(obj, dict):
        raise ProtocolError("reply is not a JSON object")
    if "answer" in obj:
        answer = obj["answer"]
        if not isinstance(answer, str) or not answer.strip():
            raise ProtocolError("'answer' must be a non-empty string")
        return ("answer", answer)
    action = obj.get("action")
    if isinstance(action, dict) and isinstance(action.get("tool"), str):
        args = action.get("args") or {}
        if not isinstance(args, dict):
            raise ProtocolError("'args' must be an object")
        return ("action", action["tool"], args)
    raise ProtocolError(
        "reply must be {\"answer\": ...} or {\"action\": {...}}")


def _cap(text, limit=None):
    limit = limit or content.TOOL_OUTPUT_CAP
    if text is None:
        return ""
    return text if len(text) <= limit else \
        text[:limit] + f"\n...[+{len(text) - limit} chars]"


class RunResult:
    def __init__(self, status, reason, iterations):
        self.status = status
        self.reason = reason
        self.iterations = iterations

    def __repr__(self):
        return f"RunResult({self.status!r}, {self.reason!r}, " \
               f"{self.iterations})"


class Agent:
    def __init__(self, llm, registry, analyzer=None, policy=None,
                 skills=None, max_iterations=None, token_budget=None,
                 repo_root=None, memory_path=None):
        self.llm = llm
        self.registry = registry
        self.analyzer = analyzer or RiskAnalyzer()
        self.policy = policy or ConfirmationPolicy()
        self.skills = skills or []
        self.max_iterations = max_iterations or content.DEFAULT_MAX_ITERATIONS
        self.token_budget = token_budget or content.CONDENSER_TOKEN_BUDGET
        self.repo_root = repo_root

    # ------------------------------------------------------------- prompt
    def build_system_prompt(self, workspace_root, skill_block=""):
        parts = [
            content.IDENTITY_LINE,
            "",
            content.PROTOCOL_INSTRUCTIONS,
            "",
            "# Tools",
            self.registry.describe_all(),
            "",
            f"# Workspace\nRoot: {workspace_root}",
        ]
        if skill_block:
            parts += ["", skill_block]
        return "\n".join(parts)

    # ---------------------------------------------------------- history
    def _messages_from_history(self, all_events):
        kept, dropped = condenser.condense(all_events, self.token_budget)
        messages = []
        if dropped:
            messages.append({"role": "user",
                             "content": condenser.summarize_dropped(dropped)})
        for e in kept:
            t = e.TYPE
            if t == "user_message":
                messages.append({"role": "user", "content": e.text})
            elif t == "agent_message":
                messages.append({"role": "assistant",
                                 "content": json.dumps({"answer": e.text})})
            elif t == "agent_thought":
                messages.append({"role": "assistant",
                                 "content": _cap(e.text, 4000)})
            elif t == "action":
                messages.append({"role": "assistant", "content": json.dumps(
                    {"action": {"tool": e.tool, "args": e.args}})})
            elif t == "observation":
                body = e.output if e.output else ""
                if e.error:
                    body += f"\n[error] {e.error}"
                messages.append({"role": "user",
                                 "content": f"OBSERVATION({e.tool}):\n"
                                            f"{_cap(body)}"})
            elif t == "denied_action":
                messages.append({"role": "user",
                                 "content": f"REFUSED({e.tool}): "
                                            f"{e.reason}. Choose another "
                                            "approach."})
            elif t == "confirmation_required":
                messages.append({"role": "user",
                                 "content": f"PENDING CONFIRMATION "
                                            f"({e.tool}): {e.reason}"})
        return messages

    # -------------------------------------------------------------- exec
    def _execute(self, conversation, tool_name, args, ctx,
                 bypass_policy=False):
        verdict = self.analyzer.classify(tool_name, args)
        conversation.append(events.ActionEvent(
            tool=tool_name, args=args, risk=verdict.risk,
            risk_reason=verdict.reason))
        if not verdict.allowed:
            conversation.append(events.DeniedActionEvent(
                tool=tool_name, args=args, reason=verdict.reason))
            conversation.append(events.ObservationEvent(
                tool=tool_name, output="", exit_code=3,
                error=f"denied by security: {verdict.reason}"))
            return None
        if not bypass_policy and self.policy.apply(verdict):
            conversation.append(events.ConfirmationRequiredEvent(
                tool=tool_name, args=args, risk=verdict.risk,
                reason=verdict.reason))
            return "waiting"
        tool = self.registry.get(tool_name)
        try:
            obs = tool.run(args, ctx)
        except Exception as exc:                  # noqa: BLE001 - audited
            obs_text, err, code = "", f"{type(exc).__name__}: {exc}", 2
        else:
            obs_text, err = obs.output, obs.error
            code = obs.exit_code
        conversation.append(events.ObservationEvent(
            tool=tool_name, output=_cap(obs_text), error=_cap(err, 2000),
            exit_code=code))
        return None

    # --------------------------------------------------------------- run
    def run(self, conversation, user_text="", confirm=False, workspace=None):
        ctx = ToolContext.build(workspace, repo_root=self.repo_root,
                                memory_path=self._memory_path())
        conversation.set_status(conversation.RUNNING)

        if user_text:
            conversation.append(events.UserMessage(text=user_text))

        # ---- resume path: one confirmed privileged action, gate re-arms
        if conversation.pending_action:
            if not confirm:
                return RunResult(conversation.status, "awaiting_confirmation",
                                 0)
            tool_name, args = conversation.pending_action
            conversation.pending_action = None
            outcome = self._execute(conversation, tool_name, args, ctx,
                                    bypass_policy=True)
            if outcome == "waiting":              # still gated somehow
                return RunResult(conversation.status,
                                 "awaiting_confirmation", 0)
            user_text = ""                        # no fresh mission

        skill_block = condenser_skills_block(self.skills, user_text)
        system = self.build_system_prompt(workspace.root, skill_block)
        conversation.append(events.SystemPrompt(text=system))

        corrective = 0
        recent_signatures = []
        iterations = 0
        while iterations < self.max_iterations:
            iterations += 1
            messages = self._messages_from_history(conversation.events)
            try:
                reply = self.llm.complete(system, messages)
            except Exception as exc:              # LLMError and friends
                conversation.append(events.ErrorEvent(message=str(exc)))
                conversation.append(events.FinishedEvent(reason="error"))
                return RunResult(conversation.ERROR, "error", iterations)
            conversation.append(events.AgentThought(
                text=reply.text, usage=getattr(reply, "usage", {})))
            try:
                parsed = parse_reply(reply.text)
            except ProtocolError as exc:
                if corrective < 1:
                    corrective += 1
                    conversation.append(events.UserMessage(
                        text=f"[protocol] Your reply was invalid ({exc}). "
                             "Respond with EXACTLY ONE JSON object: "
                             '{"action":{"tool":...,"args":{...}}} or '
                             '{"answer":"..."}.'))
                    continue
                conversation.append(events.ErrorEvent(
                    message=f"protocol failure: {exc}"))
                conversation.append(events.FinishedEvent(reason="error"))
                return RunResult(conversation.ERROR, "protocol_error",
                                 iterations)

            if parsed[0] == "answer":
                conversation.append(events.AgentMessage(text=parsed[1]))
                conversation.append(events.FinishedEvent(reason="answered"))
                return RunResult(conversation.FINISHED, "answered",
                                 iterations)

            _, tool_name, args = parsed
            outcome = self._execute(conversation, tool_name, args, ctx)
            if outcome == "waiting":
                return RunResult(conversation.WAITING_CONFIRMATION,
                                 "awaiting_confirmation", iterations)

            # stuck detection runs after execution: the pattern must
            # actually repeat STUCK_REPEAT_LIMIT times before stopping
            signature = json.dumps([tool_name, args], sort_keys=True)
            recent_signatures.append(signature)
            recent_signatures = recent_signatures[-content.STUCK_REPEAT_LIMIT:]
            if len(recent_signatures) == content.STUCK_REPEAT_LIMIT and \
                    len(set(recent_signatures)) == 1:
                conversation.append(events.FinishedEvent(reason="stuck"))
                return RunResult(conversation.ERROR, "stuck", iterations)

        conversation.append(events.FinishedEvent(reason="max_iterations"))
        return RunResult(conversation.ERROR, "max_iterations", iterations)

    def _memory_path(self):
        # memory destination lives on the ToolContext; default handled there
        return None


def condenser_skills_block(skills, user_text):
    """Local import-free helper bridging skills -> prompt block."""
    from ptah import skills as skills_mod
    matched = skills_mod.select_skills(skills, user_text or "")
    return skills_mod.render_block(matched)
