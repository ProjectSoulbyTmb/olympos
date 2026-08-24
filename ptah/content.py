"""PTAH content - shared constants, limits and prompt text.

Ptah is the Yggdrasil software-engineering agent kernel: an event-sourced
reasoning-action loop that plans with an LLM and acts through audited,
security-classified tools inside a scoped workspace.

House rules honored here:
  - standard library only, no third-party imports
  - local-first: the kernel runs offline; network is opt-in per provider
  - fail-safe: destructive actions are classified, gated and audited
  - ports: vulcan owns 43901, zeus owns 43902 -> ptah owns 43903
"""

import os

# ---------------------------------------------------------------- identity
REALM = "ptah"
VERSION = "1.1.0"
USER_AGENT = f"ptah/{VERSION} (Yggdrasil)"

# -------------------------------------------------------------- networking
SERVER_PORT = 43903            # vulcan hosts 43901; zeus takes 43902
SERVER_HOST = "127.0.0.1"      # loopback only unless explicitly widened
OWNED_PORTS = [SERVER_PORT]

# ------------------------------------------------------------------ limits
DEFAULT_MAX_ITERATIONS = 25    # reasoning-action turns per run()
STUCK_REPEAT_LIMIT = 3         # identical consecutive actions before stop
TERMINAL_TIMEOUT_S = 60        # per-command ceiling for the terminal tool
TERMINAL_OUTPUT_CAP = 64 * 1024        # bytes of combined output kept
TOOL_OUTPUT_CAP = 32 * 1024            # bytes embedded into observations
FILE_SIZE_CAP = 2 * 1024 * 1024        # file_editor read/create ceiling
HTTP_TIMEOUT_S = 120                   # LLM call ceiling
HTTP_MAX_RETRIES = 3                   # transient-failure retries
HTTP_BACKOFF_BASE_S = 0.5              # exponential backoff seed
CONDENSER_TOKEN_BUDGET = 24_000        # ~96 KB of prompt history
CHARS_PER_TOKEN = 4                    # heuristic used by the condenser

# ------------------------------------------------------------------ layout
def data_dir():
    """Runtime state root (gitignored): ptah/data."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def conversations_dir():
    return os.path.join(data_dir(), "conversations")


BUILTIN_SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "builtin_skills")

# ------------------------------------------------------------ security
DEFAULT_POLICY = "confirm-risky"

# Hard-deny patterns: never executable, confirmation cannot override.
DENY_RULES = [
    (r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+/(\s|$)", "recursive force delete at filesystem root"),
    (r"mkfs(\.\w+)?\b", "raw filesystem format"),
    (r"\bdd\s+if=.*of=/dev/(sd|hd|nvme)", "raw disk overwrite"),
    (r":\(\)\s*\{\s*:\|\:&\s*\}\s*;", "fork bomb"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "host power control"),
    (r"\breg\s+(delete|add)\s+HKLM\\", "machine-hive registry mutation"),
    (r"\bformat\s+[a-zA-Z]:", "drive format"),
    (r"\bRemove-Item\s+(-Recurse\s+)?-Force\s+[\"']?[A-Za-z]:\\\s*$",
     "powershell drive-root deletion"),
]

# Destructive patterns: require explicit confirmation under any policy.
DESTRUCTIVE_RULES = [
    (r"\brm\s+-[a-zA-Z]*[rd]", "recursive/forced removal"),
    (r"\bdel\s+/[sq]", "windows recursive delete"),
    (r"\brmdir\s+/s", "windows tree delete"),
    (r"\bgit\s+push\s+(--force|-f)\b", "history rewrite on remote"),
    (r"\bgit\s+reset\s+--hard\b", "unrecoverable worktree reset"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "untracked-file purge"),
    (r"\bdrop\s+(table|database)\b", "destructive SQL"),
    (r"\btruncate\s+table\b", "destructive SQL"),
    (r">\s*/dev/sd[a-z]", "raw device write"),
    (r"\bchmod\s+-R\s+777\b", "permission nuke"),
]

# Elevated patterns: allowed, logged, surfaced in audits.
ELEVATED_RULES = [
    (r"\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod)\b", "network fetch"),
    (r"\bpip3?\s+install\b", "package install"),
    (r"\bnpm\s+(install|i)\b", "package install"),
    (r"\bgit\s+(clone|push)\b", "remote git transfer"),
    (r"\b(chmod|chown|icacls)\b", "permission change"),
    (r"\bschtasks\s+/create\b", "scheduled-task registration"),
]

# ------------------------------------------------------------ system prompt
PROTOCOL_INSTRUCTIONS = """\
You operate inside PTAH, a software-engineering agent kernel. You act by \
replying with EXACTLY ONE JSON object and nothing else - no prose around it:

  {"action": {"tool": "<tool name>", "args": {<tool arguments>}}}

or, when the user's task is fully complete:

  {"answer": "<your final response to the user>"}

Rules of engagement:
- One action per turn. You will see its observation before deciding again.
- Never invent tools; use only the tools listed below.
- File paths are relative to the workspace root; escaping it is blocked.
- If a plan helps, keep it in the task tracker so progress survives.
"""

IDENTITY_LINE = (
    "You are PTAH, a careful software-engineering agent: you build by "
    "measured steps, verify your work, and refuse unsafe instructions.")
