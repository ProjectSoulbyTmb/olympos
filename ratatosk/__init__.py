"""RATATOSK - the filesystem communication network of Olympos.

The squirrel that runs up and down the world tree carrying messages
between realms. Every organ of this workspace (sentinel, zeus, hades,
norn, dashboard, updater, ...) gets a filesystem mailbox under
`data/post/`; sending is an atomic file drop, reading marks letters
seen. No ports, no daemons - if you can write a file, you can talk.

Quick start:

    from ratatosk import Post
    post = Post()                       # default root: data/post/
    post.send("zeus", "incident", {"gate": "vulcan"}, frm="sentinel")
    post.send("zeus", "bolt", {"now": True}, frm="sentinel",
              priority="high")          # sorts ahead of normal mail
    letters = post.read("zeus")
    post.broadcast("incidents", "gate", {"name": "x", "ok": False})
    post.beat("sentinel", note="9/9 gates")

Request/reply between organs (reply lands in the caller's inbox):

    rid = post.request("oracle", "divine", {"q": "meaning"},
                       frm="seeker", timeout_s=5.0)
    # ... on the oracle side:
    post.respond(letter, {"answer": 42}, frm="oracle")

Topics rotate by size into .1/.2/.3 archives while every record keeps
a persistent, never-resetting seq - consumer cursors (since()) stay
correct across rotations.

CLI:

    python -m ratatosk status
    python -m ratatosk send --to zeus --kind ping --payload '{"hello":1}'
    python -m ratatosk read zeus
    python -m ratatosk tail incidents -n 20
    python -m ratatosk vitals --strict     # heartbeats + topic sizes

Contract: bus failures NEVER crash a host organ. Every helper used for
wiring swallows OSError/ImportError and degrades to a no-op.
"""

from .bus import (Post, VERSION, default_root, publish, safe_send,
                  fit_payload, deadman, beat)

__all__ = ["Post", "VERSION", "default_root", "publish", "safe_send",
           "fit_payload", "deadman", "beat"]
