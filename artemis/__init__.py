"""ARTEMIS - the huntress organ.

Signature-driven error hunting with bounded repair. Where sentinel
runs the verify gates (exhaustive, scheduled), ARTEMIS sweeps the
fleet's runtime state continuously for SPECIFIC known error
signatures and applies conservative fixes to artifacts we own.

Contracts honored (INTEGRATION.md):
- hunt ledger lines are buskit envelopes on the 'incidents' topic;
- repairs announce 'fleet.repair' letters on the 'updates' topic;
- liveness via ratatosk heartbeats - no private timers beyond the
  sentinel-family --watch loop / Scheduled Task cadence;
- bounded autonomy (L013/L017): repeat offenders escalate instead of
  looping forever; quarantine over destruction, always.

Usage:
  python -m artemis              # one hunt sweep
  python -m artemis --watch 300  # continuous hidden patrol
  python -m artemis --list       # show registered signatures

Verify: python artemis/verify_artemis.py
"""

VERSION = "1.0.0"
ORGAN = "artemis"
