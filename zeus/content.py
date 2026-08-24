"""ZEUS tuning table - every number the kernel obeys lives here.

ZEUS is the workspace protection kernel: it patrols processes, file
integrity and filesystem behaviour, escalates what it finds, and
enforces with a thunderbolt when policy says so. Nothing in the other
modules hardcodes limits; operators retune ZEUS by editing this file.
"""

import os

VERSION = 1

# ---------- identity / network ----------

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 43902            # vulcan hosts 43901; zeus takes 43902
MAX_SESSIONS = 8
MAX_LINE_BYTES = 1 << 20
PATROL_SECONDS_REAL = 5.0      # auto-patrol cadence for the hosted server

# ---------- paths ----------

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)          # Yggdrasil root
DATA_DIR = os.path.join(HERE, "data")
QUARANTINE_DIR = os.path.join(DATA_DIR, "quarantine")
AUDIT_PATH = os.path.join(DATA_DIR, "audit.jsonl")
BASELINE_PATH = os.path.join(DATA_DIR, "baseline.json")

AUDIT_MAX_BYTES = 2_000_000
EVENTS_MAX = 500
REPAIRS_MAX = 300

# Full integrity sweeps cost real IO - run them every Nth patrol tick
# once a baseline exists (at 5s cadence this is about once a minute).
INTEGRITY_EVERY_TICKS = 12

# Integrity roots, relative to WORKSPACE. Files over MAX_BASELINE_BYTES
# or under EXCLUDE_DIRS are never hashed.
PROTECTED_ROOTS = [
    "doctor.py",
    "sentinel.py",
    "requirements.txt",
    "zeus",
    "vulcan",
    "hades",
]
EXCLUDE_DIRS = {".git", "__pycache__", ".gradle", "build", "dist",
                "release", "node_modules", "data"}
EXCLUDE_SUFFIXES = (".zip", ".exe", ".dll", ".pyc", ".pyo", ".jar",
                    ".pt", ".pth", ".ckpt", ".log", ".lock")
MAX_BASELINE_BYTES = 8_000_000

# Churn watch: dirs sampled for mutation bursts each patrol tick,
# relative to WORKSPACE. Sampling is capped so a huge tree cannot
# stall the kernel.
CHURN_DIRS = [
    ".",
    os.path.join("zeus", "data"),
    os.path.join("vulcan"),
    os.path.join("data"),
]
CHURN_MAX_ENTRIES = 4000       # per hot dir per sample
CHURN_WINDOW_TICKS = 3         # burst = changes summed over this window
CHURN_BURST_THRESHOLD = 40     # changed entries within window => burst
CHURN_NEW_FILE_SHARE = 0.6     # ...and mostly-new files smells synthetic

# ---------- process supervision (sentinel) ----------

# Named watches resolve against the live process table on every tick.
# kind="image": process executable name; kind="cmdline": any cmd line
# substring match. on_death may be "alert" or "restart".
WATCH_MANIFEST = [
    {"name": "sentinel", "kind": "contains", "match": "sentinel.py",
     "on_death": "alert"},
    {"name": "dashboard", "kind": "image", "match": "python",
     "on_death": "alert"},
]

# Explicit pid watches are added at runtime via sdk.watch_pid().

CPU_SOFT_PCT = 85.0            # sustained soft limit
CPU_HARD_PCT = 97.0            # immediate hard limit
MEM_SOFT_MB = 2048             # working set soft limit
RUNAWAY_SAMPLES = 4            # soft-limit samples before escalation
ESCALATION_POLICY = {          # action once runaway confirmed
    "default": "alert",        # alert | bolt
}

# Ports that belong to the ecosystem; an unknown listener elsewhere is
# only informational, but a stranger ON these ports is suspicious.
OWNED_PORTS = [43901, SERVER_PORT]
PORT_SCAN_TOP_N = 200          # how many listening sockets to classify

# ---------- self protection (kernel circuit breakers) ----------

SUBSYSTEM_FAIL_LIMIT = 3       # consecutive failures trip the breaker
SUBSYSTEM_REVIVE_TICKS = 6     # patrols before auto-revive attempt

# ---------- bolt safety rails ----------

NEVER_KILL_PIDS = {0, 4}       # system idle / kernel
SYSTEM_PATH_PREFIXES = (       # refuse to bolt anything running from
    os.environ.get("SystemRoot", r"C:\Windows").lower() + os.sep,
)
