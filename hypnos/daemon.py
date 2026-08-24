"""HYPNOS daemon - the silent loop. This is how the sleeper hosts.

    python -m hypnos.daemon          # nap forever, work on arrival
    python -m hypnos.daemon --once   # one full tick, then leave
    python -m hypnos.daemon --poll 30

Nothing is ever printed: progress lives in the audit trail, state.json
and the heartbeat; operators watch via `python -m hypnos status`.
"""

import argparse
import os
import sys
import time
import traceback

from hypnos import content
from hypnos.kernel import Kernel


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="hypnos.daemon", description="silent task organ")
    parser.add_argument("--once", action="store_true",
                        help="run a single tick and exit")
    parser.add_argument("--poll", type=float, default=None,
                        help="seconds between ticks")
    args = parser.parse_args(argv)

    poll = max(0.5, args.poll or content.POLL_SECONDS_REAL)
    kernel = Kernel()
    try:
        kernel.post.register(content.ORGAN,
                             role="silent executor",
                             version=content.VERSION)
    except OSError:
        pass
    kernel.audit("daemon-start", pid=os.getpid(),
                 once=bool(args.once), poll_s=poll)

    while True:
        try:
            kernel.tick()
        except Exception:                     # noqa: BLE001 - never wake loudly
            kernel.audit("tick-crash", trace=traceback.format_exc()[-1500:])
        if args.once:
            break
        try:
            time.sleep(poll)
        except KeyboardInterrupt:
            break

    kernel.post.beat(content.ORGAN, note="asleep")
    kernel.audit("daemon-stop", ticks=kernel.tick_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
