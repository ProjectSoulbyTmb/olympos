"""BUSKIT: message-contract toolkit for Olympos organ communication.

Implements the INTEGRATION.md section 4.1 letter envelope and the
section 6 topic catalogue as data, plus a ledger linter (acceptance
criterion A8). Standard library only; purely additive so it merges
cleanly alongside ratatosk/bus.py on origin/main.
"""

from .envelope import (
    KINDS,
    PROFILES,
    TOPICS,
    VERSION,
    dump,
    iter_lint,
    loads,
    make,
    stamp_seq,
    validate,
)

__all__ = [
    "KINDS",
    "PROFILES",
    "TOPICS",
    "VERSION",
    "dump",
    "iter_lint",
    "loads",
    "make",
    "stamp_seq",
    "validate",
]
