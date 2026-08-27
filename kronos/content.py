"""KRONOS configuration - strain thresholds, cadence, managed fleet.

KRONOS is the resource governor: when the machine strains, the
deferrable patrols are held (their scheduled tasks stopped) until it
recovers, so testing and interactive work keep their headroom.

The ZEUS guardians are never listed here - protection stays on
through any hold. Their elevated run level enforces that physically:
a limited-level governor cannot stop a highest-level task even by
accident.
"""

# --- strain thresholds (percent of physical RAM in use) -------------
HOLD_PCT = 75          # at/above this for HOLD_SAMPLES -> hold patrols
RELEASE_PCT = 70       # below this for RELEASE_SAMPLES -> release them

# Samples landing in [RELEASE_PCT, HOLD_PCT) are deadband: neither
# strained nor calm; they reset both streaks and prevent flapping.

HOLD_SAMPLES = 3       # consecutive strained samples before a hold
RELEASE_SAMPLES = 6    # consecutive calm samples before a release

SAMPLE_S = 10.0        # governor nap between RAM samples

# --- nervous system ---------------------------------------------------
BUS_ENABLED = True          # liveness beats + incident broadcasts
HEARTBEAT_EVERY_S = 60.0    # nap between heartbeats while looping

# --- the deferrable fleet (explicit whitelist; never wildcards) -----
MANAGED_TASKS = (
    "Olympos HYPNOS Dreamworker",
    "Olympos GAIA Pulse",
    "Olympos RELAY Bridge",
    "Olympos POSEIDON Tide",
    "Olympos HEBE Scribe",
    "Olympos ARTEMIS Huntress",
    "Olympos ARES Exposure Sweep",
    "Eidovara VULCAN Auto",
)

# A task name carrying any of these markers is untouchable, whatever
# a future edit does to MANAGED_TASKS.
FORBIDDEN_MARKERS = ("zeus",)
