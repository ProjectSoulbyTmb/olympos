"""MIND CLI - command the director.

    python -m mind demo                    # dress rehearsal vs mock OBS
    python -m mind selfcheck               # module-level sanity sweep
    python -m mind serve                   # direct a real OBS Studio
    python -m mind serve --config mind.config.json --dry-run
    python -m mind status                  # poll a running dashboard
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from . import DEFAULT_DASHBOARD_PORT, __version__
from . import bus as bus_mod
from . import flows as flows_mod
from . import journal as journal_mod
from . import mockobs as mockobs_mod
from . import obsclient as obsclient_mod
from . import obswire as obswire_mod
from . import snapshot as snapshot_mod
from .director import (Director, run_demo,
                       selftest as director_selftest)
from .surfaces import control as control_surf
from .surfaces import dashboard as dashboard_surf
from .surfaces import events as events_surf
from .surfaces import http as http_surf
from .surfaces import overlays as overlay_surf

DEFAULT_CONFIG = "mind.config.json"

SUITES = (
    ("journal", journal_mod.selftest),
    ("bus", bus_mod.selftest),
    ("snapshot", snapshot_mod.selftest),
    ("flows", flows_mod.selftest),
    ("wire", obswire_mod.selftest),
    ("mockobs", mockobs_mod.selftest),
    ("client", obsclient_mod.selftest),
    ("http-surface", http_surf.selftest),
    ("control-surface", control_surf.selftest),
    ("events-surface", events_surf.selftest),
    ("overlay-surfaces", overlay_surf.selftest),
    ("dashboard-surface", dashboard_surf.selftest),
    ("director", director_selftest),
)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"{path}: top level must be an object")
    return config


def cmd_demo(_args) -> int:
    report = run_demo()
    for entry in report["steps"]:
        mark = "ok " if entry["ok"] else "FAIL"
        print(f"  [{mark}] {entry['step']}: {entry['detail']}")
    print(f"mind {__version__} rehearsal: "
          f"{'green' if report['ok'] else 'RED'}")
    return 0 if report.get("ok") else 1


def cmd_selfcheck(_args) -> int:
    failed = []
    for name, suite in SUITES:
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
    director = Director(load_config(args.config),
                        dry_run=args.dry_run,
                        journal_path=args.journal or None)
    director.start_server()
    mode = "DRY-RUN (no side effects)" if args.dry_run else "ARMED"
    print(f"mind {__version__} serving {director.url} [{mode}]")
    print(f"obs target {director.obs_host}:{director.obs_port}")
    if args.once:
        try:
            director.connect_once()
            print("connected")
            return 0
        finally:
            director.stop()
    try:
        director.supervise_forever()
    except KeyboardInterrupt:
        print("\nmind paused (keyboard interrupt)")
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
        description="MIND v2 - surfaces-first OBS companion")
    ap.add_argument("--version", action="version",
                    version=f"mind {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("demo", help="full rehearsal against mock OBS")
    sub.add_parser("selfcheck", help="run every module selftest")

    s = sub.add_parser("serve", help="direct a real OBS instance")
    s.add_argument("--config", default=DEFAULT_CONFIG)
    s.add_argument("--dry-run", action="store_true",
                   help="log actions without touching OBS")
    s.add_argument("--journal", default=None,
                   help="journal path override")
    s.add_argument("--once", action="store_true",
                   help="single connection attempt then exit")

    st = sub.add_parser("status", help="poll a running dashboard")
    st.add_argument(
        "--url",
        default=f"http://127.0.0.1:{DEFAULT_DASHBOARD_PORT}")
    st.add_argument("--timeout", type=float, default=5.0)

    ns = ap.parse_args(argv)
    table = {"demo": cmd_demo, "selfcheck": cmd_selfcheck,
             "serve": cmd_serve, "status": cmd_status}
    try:
        return table[ns.cmd](ns)
    except FileNotFoundError as exc:
        print(f"mind: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"mind: bad config json: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
