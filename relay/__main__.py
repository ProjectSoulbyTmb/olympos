"""RELAY CLI - bridge, stream and fleet intents from any shell.

    python -m relay once                       # single cycle
    python -m relay watch [--every 60]         # constant update stream
    python -m relay status                     # bridge + lane snapshot
    python -m relay send --type build --blueprint jsonl-echo --name web1
    python -m relay send --type repair --note "operator asked"
    python -m relay riley [--status]           # studio work stream
"""

import argparse
import json
import os
import sys
import uuid

from . import content
from .bridge import Relay, watch
from .riley_stream import RileyStream


def cmd_once(_a):
    print(json.dumps(Relay().run_cycle(), indent=2, default=str))
    return 0


def cmd_watch(a):
    watch(every_s=a.every)
    return 0


def cmd_status(_a):
    relay = Relay()
    pending, done, failed = _counts()
    mind_pending, mind_done, mind_failed = _mind_counts()
    tail = relay.post.tail(content.TOPIC, n=3)
    print(json.dumps({
        "topic": content.TOPIC,
        "mailbox": content.MAILBOX,
        "mind_mailbox": content.MIND_MAILBOX,
        "intents": {"pending": pending, "done": done, "failed": failed},
        "mind_intents": {"pending": mind_pending, "done": mind_done,
                         "failed": mind_failed},
        "recent_updates": [
            {"seq": r.get("seq"), "kind": r.get("kind"),
             "at": (r.get("payload") or {}).get("at")}
            for r in tail],
    }, indent=2, default=str))
    return 0


def cmd_send(a):
    intent = {"id": f"cli-{uuid.uuid4().hex[:8]}", "type": a.type,
              "note": a.note}
    if a.blueprint:
        intent["blueprint"] = a.blueprint
    if a.name:
        intent["name"] = a.name
    os.makedirs(content.INTENT_DIR, exist_ok=True)
    path = os.path.join(
        content.INTENT_DIR, f"{intent['id']}.intent.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(intent, fh, indent=1)
    print(f"queued {path}")
    return 0


def cmd_riley(a):
    def _n(path):
        try:
            return sum(1 for f in os.listdir(path)
                       if f.endswith(".order.json"))
        except OSError:
            return 0

    def _cursor(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return int(fh.read().strip() or 0)
        except (OSError, ValueError):
            return 0

    if a.status:
        print(json.dumps({
            "studio": content.RILEY_URL,
            "spool": {"pending": _n(content.RILEY_PENDING_DIR),
                      "sent": _n(content.RILEY_SENT_DIR),
                      "rejected": _n(content.RILEY_REJECTED_DIR)},
            "cursor": _cursor(content.RILEY_CURSOR),
        }, indent=2))
        return 0
    s = RileyStream()
    result = dict(s.stream())
    result["announced"] = s.completions()
    print(json.dumps(result, indent=2, default=str))
    return 0


def _counts():
    def _n(path):
        try:
            return sum(1 for f in os.listdir(path)
                       if f.endswith(".intent.json"))
        except OSError:
            return 0
    return (_n(content.INTENT_DIR), _n(content.INTENT_DONE),
            _n(content.INTENT_FAILED))


def _mind_counts():
    def _n(path):
        try:
            return sum(1 for f in os.listdir(path)
                       if f.endswith(".intent.json"))
        except OSError:
            return 0
    return (_n(content.MIND_INTENT_DIR), _n(content.MIND_DONE),
            _n(content.MIND_FAILED))


def main(argv=None):
    p = argparse.ArgumentParser(prog="relay",
                                description="daedalus<->venus bridge")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("once"); s.set_defaults(fn=cmd_once)
    s = sub.add_parser("watch")
    s.add_argument("--every", type=float, default=None)
    s.set_defaults(fn=cmd_watch)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("send")
    s.add_argument("--type", required=True,
                   choices=["build", "repair", "status"])
    s.add_argument("--blueprint", default=None)
    s.add_argument("--name", default=None)
    s.add_argument("--note", default=None)
    s.set_defaults(fn=cmd_send)
    s = sub.add_parser("riley", help="studio work stream pass/status")
    s.add_argument("--status", action="store_true",
                   help="spool counts, no dialing")
    s.set_defaults(fn=cmd_riley)
    args = p.parse_args(argv)
    fn = getattr(args, "fn", None)
    if fn is None:
        p.print_help()
        return 2
    return fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
