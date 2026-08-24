"""PTAH hooks - lifecycle command hooks (OpenHands/Claude-Code contract).

Hooks are shell commands registered in `.ptah/hooks.json`:

    {
      "PreToolUse":  [{"matcher": "terminal",
                       "command": "scripts/block_rmrf.sh", "timeout_s": 10}],
      "PostToolUse": [{"matcher": "*", "command": "log_tool.sh"}],
      "UserPromptSubmit": [...],
      "Stop": [...]
    }

Contract (matched against the Claude Code hook convention):
  - the event payload arrives as JSON on stdin; env carries
    PTAH_EVENT and PTAH_TOOL_NAME
  - exit 0   -> allow; stdout JSON may add "additionalContext"
  - exit 2   -> BLOCK; stderr becomes the feedback reason
  - other    -> non-blocking error, logged, operation proceeds

Events wired into Agent.run():
  UserPromptSubmit -> before the mission is recorded
  PreToolUse       -> after risk classification, before execution
  PostToolUse      -> after the observation is recorded
  Stop             -> when the agent is about to finish with an answer

Matchers: exact tool name or "*" (all tools). Empty matcher = match all.
"""

import json
import os
import subprocess


EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


class HookOutcome:
    def __init__(self, blocked=False, reason="", context=""):
        self.blocked = blocked
        self.reason = reason
        self.context = context

    def __repr__(self):
        return f"HookOutcome(blocked={self.blocked}, reason={self.reason!r})"


def load_hook_config(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("hooks") or {}


def _matches(matcher, tool_name):
    m = (matcher or "*").strip()
    return m == "*" or m == tool_name


def run_hooks(config, event, payload, cwd=None, timeout_s=10):
    """Run every matching hook for `event`; aggregate their verdicts."""
    outcome = HookOutcome()
    definitions = config.get(event) or []
    for entry in definitions:
        command = entry.get("command")
        if not command:
            continue
        if event in ("PreToolUse", "PostToolUse") and \
                not _matches(entry.get("matcher"), payload.get("tool")):
            continue
        env = dict(os.environ)
        env["PTAH_EVENT"] = event
        if payload.get("tool"):
            env["PTAH_TOOL_NAME"] = str(payload["tool"])
        stdin_blob = json.dumps(payload, ensure_ascii=False)
        try:
            proc = subprocess.run(
                command, shell=True, cwd=cwd or os.getcwd(),
                input=stdin_blob, capture_output=True, text=True,
                timeout=min(int(entry.get("timeout_s", timeout_s)), 120))
        except subprocess.TimeoutExpired:
            outcome.reason = outcome.reason or f"hook timed out: {command}"
            continue
        except OSError:
            continue                              # unspawnable: non-blocking
        code = proc.returncode
        stdout_json = {}
        try:
            parsed = json.loads(proc.stdout.strip() or "{}")
            if isinstance(parsed, dict):
                stdout_json = parsed
        except ValueError:
            pass
        if code == 0:
            ctx = stdout_json.get("additionalContext")
            if ctx:
                outcome.context = (outcome.context + "\n" + ctx).strip()
        elif code == 2:
            if not outcome.blocked:
                outcome.blocked = True
                outcome.blocking_reason = (
                    proc.stderr.strip()
                    or stdout_json.get("reason")
                    or f"{event} hook denied ({command})")
                outcome.reason = outcome.blocking_reason
                outcome.decision = stdout_json.get("decision", "deny")
        else:
            outcome.context = (outcome.context +
                               f"\n[hook error {code}: {command}]").strip()
    return outcome
