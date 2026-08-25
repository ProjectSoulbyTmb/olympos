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
KIND_RENDER = "fleet.render"    # riley work-stream order outcome
KIND_RENDER_DONE = "fleet.render-done"  # finished studio job announcement
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

# ---------- mind lane semantics ----------
MIND_MAX_PER_DRAIN = 25         # per-cycle ceiling; overflow stays queued
MIND_INTENT_TTL_S = 900         # intents older than this expire unrun
MIND_DEDUPE_LEDGER = os.path.join(HERE, "data", "mind_seen.json")
MIND_LEDGER_MAX = 500           # prune oldest entries beyond this
MIND_SUBSCRIPTIONS = os.path.join(
    WORKSPACE, "assistant", "data", "relay", "mind-subscriptions.json")

# ---------- cadence ----------

TICK_EVERY_S = 60.0             # constant update stream period
BEAT_EVERY_TICKS = 1            # heartbeat every cycle

# ---------- fleet subprocesses ----------

DAEDALUS_TIMEOUT_S = 180.0      # build commissioning ceiling
STATUS_TIMEOUT_S = 20.0         # daedalus status probe ceiling
REPORT_PATH = os.path.join("data", "health_report.json")  # doctor's verdict

# ---------- RILEY work stream ----------

# DAEDELUS blueprint whose build verdicts become RILEY render orders.
RILEY_BLUEPRINT = "nymph-hunter"

# The studio's loopback API (PERSEPHONE-guarded product; we only ever
# POST jobs to its public endpoint - never touch its files or state).
RILEY_URL = "http://127.0.0.1:43907"
RILEY_TIMEOUT_S = 10.0          # per-order delivery ceiling

# Spool for crash-tolerant delivery: orders survive a dark studio and
# retry each cycle until the studio answers.
RILEY_PENDING_DIR = os.path.join(WORKSPACE, "assistant", "data", "relay",
                                 "riley", "pending")
RILEY_SENT_DIR = os.path.join(WORKSPACE, "assistant", "data", "relay",
                              "riley", "sent")
RILEY_REJECTED_DIR = os.path.join(WORKSPACE, "assistant", "data", "relay",
                                  "riley", "rejected")

# Completion lane: highest studio job id (j<N>) already announced.
RILEY_CURSOR = os.path.join(WORKSPACE, "assistant", "data", "relay",
                            "riley", "jobs.cursor")

# Proof-card render spec (img.art is seeded & deterministic, so a
# retried duplicate order renders the identical asset - idempotent).
CARD_W = 512
CARD_H = 512
CARD_FMT = "png"
RED_VARIANTS = 2                # failed verdicts fan out a witness pair

# One style per nymph; a verdict renders her signature card.
# Styles ride RILEY's artgen engine (riley_artgen.py, landed in the
# v1.3.0 kernel + verify battery): procedural, seeded, deterministic -
# a retried order renders the identical card.
NYMPH_STYLES = {
    "daphne": "flowfield",       # code hunts - currents through the field
    "cyrene": "attractors",      # network hunts - strange attractors
    "arethusa": "moire",         # bus hunts - wave interference
    "britomartis": "voronoi",    # integrity hunts - cellular lattice
    "taygete": "strata",         # liveness hunts - ridge lines
    "maera": "truchet",          # git hygiene - tilework
}
NYMPH_DEFAULT_STYLE = "guilloche"
