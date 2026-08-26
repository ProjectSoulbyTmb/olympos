"""ordersctl - a local waiting-orders queue with manual release.

Orders wait in <home>/pending/*.json until you release them by id
("whenever I say"). Released orders move to done/, refused ones to
cancelled/, and every transition lands in orders.log. Pure standard
library, zero dependencies on this repo's packages, so any session or
project can use it.

Queue home resolution (first wins):
    --home PATH
    MIND_ORDERS_HOME environment variable
    ./orders relative to the current directory

Usage:
    py ordersctl.py place ship-v2 --title "Ship MIND v2" \
        --note "commit + parent extraction" [--payload-file ctx.json]
    py ordersctl.py list [--all]
    py ordersctl.py show ship-v2
    py ordersctl.py release ship-v2     # the callback: fires on your word
    py ordersctl.py cancel ship-v2
    py ordersctl.py log [-n 20]
    py ordersctl.py selftest

An order file:
    {"id": "...", "title": "...", "note": "...", "payload": {...},
     "created": iso8601, "released": iso8601|null}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

VERSION = "1.0.0"
STATUSES = ("pending", "done", "cancelled")


class OrdersError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_home(explicit: str = None) -> str:
    home = explicit or os.environ.get("MIND_ORDERS_HOME") \
        or os.path.join(os.getcwd(), "orders")
    return os.path.abspath(home)


def status_dir(home: str, status: str) -> str:
    if status not in STATUSES:
        raise OrdersError(f"unknown status {status!r}")
    path = os.path.join(home, status)
    os.makedirs(path, exist_ok=True)
    return path


def order_path(home: str, order_id: str, status: str) -> str:
    _validate_id(order_id)
    return os.path.join(status_dir(home, status),
                        f"{order_id}.json")


def find_order(home: str, order_id: str):
    """Return (status, path) or (None, None)."""
    _validate_id(order_id)
    for status in STATUSES:
        path = os.path.join(home, status, f"{order_id}.json")
        if os.path.isfile(path):
            return status, path
    return None, None


def _validate_id(order_id: str):
    bad = (not order_id) or any(c in order_id for c in "/\\:*?\"<>| ") \
        or order_id in (".", "..") or order_id.strip() != order_id
    if bad:
        raise OrdersError(f"invalid order id: {order_id!r} "
                          "(no spaces, separators, or wildcards)")


def read_order(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            order = json.load(handle)
    except json.JSONDecodeError as exc:
        raise OrdersError(f"corrupt order file {path}: {exc}") from exc
    if not isinstance(order, dict) or "id" not in order:
        raise OrdersError(f"malformed order file {path}")
    return order


def write_order(home: str, status: str, order: dict):
    path = order_path(home, order["id"], status)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(order, handle, indent=1)
        handle.write("\n")
    os.replace(tmp, path)
    return path


def log_entry(home: str, action: str, order_id: str, **fields):
    entry = {"ts": now_iso(), "action": action, "id": order_id}
    entry.update(fields)
    with open(os.path.join(home, "orders.log"), "a",
              encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


# -- commands ----------------------------------------------------------------


def cmd_place(args) -> int:
    home = queue_home(args.home)
    status_dir(home, "pending")  # ensure layout exists
    existing, _ = find_order(home, args.id)
    if existing is not None:
        raise OrdersError(f"id already exists ({existing}): {args.id}")
    payload = {}
    if args.payload_file:
        with open(args.payload_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise OrdersError("payload file must hold a JSON object")
    order = {
        "id": args.id,
        "title": args.title,
        "note": args.note or "",
        "payload": payload,
        "created": now_iso(),
        "released": None,
    }
    write_order(home, "pending", order)
    log_entry(home, "placed", args.id, title=args.title)
    print(f"placed pending order: {args.id}")
    return 0


def cmd_list(args) -> int:
    home = queue_home(args.home)
    statuses = STATUSES if args.all else ("pending",)
    found = []
    for status in statuses:
        folder = os.path.join(home, status)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if name.endswith(".json"):
                order = read_order(os.path.join(folder, name))
                found.append((status, order))
    if not found:
        print("(queue empty)")
        return 0
    for status, order in found:
        marker = {"pending": "WAITING ", "done": "RELEASED",
                  "cancelled": "CANCELLED"}[status]
        title = order.get("title") or ""
        print(f"[{marker}] {order['id']}: {title}")
    print(f"-- {len(found)} order(s)")
    return 0


def cmd_show(args) -> int:
    home = queue_home(args.home)
    status, path = find_order(home, args.id)
    if path is None:
        raise OrdersError(f"no such order: {args.id}")
    print(f"status: {status}")
    print(json.dumps(read_order(path), indent=1))
    return 0


def _move(home: str, order_id: str, from_status: str, to_status: str,
          stamp_field: str) -> dict:
    src = order_path(home, order_id, from_status)
    if not os.path.isfile(src):
        raise OrdersError(f"no {from_status} order named: {order_id}")
    order = read_order(src)
    order[stamp_field] = now_iso()
    write_order(home, to_status, order)
    os.remove(src)
    return order


def cmd_release(args) -> int:
    home = queue_home(args.home)
    order = _move(home, args.id, "pending", "done", "released")
    log_entry(home, "released", args.id, title=order.get("title"))
    print(f"RELEASED: {order['id']}")
    if order.get("note"):
        print(f"note: {order['note']}")
    if order.get("payload"):
        print("payload:")
        print(json.dumps(order["payload"], indent=1))
    return 0


def cmd_cancel(args) -> int:
    home = queue_home(args.home)
    order = _move(home, args.id, "pending", "cancelled",
                  "cancelled_at")
    log_entry(home, "cancelled", args.id, title=order.get("title"))
    print(f"cancelled: {args.id}")
    return 0


def cmd_log(args) -> int:
    home = queue_home(args.home)
    path = os.path.join(home, "orders.log")
    if not os.path.isfile(path):
        print("(no log yet)")
        return 0
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    for line in lines[-args.n:]:
        entry = json.loads(line)
        print(f"{entry['ts']}  {entry['action']:9s} {entry['id']}")
    return 0


# -- selftest ------------------------------------------------------------


def selftest(home: str = None) -> int:
    import tempfile
    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    home = home or tempfile.mkdtemp(prefix="orders-selftest-")

    def place(oid):
        ns = argparse.Namespace(id=oid, title=f"t-{oid}",
                                note="n", payload_file=None, home=home)
        return cmd_place(ns)

    place("alpha")
    check("pending-file-exists",
          os.path.isfile(order_path(home, "alpha", "pending")))

    ns_place_dup = argparse.Namespace(
        id="alpha", title="dup", note=None, payload_file=None,
        home=home)
    try:
        cmd_place(ns_place_dup)
        check("duplicate-refused", False)
    except OrdersError:
        check("duplicate-refused", True)

    listing = _capture(lambda: cmd_list(argparse.Namespace(all=False,
                                                           home=home)))
    check("list-shows-pending", "WAITING" in listing and "alpha" in
          listing)

    show = _capture(lambda: cmd_show(argparse.Namespace(id="alpha",
                                                        home=home)))
    check("show-includes-created", '"created"' in show)

    try:
        _move(home, "ghost", "pending", "done", "released")
        check("release-missing-refused", False)
    except OrdersError:
        check("release-missing-refused", True)

    cmd_release(argparse.Namespace(id="alpha", home=home))
    released = read_order(order_path(home, "alpha", "done"))
    check("release-stamps-time", released["released"] is not None)
    check("moved-out-of-pending",
          not os.path.exists(order_path(home, "alpha", "pending"))
          and os.path.isfile(order_path(home, "alpha", "done")))

    place("beta")
    cmd_cancel(argparse.Namespace(id="beta", home=home))
    cancelled = read_order(order_path(home, "beta", "cancelled"))
    check("cancel-stamps-time",
          cancelled["cancelled_at"] is not None)

    with open(os.path.join(home, "orders.log"), "r",
              encoding="utf-8") as handle:
        kinds = [json.loads(l)["action"] for l in handle]
    check("log-audits-lifecycle",
          kinds == ["placed", "released", "placed", "cancelled"])

    for bad in ("../evil", "with space", "", "x/y"):
        try:
            _validate_id(bad)
            check(f"bad-id-rejected:{bad}", False)
        except OrdersError:
            check(f"bad-id-rejected:{bad}", True)

    ok = not failures
    print(f"orders selftest: {'green' if ok else 'RED ' + str(failures)}")
    return 0 if ok else 1


def _capture(fn) -> str:
    import io
    import contextlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        fn()
    return buffer.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ordersctl",
                                 description="waiting-orders queue "
                                             "(manual release)")
    ap.add_argument("--version", action="version",
                    version=f"ordersctl {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--home", default=None,
                       help="queue home (default: $MIND_ORDERS_HOME "
                            "or ./orders)")

    p = sub.add_parser("place", help="queue a new waiting order")
    p.add_argument("id")
    p.add_argument("--title", required=True)
    p.add_argument("--note", default=None)
    p.add_argument("--payload-file", default=None,
                   help="path to JSON object with extra context")
    common(p)
    p.set_defaults(fn=cmd_place)

    p = sub.add_parser("list", help="list waiting orders")
    p.add_argument("--all", action="store_true",
                   help="include released and cancelled")
    common(p)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="print one order")
    p.add_argument("id")
    common(p)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("release", help="fire an order on your word")
    p.add_argument("id")
    common(p)
    p.set_defaults(fn=cmd_release)

    p = sub.add_parser("cancel", help="refuse an order")
    p.add_argument("id")
    common(p)
    p.set_defaults(fn=cmd_cancel)

    p = sub.add_parser("log", help="tail the audit log")
    p.add_argument("-n", type=int, default=20)
    common(p)
    p.set_defaults(fn=cmd_log)

    sub.add_parser("selftest").set_defaults(
        fn=lambda _a: selftest())

    ns = ap.parse_args(argv)
    try:
        return ns.fn(ns)
    except OrdersError as exc:
        print(f"ordersctl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
