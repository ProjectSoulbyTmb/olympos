"""MIND CLI - command the director.

    python -m mind demo                    # dress rehearsal vs mock OBS
    python -m mind selfcheck               # module-level sanity sweep
    python -m mind serve                   # direct a real OBS Studio
    python -m mind serve --config mind.json --dry-run
    python -m mind status                  # poll a running dashboard
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from . import DEFAULT_DASHBOARD_PORT, __version__
from . import auth as auth_mod
from . import bus as bus_mod
from . import journal as journal_mod
from . import protocol as protocol_mod
from . import rules as rules_mod
from . import state as state_mod
from . import wire as wire_mod
from .director import Director, run_demo

DEFAULT_CONFIG = "mind.config.json"


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"{path}: top level must be an object")
    return config


def cmd_demo(args) -> int:
    report = run_demo()
    print(json.dumps(report, indent=1))
    if args.keep:
        print("note: --keep is a no-op; rehearsals always clean up")
    return 0 if report.get("ok") else 1


def cmd_selfcheck(_args) -> int:
    suites = (
        ("wire", wire_mod.selftest),
        ("auth", auth_mod.selftest),
        ("protocol", protocol_mod.selftest),
        ("state", state_mod.selftest),
        ("rules", rules_mod.selftest),
        ("journal", journal_mod.selftest),
        ("bus", bus_mod.selftest),
    )
    failed = []
    for name, suite in suites:
        try:
            code = suite()
        except Exception as exc:  # a crashing suite is a failing suite
            print(f"FAIL {name}: crashed: {exc}")
            code = 1
        if code != 0:
            failed.append(name)
    print(f"mind {__version__} selfcheck: "
          f"{'green' if not failed else 'RED ' + ','.join(failed)}")
    return 0 if not failed else 1


def cmd_serve(args) -> int:
    config = load_config(args.config)
    director = Director(config, dry_run=args.dry_run,
                        journal_path=args.journal or None)
    director.start_server()
    mode = "DRY-RUN (no side effects)" if args.dry_run else "ARMED"
    print(f"mind {__version__} serving {director.server.url} [{mode}]")
    print(f"obs target {director.obs_host}:{director.obs_port}")
    if args.once:
        # one supervised connection attempt, then exit (CI smoke)
        try:
            director.connect_once()
            print("connected")
            return 0
        except Exception as exc:
            print(f"connect failed: {exc}")
            return 1
    try:
        director.supervise_forever()
    except KeyboardInterrupt:
        print("mind paused (keyboard interrupt)")
    finally:
        director.stop()
    return 0


def cmd_status(args) -> int:
    url = f"{args.url.rstrip('/')}/api/status"
    with urllib.request.urlopen(url, timeout=args.timeout) as resp:
        snapshot = json.loads(resp.read().decode())
    print(json.dumps(snapshot, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="mind",
        description="MIND - modular intelligent network director "
                    "for OBS-driven productions")
    ap.add_argument("--version", action="version",
                    version=f"mind {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="full rehearsal against mock OBS")
    d.add_argument("--keep", action="store_true")

    sub.add_parser("selfcheck", help="run every module selftest")

    s = sub.add_parser("serve", help="direct a real OBS instance")
    s.add_argument("--config", default=DEFAULT_CONFIG)
    s.add_argument("--dry-run", action="store_true",
                   help="log flows without touching OBS")
    s.add_argument("--journal", default=None,
                   help="journal path override (default: temp)")
    s.add_argument("--once", action="store_true",
                   help="single connection attempt then exit")

    st = sub.add_parser("status", help="poll a running dashboard")
    st.add_argument("--url",
                    default=f"http://127.0.0.1:{DEFAULT_DASHBOARD_PORT}")
    st.add_argument("--timeout", type=float, default=5.0)

    ns = ap.parse_args(argv)
    table = {"demo": cmd_demo, "selfcheck": cmd_selfcheck,
             "serve": cmd_serve, "status": cmd_status}
    return table[ns.cmd](ns)


if __name__ == "__main__":
    sys.exit(main())
