"""ARTEMIS CLI - python -m artemis.

  python -m artemis                 # one hunt sweep (nymph-led)
  python -m artemis --watch 300     # continuous patrol every N seconds
  python -m artemis --list          # signatures + owning nymphs
  python -m artemis --nymphs        # the retinue roster
  python -m artemis --drill         # prove every nymph via DAEDELUS
  python -m artemis --json          # machine-readable single sweep

Exit codes: 0 clean (or repairs applied), 1 findings open,
2 kernel broken internally. --drill exits 1 when any nymph fails her
jail gate or the workshop is unavailable.
"""

import argparse
import json
import sys
import time

from artemis import VERSION
from artemis import hunt


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m artemis",
        description="ARTEMIS error-hunt kernel v" + VERSION)
    ap.add_argument("--watch", type=int, metavar="SECONDS",
                    help="keep hunting every N seconds")
    ap.add_argument("--list", action="store_true",
                    help="show signatures and their nymphs, exit")
    ap.add_argument("--nymphs", action="store_true",
                    help="show the retinue roster, exit")
    ap.add_argument("--drill", action="store_true",
                    help="prove every nymph through the DAEDELUS "
                         "workshop inside ATLAS jail guests")
    ap.add_argument("--lanes", type=int, default=2, metavar="N",
                    help="parallel jail lanes for --drill (default 2)")
    ap.add_argument("--json", action="store_true",
                    help="print the sweep summary as JSON")
    opts = ap.parse_args(argv)

    if opts.nymphs:
        from artemis import nymphs
        for n in nymphs.NYMPHS:
            print(f"{n.name:<12} {n.domain:<18} "
                  f"{', '.join(n.signatures)}")
        return 0

    if opts.drill:
        from artemis import nymphs
        summary = nymphs.drill(lanes=opts.lanes)
        print(json.dumps(summary))
        ok = summary["green"] == summary["total"] \
            and not summary["degraded"]
        return 0 if ok else 1

    if opts.list:
        for owner, name, mode in hunt.list_signatures():
            print(f"{owner:<12} {name:<24} {mode}")
        return 0

    if opts.json:
        summary = hunt.sweep()
        print(json.dumps(summary))
        return 0 if summary["escalations"] == 0 else 1

    while True:
        try:
            summary = hunt.sweep()
            code = 0 if summary["findings"] == 0 or \
                summary["repairs"] == summary["findings"] else 1
        except Exception as exc:     # noqa: BLE001 - kernel broken
            hunt.log(f"kernel error: {exc}")
            code = 2
        if not opts.watch:
            return code
        time.sleep(max(30, opts.watch))


if __name__ == "__main__":
    sys.exit(main())
