"""DAEDALUS blueprint: learn-gateway - the learning mind adapter.

Batch V8 mind tier. Proposal/promotion law for the OS's learning
loop, mirroring the fleet-learning doctrine:

  B9 evidence rule - a lesson proposal WITHOUT evidence citations is
  refused by name. Evidence is what separates lessons from noise.
  Human promotion valve - promote requires BOTH an L2 session AND an
  operator sign-off file present on disk; each missing precondition
  is refused with its own named error. No autonomous promotion exists.
  Ids are monotonic and never reused (vault convention).

The in-memory state stands in for learning/vault at commissioning;
the LAW above it is what this blueprint owns.

Extension shape: register(executors) wires learn propose/status/
report/promote onto APOLLO's drop-in protocol."""

import sys

GATEWAY = '''"""Learn gateway - evidence-gated proposals, human-gated promotion."""

import os
import time


class LearnState(object):
    def __init__(self):
        self.proposals = []
        self.lessons = []
        self._seq = 0

    def next_proposal_id(self):
        self._seq += 1
        return "P-%04d" % self._seq

    def next_lesson_id(self):
        n = len(self.lessons) + 1
        return "L%03d" % n


def propose(state, title, category, source, lesson, evidence,
            proposed_by="operator"):
    if not str(title or "").strip():
        return {"ok": False, "error": "title required"}
    if not str(lesson or "").strip():
        return {"ok": False, "error": "lesson body required"}
    evidence = [str(e) for e in (evidence or []) if str(e).strip()]
    if not evidence:
        return {"ok": False,
                "error": "evidence required: cite source as "
                         "path:line before proposing"}
    pid = state.next_proposal_id()
    record = {"id": pid, "title": title, "category": category,
              "source": source, "lesson": lesson,
              "evidence": evidence, "proposed_by": proposed_by,
              "status": "staged",
              "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    state.proposals.append(record)
    return {"ok": True, "proposal_id": pid}


def status_counts(state):
    return {"lessons": len(state.lessons),
            "proposals": sum(1 for p in state.proposals
                             if p["status"] == "staged"),
            "promoted": sum(1 for p in state.proposals
                            if p["status"] == "promoted")}


def promote(state, proposal_id, level, signoff_path):
    """THE VALVE: L2 session AND operator sign-off file. Either
    missing is a named refusal; nothing promotes silently."""
    if level != "L2":
        return {"ok": False,
                "error": "promote requires L2 session "
                         "(human authority), held %r" % level}
    if not signoff_path or not os.path.exists(signoff_path):
        return {"ok": False,
                "error": "operator sign-off file missing: "
                         "promotion stays human-gated"}
    for rec in state.proposals:
        if rec["id"] == str(proposal_id) and \\
                rec["status"] == "staged":
            rec["status"] = "promoted"
            lid = state.next_lesson_id()
            state.lessons.append({"id": lid,
                                  "title": rec["title"],
                                  "from": rec["id"]})
            return {"ok": True, "lesson_id": lid,
                    "proposal": rec["id"]}
    return {"ok": False,
            "error": "no staged proposal %r" % proposal_id}


def report(state):
    c = status_counts(state)
    lines = ["learning status", "lessons: %d" % c["lessons"],
             "staged proposals: %d" % c["proposals"],
             "promoted: %d" % c["promoted"]]
    return "\\n".join(lines)


def register(executors):
    """APOLLO drop-in adapter: learn domain lands here. The vault
    instance and sign-off path arrive via ctx at commissioning."""

    def _propose(session, cmd, ctx):
        st = ctx.get("learn_state")
        out = propose(st,
                      title=cmd.flags.get("title", cmd.target),
                      category=cmd.flags.get("category", "general"),
                      source=cmd.flags.get("source", ""),
                      lesson=cmd.flags.get("lesson", ""),
                      evidence=cmd.flags.get("evidence", []) or [],
                      proposed_by=session["profile"])
        return out
    executors[("learn", "propose")] = _propose

    def _status(session, cmd, ctx):
        return {"ok": True,
                "data": status_counts(ctx.get("learn_state"))}
    executors[("learn", "status")] = _status

    def _report(session, cmd, ctx):
        return {"ok": True, "text": report(ctx.get("learn_state"))}
    executors[("learn", "report")] = _report

    def _promote(session, cmd, ctx):
        return promote(ctx.get("learn_state"),
                       str(cmd.target or ""), session["level"],
                       ctx.get("signoff_path"))
    executors[("learn", "promote")] = _promote
'''

GATE = '''"""Self-test gate for learn-gateway (exit 0 = green)."""

import os
import sys
import tempfile

from learn_gateway import LearnState, propose, promote, report

EVIDENCE = ["tools/muster_launch.py:31", "docs/adr/0003:1"]


def main():
    st = LearnState()

    # B9: no evidence, no proposal - refused BY NAME
    r = propose(st, "t", "testing", "somewhere", "lesson text", [])
    assert not r["ok"] and "evidence required" in r["error"], r

    # blank-string evidence counts as absent
    r = propose(st, "t", "testing", "s", "l", ["   "])
    assert not r["ok"] and "evidence required" in r["error"], r

    # with evidence it stages, ids monotonic
    r1 = propose(st, "watchdog lesson", "testing",
                 "muster cycle", "bounded readline everywhere",
                 EVIDENCE)
    r2 = propose(st, "second lesson", "ops", "muster cycle",
                 "tree-kill fallbacks", EVIDENCE + ["x:1"])
    assert r1["ok"] and r2["ok"], (r1, r2)
    assert r1["proposal_id"] != r2["proposal_id"]
    counts = report(st)
    assert "staged proposals: 2" in counts, counts

    # THE VALVE: editor (L1) refused regardless of files
    signoff = os.path.join(tempfile.mkdtemp(prefix="signoff-"),
                           "operator.ok")
    open(signoff, "w").write("approved")
    r = promote(st, r1["proposal_id"], "L1", signoff)
    assert not r["ok"] and "requires L2" in r["error"], r

    # admin (L2) WITHOUT the sign-off file still refused, by name
    r = promote(st, r1["proposal_id"], "L2",
                os.path.join("nowhere", "operator.ok"))
    assert not r["ok"] and "sign-off file missing" in r["error"], r

    # admin WITH sign-off: promoted exactly once, lesson minted
    ok = promote(st, r1["proposal_id"], "L2", signoff)
    assert ok["ok"] and ok["lesson_id"] == "L001", ok
    again = promote(st, r1["proposal_id"], "L2", signoff)
    assert not again["ok"] and "no staged proposal" in \\
        again["error"], again
    assert report(st).splitlines()[3] == "promoted: 1"

    print("learn-gateway gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"learn_gateway.py": GATEWAY,
            "verify_learngateway.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # sign-off check gutted -> an L2 session promotes without the
    # operator file; the named-refusal assertion goes red
    "auto_promote": ("learn_gateway.py",
                     'if not signoff_path or not '
                     'os.path.exists(signoff_path):\n'
                     '        return {"ok": False,\n'
                     '                "error": "operator sign-off '
                     'file missing: "\n'
                     '                         "promotion stays '
                     'human-gated"}',
                     'pass'),
}

BLUEPRINT = {
    "description": "VOLTAGE learn-gateway: evidence-required "
                   "proposals, human-gated L2+sign-off promotion",
    "files": FILES,
    "gate": [sys.executable, "verify_learngateway.py"],
    "faults": dict(FAULTS),
}
