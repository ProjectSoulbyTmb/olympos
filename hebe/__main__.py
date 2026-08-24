"""HEBE CLI - command the scribe.

    python -m hebe once                  # single decree cycle
    python -m hebe once --dry-run        # plan only, touch nothing
    python -m hebe watch --interval 300  # the constant scribe
    python -m hebe status                # sea of records
    python -m hebe resume                # clear quarantine
    python -m hebe dictate --path docs/memo.md --body "..." [--title T]
    python -m hebe advise [topic]        # legal knowledge corpus
    python -m hebe license --spdx mit    # draft the platform license
    python -m hebe seal-ip --path DESIGN.md --classification confidential
"""

import argparse
import json
import sys

from . import content as C
from .kernel import ROOT, Scribe


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hebe")
    ap.add_argument("--mode", default=C.DEFAULT_MODE,
                    choices=C.MERGE_MODES)
    ap.add_argument("--interval", type=float, default=C.CADENCE_S)
    ap.add_argument("--root", default=ROOT,
                    help="workspace root (default: this checkout)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("once")
    o.add_argument("--dry-run", action="store_true")
    w = sub.add_parser("watch")
    w.add_argument("--max-cycles", type=int, default=0)
    sub.add_parser("status")
    sub.add_parser("resume")

    d = sub.add_parser("dictate")
    d.add_argument("--path", required=True)
    d.add_argument("--title", default="")
    d.add_argument("--body", default="")
    d.add_argument("--body-file", default=None,
                   help="read body text from this file instead")
    d.add_argument("--classification", default="internal",
                   choices=C.CLASSIFICATIONS)

    a = sub.add_parser("advise")
    a.add_argument("topic", nargs="?", default=None)

    l = sub.add_parser("license")
    l.add_argument("--spdx", default=C.DEFAULT_LICENSE,
                   choices=sorted(C.LICENSES))
    l.add_argument("--holder", default=C.DEFAULT_HOLDER)
    l.add_argument("--year", default="")

    s = sub.add_parser("seal-ip")
    s.add_argument("--path", required=True)
    s.add_argument("--classification", default="internal",
                   choices=C.CLASSIFICATIONS)

    ns = ap.parse_args(argv)
    eng = Scribe(root=ns.root, mode=ns.mode, interval=ns.interval)

    if ns.cmd == "once":
        rep = eng.once(dry_run=ns.dry_run)
        print(json.dumps(rep, indent=1))
        return 1 if rep.get("verdict") == "failed" else 0

    if ns.cmd == "watch":
        try:
            return eng.watch(max_cycles=ns.max_cycles)
        except KeyboardInterrupt:
            print("scribe paused (keyboard interrupt)")
            return 0

    if ns.cmd == "status":
        print(json.dumps(eng.status(), indent=1))
        return 0

    if ns.cmd == "resume":
        st = eng.resume()
        print("lane reopened: failures=%d quarantine cleared"
              % st["failures"])
        return 0

    if ns.cmd == "dictate":
        text = ns.body
        if ns.body_file:
            with open(ns.body_file, encoding="utf-8") as fh:
                text = fh.read()
        try:
            row = eng.dictate(ns.path, text, title=ns.title,
                              classification=ns.classification)
        except Exception as exc:              # noqa: BLE001 - CLI
            print(json.dumps({"verdict": "refused",
                              "reason": str(exc)}, indent=1))
            return 1
        print(json.dumps(row, indent=1))
        return 0

    if ns.cmd == "advise":
        out = eng.advise(ns.topic)
        if not out:
            print(json.dumps({"unknown-topic": ns.topic,
                              "topics": C.knowledge_topics()},
                             indent=1))
            return 2
        print(json.dumps(out, indent=1))
        return 0

    if ns.cmd == "license":
        row = eng.seed_license(ns.spdx, ns.holder, ns.year or "")
        if row is None:
            print("LICENSE already exists - dictate an amendment "
                  "instead (never silently overwrite a license)")
            return 1
        print(json.dumps(row, indent=1))
        return 0

    if ns.cmd == "seal-ip":
        row = eng.seal_ip(ns.path, ns.classification)
        print(json.dumps(row, indent=1))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
