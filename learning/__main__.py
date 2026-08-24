"""LEARNING CLI: propose lessons, inspect the queue, build reports.

    python -m learning status
    python -m learning report
    python -m learning propose --title "..." --category testing \\
        --source "verify_x failure" --lesson "..." --tags a,b \\
        --by metis --evidence "path:line"
"""

import argparse
import json

from . import report as report_mod
from .vault import Vault


def main(argv=None):
    ap = argparse.ArgumentParser(prog="learning")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sub.add_parser("report")
    p = sub.add_parser("propose")
    p.add_argument("--title", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--lesson", required=True)
    p.add_argument("--tags", default="")
    p.add_argument("--by", default="operator")
    p.add_argument("--evidence", action="append", default=[])
    p.add_argument("--rationale", default="")

    ns = ap.parse_args(argv)
    vault = Vault()

    if ns.cmd == "status":
        print(json.dumps({
            "lessons": len(vault.lessons()),
            "next_id": vault.next_id(),
            "proposals": len(vault.proposals()),
            "streams": report_mod.build()["streams"],
        }, indent=2))
        return 0

    if ns.cmd == "report":
        print(report_mod.markdown(report_mod.build()))
        return 0

    tags = [t.strip() for t in ns.tags.split(",") if t.strip()]
    path = vault.propose(
        {"title": ns.title, "category": ns.category,
         "source": ns.source, "lesson": ns.lesson, "tags": tags},
        proposed_by=ns.by, evidence=ns.evidence,
        rationale=ns.rationale)
    print(f"proposal staged: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
