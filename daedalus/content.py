"""DAEDALUS tuning table - the builder obeys nothing but this file."""

import os

VERSION = 1

# ---------- identity / network ----------

ORGAN = "daedalus"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 43905            # after atlas's 43904
MAX_SESSIONS = 8
MAX_LINE_BYTES = 1 << 20

# ---------- paths ----------

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)
DATA_DIR = os.path.join(HERE, "data")
AUDIT_PATH = os.path.join(DATA_DIR, "audit.jsonl")
ARTIFACTS_DIR = os.path.join(DATA_DIR, "artifacts")   # sealed copies
PLANS_DIR = os.path.join(DATA_DIR, "plans")           # planning station

# ---------- build policy ----------

# Lane count: 8 by default (2x the founding fleet); DAEDALUS_LANES
# overrides per machine. Every lane is one ATLAS guest - the pool can
# never exceed atlas.content.MAX_GUESTS (resize fails loud past it).
try:
    MAX_CONCURRENT_BUILDS = max(1, int(os.environ.get("DAEDALUS_LANES") or 8))
except ValueError:                 # garbage in the env never stops boot
    MAX_CONCURRENT_BUILDS = 8
BUILD_ATTEMPTS = 3             # verify-fix-retry ceiling per build
GATE_TIMEOUT_S = 60.0          # per verify-gate run inside the guest
EXEC_TIMEOUT_S = 120.0         # absolute per-command ceiling
REPAIR_REGATES_MAX = 3         # culprit-isolation re-gate ceiling

# ---------- repair telemetry ----------

REPAIR_STATS_PATH = os.path.join(DATA_DIR, "repair_stats.json")

# ---------- audit ----------

AUDIT_MAX_BYTES = 2_000_000
EVENTS_MAX = 500

SUBSYSTEM_FAIL_LIMIT = 3
SUBSYSTEM_REVIVE_TICKS = 6

# ---------- fleet fluidity ----------

LANE_COOLDOWN_AFTER_FAILS = 3   # consecutive failures -> lane pauses
LANE_COOLDOWN_S = 45.0          # pause before the lane rejoins the pool
PUMP_IDLE_WAIT_S = 0.25         # pump nap between quiet cycles
