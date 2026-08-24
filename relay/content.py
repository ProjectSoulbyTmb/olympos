"""RELAY tuning table - the bridge obeys nothing but this file."""

import os

VERSION = 1

ORGAN = "relay"

# ---------- transport ----------

# Outbound telemetry topic (buskit catalogue: buskit/envelope.py TOPICS).
TOPIC = "updates"
KIND_TICK = "fleet.tick"        # heartbeat + gate/lane summary each cycle
KIND_BUILD = "fleet.build"      # daedalus outcome (forwarded or commissioned)
KIND_REPAIR = "fleet.repair"    # remediation sweep outcome
MAILBOX = "venus"               # stable point-to-point lane for Venus
MIND_MAILBOX = "mind"           # outbound mirror for the mind layer

# Inbound intent lane: Venus is the only writer, relay the only reader.
HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)
INTENT_DIR = os.path.join(WORKSPACE, "assistant", "data", "relay",
                          "to-fleet")
INTENT_DONE = os.path.join(INTENT_DIR, "done")
INTENT_FAILED = os.path.join(INTENT_DIR, "failed")

# MIND intent lane: the consciousness layer writes here, relay drains.
MIND_INTENT_DIR = os.path.join(WORKSPACE, "assistant", "data", "relay",
                               "from-mind")
MIND_DONE = os.path.join(MIND_INTENT_DIR, "done")
MIND_FAILED = os.path.join(MIND_INTENT_DIR, "failed")

# ---------- cadence ----------

TICK_EVERY_S = 60.0             # constant update stream period
BEAT_EVERY_TICKS = 1            # heartbeat every cycle

# ---------- fleet subprocesses ----------

DAEDALUS_TIMEOUT_S = 180.0      # build commissioning ceiling
STATUS_TIMEOUT_S = 20.0         # daedalus status probe ceiling
REPORT_PATH = os.path.join("data", "health_report.json")  # doctor's verdict
