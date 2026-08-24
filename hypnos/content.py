"""HYPNOS tuning table - every number the sleeper obeys lives here.

HYPNOS is the silent task-handling organ: it sleeps until task letters
arrive in its Ratatosk mailbox, executes them headless (no ports, no
windows, no console noise), replies to the sender and audits every
step. Operators retune HYPNOS by editing this file.
"""

import os

VERSION = 1

# ---------- identity ----------

ORGAN = "hypnos"
TOPIC = "hypnos"

# ---------- paths ----------

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)          # Olympos root
DATA_DIR = os.path.join(HERE, "data")
AUDIT_PATH = os.path.join(DATA_DIR, "audit.jsonl")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
QUEUE_DIR = os.path.join(DATA_DIR, "queue")     # claimed / unfinished work
DROPIN_DIR = os.path.join(DATA_DIR, "dropin")   # *.task.json land here
DROPIN_DONE = os.path.join(DROPIN_DIR, "done")
DROPIN_FAILED = os.path.join(DROPIN_DIR, "failed")
DROPIN_KEEP = 200                # archived drop-in results per side

# File-touching actions may only resolve inside these roots.
ALLOWED_ROOTS = [WORKSPACE]

# ---------- unfinished work ----------

RETRY_MAX_ATTEMPTS = 3           # default cap when a letter asks for retry
RETRY_BACKOFF_BASE_S = 20.0      # next_epoch = now + base * 2**(attempt-1)
RETRY_BACKOFF_MAX_S = 1800.0
QUEUE_KEEP_DONE = 0              # claims vanish on completion (audited)

# ---------- cadence ----------

POLL_SECONDS_REAL = 5.0        # daemon nap between ticks
TICK_LETTERS_MAX = 8           # task letters drained per tick
PURGE_EVERY_TICKS = 60         # seen-folder cap sweep cadence

# ---------- bounds ----------

MAX_ACTIONS_PER_TASK = 32
MAX_RUN_TIMEOUT_S = 600.0      # hard ceiling for any run action
DEFAULT_RUN_TIMEOUT_S = 120.0
MAX_SLEEP_S = 30.0             # per sleep-action cap
RUN_OUTPUT_MAX_BYTES = 200_000
SHELL_ALLOWED = False          # runs are argv lists, never shell strings

# ---------- audit ----------

AUDIT_MAX_BYTES = 2_000_000
AUDIT_ROTATIONS = 3
EVENTS_MAX = 500

# ---------- full autonomy (operator approval 2026-08-24) ----------

# A red build dispatches doctor automatically - once per cooldown
# window - and the next build cycle verifies the repair. Closed loop:
# detect, act, verify, with no human in the chain.
AUTO_REPAIR_ENABLED = True
AUTO_REPAIR_COOLDOWN_S = 1800.0   # max one doctor dispatch per window
AUTO_REPAIR_ARGV = ["python", "doctor.py", "--ci"]
AUTO_REPAIR_TIMEOUT_S = 600

# Recurring duties: due entries become ordinary claims (same claim /
# run / retry / resume machinery as everything else). Operators add
# rows here; the sleeper never forgets one that is pending.
SCHEDULES = [
    {"name": "daily-provenance-scan", "every_s": 86400,
     "label": "hades integrity scan",
     "actions": [{"do": "run",
                  "argv": ["python", "hades/cli.py", "scan"],
                  "timeout_s": 900}]},
]

# ---------- self protection ----------

SUBSYSTEM_FAIL_LIMIT = 3       # consecutive tick failures trip the breaker
SUBSYSTEM_REVIVE_TICKS = 6     # ticks before auto-revive attempt

# ---------- live-system feed (build engine) ----------

# After a tick - work or idle - HYPNOS proves the organism still
# builds: every organ's verify gate runs on cadence, outcomes publish
# to topic "hypnos" as kind="build"/"build-failed" and land in
# data/build.json for the rest of the system. This is what makes the
# workspace self-verifying without a human in the loop.
BUILD_ENABLED = True
BUILD_GATES = [
    {"name": "ratatosk", "argv": ["python", "ratatosk/verify_ratatosk.py"],
     "timeout_s": 120},
    {"name": "norn", "argv": ["python", "norn/verify_norn.py"],
     "timeout_s": 180},
    {"name": "vulcan", "argv": ["python", "vulcan/verify_vulcan.py"],
     "timeout_s": 300},
    {"name": "hades", "argv": ["python", "hades/verify_hades.py"],
     "timeout_s": 300},
    {"name": "zeus", "argv": ["python", "zeus/verify_zeus.py"],
     "timeout_s": 300},
    {"name": "hypnos", "argv": ["python", "hypnos/verify_hypnos.py"],
     "timeout_s": 420},
    {"name": "ptah", "argv": ["python", "ptah/verify_ptah.py"],
     "timeout_s": 600},
    {"name": "atlas", "argv": ["python", "atlas/verify_atlas.py"],
     "timeout_s": 300},
    {"name": "daedalus",
     "argv": ["python", "daedalus/verify_daedalus.py"],
     "timeout_s": 420},
    {"name": "safeguards",
     "argv": ["python", "safeguards/verify_safeguards.py"],
     "timeout_s": 300},
    {"name": "hermod",
     "argv": ["python", "hermod/verify_hermod.py"],
     "timeout_s": 180},
    {"name": "template",
     "argv": ["python", "templates/verify_template.py"],
     "timeout_s": 120},
    {"name": "poseidon",
     "argv": ["python", "poseidon/verify_poseidon.py"],
     "timeout_s": 300},
    {"name": "relay",
     "argv": ["python", "relay/verify_relay.py"],
     "timeout_s": 300},
    {"name": "hebe",
     "argv": ["python", "hebe/verify_hebe.py"],
     "timeout_s": 300},
    {"name": "knowledge",
     "argv": ["python", "knowledge/verify_knowledge.py"],
     "timeout_s": 300},
    {"name": "persephone",
     "argv": ["python", "persephone/verify_persephone.py"],
     "timeout_s": 300},
    {"name": "kinema",
     "argv": ["python", "verify_kinema.py"],
     "timeout_s": 600},
]
BUILD_MIN_INTERVAL_S = 900.0   # never more often than this
BUILD_ON_IDLE = True           # the organism proves itself even quiet
BUILD_MAX_WORKERS = 4          # gates verify concurrently, not in line
