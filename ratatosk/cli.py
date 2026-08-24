"""RATATOSK CLI - drive the post office from any shell.

    python -m ratatosk status
    python -m ratatosk send --to zeus --kind ping --payload '{"a":1}'
    python -m ratatosk read zeus [--keep] [--limit N] [--json]
    python -m ratatosk post incidents --kind gate --payload '...'
    python -m ratatosk tail incidents [-n 20]
    python -m ratatosk follow incidents --consumer dashboard
    python -m ratatosk beat sentinel --note "9/9 gates"
    python -m ratatosk vitals [--stale-s 600] [--strict]
    python -m ratatosk demo
"""

import argparse
import json
import os
import shutil
import sys
import tempfile

from .bus import Post, default_root


def _payload(text):
    if text is None:
        return {}
    if text.startswith("@"):
        with open(text[1:], "r", encoding="utf-8") as fh:
            return json.load(fh)
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


def cmd_status(_args):
    st = Post().status()
    print(f"post office: {st['root']}")
    print()
    print(f"{'organ':<16} {'unread':>6} {'heartbeat':>12}  note")
    for name, o in sorted(st["organs"].items()):
        age = o["heartbeat_age_s"]
        age_s = f"{age:.0f}s ago" if age is not None else "-"
        flag = "" if not o["stale"] else " (stale)"
        print(f"{name:<16} {o['unread']:>6} {age_s:>12}{flag}")
    print()
    for t, meta in sorted(st["topics"].items()):
        print(f"topic {t}: {meta['lines']} letters, "
              f"{meta['bytes']} bytes")
    if not st["topics"]:
        print("topics: (none yet)")
    return 0


def cmd_send(args):
    post = Post()
    lid = post.send(args.to, args.kind, _payload(args.payload),
                    frm=args.frm)
    print(f"delivered {lid} -> {args.to}/inbox")
    return 0


def cmd_post(args):
    seq = Post().broadcast(args.topic, args.kind,
                           _payload(args.payload), frm=args.frm)
    print(f"broadcast to {args.topic} seq={seq}")
    return 0


def cmd_read(args):
    post = Post()
    letters = post.read(args.organ, limit=args.limit,
                        mark=not args.keep)
    if args.json:
        print(json.dumps(letters, indent=1, default=str))
        return 0
    for l in letters:
        head = json.dumps(l.get("payload"), default=str)[:100]
        print(f"[{l.get('ts')}] {l.get('from')} -> {l.get('to')} "
              f"({l.get('kind')}) id={l.get('id')}")
        print(f"    {head}")
    if not letters:
        print(f"{args.organ}: inbox empty")
    return 0


def cmd_tail(args):
    for rec in Post().tail(args.topic, n=args.n):
        head = json.dumps(rec.get("payload"), default=str)[:120]
        print(f"#{rec.get('seq')} [{rec.get('ts')}] "
              f"{rec.get('from')} ({rec.get('kind')}): {head}")
    return 0


def cmd_follow(args):
    seen = 0
    for rec in Post().since(args.topic, args.consumer):
        seen += 1
        head = json.dumps(rec.get("payload"), default=str)[:120]
        print(f"#{rec.get('seq')} {rec.get('from')} "
              f"({rec.get('kind')}): {head}")
    print(f"-- {seen} new letter(s) for {args.consumer} "
          f"on {args.topic}; cursor advanced")
    return 0


def cmd_beat(args):
    hb = Post().beat(args.organ, note=args.note)
    print(f"{hb['organ']} heartbeat at {hb['ts']}"
          + (f" ({hb['note']})" if hb.get("note") else ""))
    return 0


def cmd_vitals(args):
    """One line per organ (heartbeat age, unread, stale marker) plus
    per-topic line counts. --strict exits 1 when ANY known organ's
    heartbeat is older than --stale-s or missing entirely."""
    post = Post()
    stale = False
    print(f"post office: {post.root}")
    print(f"{'organ':<16} {'unread':>6} {'hb-age':>10}  state")
    for name in post.organs():
        age = post.heartbeat_age(name)
        if age is None:
            state = "STALE (no heartbeat)"
        elif age > args.stale_s:
            state = "STALE"
        else:
            state = "ok"
        stale = stale or state.startswith("STALE")
        age_s = f"{age:.0f}s" if age is not None else "-"
        print(f"{name:<16} {post.unread(name):>6} {age_s:>10}  {state}")
    topics = post.topics()
    for t in topics:
        print(f"topic {t}: {post.line_count(t)} lines")
    if not topics:
        print("topics: (none yet)")
    return 1 if (args.strict and stale) else 0


def cmd_purge(_args):
    removed = Post().purge()
    print(f"purged {removed} seen letter(s)")
    return 0


def cmd_demo(_args):
    """Two organs + a topic, end-to-end, inside a throwaway root."""
    root = os.path.join(tempfile.mkdtemp(prefix="ratatosk-demo-"),
                        "post")
    try:
        post = Post(root=root)
        post.register("odin", role="allfather")
        post.register("ratatoskr", role="courier")
        post.send("odin", "report", {"gossip": "nidhogg chews roots"},
                  frm="ratatoskr")
        post.send("odin", "alert", {"eagle": "arguing"}, frm="ratatoskr")
        post.send("ratatoskr", "orders", {"route": "trunk"},
                  frm="odin")
        post.broadcast("nine-realms", "weather",
                       {"forecast": "fimbulwinter likely"}, frm="yggdrasil")
        post.beat("ratatoskr", note="laps completed: many")

        print("== odin reads his inbox ==")
        for l in post.read("odin"):
            print(f"  {l['from']}: {l['payload']}")
        print("== ratatoskr reads his ==")
        for l in post.read("ratatoskr"):
            print(f"  {l['from']}: {l['payload']}")
        print("== midgard subscribes to nine-realms ==")
        for rec in post.since("nine-realms", "midgard"):
            print(f"  #{rec['seq']} {rec['from']}: {rec['payload']}")
        st = post.status()
        print(f"== status: organs={sorted(st['organs'])} "
              f"topics={st['topics']}")
        print("demo complete - the tree talks.")
        return 0
    finally:
        shutil.rmtree(os.path.dirname(root), ignore_errors=True)


def build_parser():
    p = argparse.ArgumentParser(
        prog="ratatosk", description="Yggdrasil filesystem post office")
    p.add_argument("--root", default=None,
                   help="override post root (default: data/post)")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("status", help="organs, mailboxes, topics")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("send", help="deliver a letter to an organ")
    s.add_argument("--to", required=True)
    s.add_argument("--kind", default="note")
    s.add_argument("--payload", default=None)
    s.add_argument("--frm", default="cli")
    s.set_defaults(fn=cmd_send)

    s = sub.add_parser("read", help="drain an organ's inbox")
    s.add_argument("organ")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--keep", action="store_true",
                   help="do not mark as read")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("post", help="broadcast on a topic")
    s.add_argument("topic")
    s.add_argument("--kind", default="event")
    s.add_argument("--payload", default=None)
    s.add_argument("--frm", default="cli")
    s.set_defaults(fn=cmd_post)

    s = sub.add_parser("tail", help="last N records of a topic")
    s.add_argument("topic")
    s.add_argument("-n", type=int, default=20)
    s.set_defaults(fn=cmd_tail)

    s = sub.add_parser("follow", help="consume a topic from a cursor")
    s.add_argument("topic")
    s.add_argument("--consumer", required=True)
    s.set_defaults(fn=cmd_follow)

    s = sub.add_parser("beat", help="record a heartbeat")
    s.add_argument("organ")
    s.add_argument("--note", default=None)
    s.set_defaults(fn=cmd_beat)

    s = sub.add_parser("vitals",
                       help="organ heartbeats + topic line counts")
    s.add_argument("--stale-s", type=float, default=600.0,
                   help="heartbeat age (s) considered stale")
    s.add_argument("--strict", action="store_true",
                   help="exit 1 if any organ is stale or silent")
    s.set_defaults(fn=cmd_vitals)

    s = sub.add_parser("purge", help="cap the seen folders")
    s.set_defaults(fn=cmd_purge)

    s = sub.add_parser("demo", help="self-contained end-to-end demo")
    s.set_defaults(fn=cmd_demo)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "root", None):
        os.environ["RATATOSK_ROOT"] = args.root
    fn = getattr(args, "fn", None)
    if fn is None:
        parser.print_help()
        return 2
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
