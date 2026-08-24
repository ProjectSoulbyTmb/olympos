"""ATLAS tuning table - the hypervisor obeys nothing but this file.

ATLAS hosts isolated guest workspaces: each guest is a jailed
directory plus a hardened execution lane (argv-only, hard timeout,
tree-kill, capped output, scrubbed environment). Builders like PTAH
rent guests; the hypervisor guarantees they cannot touch anything
outside their own world.
"""

import os

VERSION = 1

# ---------- identity / network ----------

ORGAN = "atlas"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 43904            # after ptah's 43903
MAX_SESSIONS = 8
MAX_LINE_BYTES = 1 << 20

# ---------- paths ----------

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)
DATA_DIR = os.path.join(HERE, "data")
AUDIT_PATH = os.path.join(DATA_DIR, "audit.jsonl")
GUESTS_DIR = os.path.join(DATA_DIR, "guests")

# ---------- bounds ----------

MAX_GUESTS = 16                     # concurrent jailed workspaces
GUEST_TIMEOUT_S = 60.0              # default exec ceiling
MAX_GUEST_TIMEOUT_S = 600.0         # absolute exec ceiling
RUN_OUTPUT_MAX_BYTES = 200_000      # combined stdout+stderr cap per exec
MAX_GUEST_NAME_LEN = 32

# ---------- cadence ----------

REAP_EVERY_BEATS = 12               # server beats between reaper sweeps
AUDIT_MAX_BYTES = 2_000_000
EVENTS_MAX = 500

# ---------- self protection ----------

SUBSYSTEM_FAIL_LIMIT = 3
SUBSYSTEM_REVIVE_TICKS = 6

# Environment variables a guest process may inherit; everything else
# is stripped so guests cannot smell the host's secrets.
ENV_ALLOWLIST = ("SystemRoot", "SystemDrive", "COMSPEC", "PATHEXT",
                 "PATH", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS")
