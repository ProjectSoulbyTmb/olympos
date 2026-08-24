"""Lint a JSONL incident ledger against the BUSKIT envelope contract.

Acceptance criterion A8 (INTEGRATION.md): the sentinel ledger schema
matches the section 4.1 envelope.

Usage:
    python -m buskit.lint data/sentinel/incidents.jsonl
    python -m buskit.lint --quiet <ledger>   # exit code only

Exit codes: 0 clean, 1 violations found, 2 file unreadable.
"""

import sys

from .envelope import iter_lint


def main(argv):
    args = [a for a in argv if a != "--quiet"]
    quiet = "--quiet" in argv
    if not args:
        print("usage: python -m buskit.lint [--quiet] <ledger.jsonl>")
        return 2
    path = args[0]
    bad = 0
    try:
        for no, problems in iter_lint(path):
            bad += 1
            if not quiet:
                for prob in problems:
                    print(f"FAIL  line {no}: {prob}")
    except OSError as exc:
        print(f"ERROR cannot read {path}: {exc}")
        return 2
    if not quiet:
        verdict = "CLEAN" if bad == 0 else f"{bad} bad line(s)"
        print(f"lint  {path}: {verdict}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
