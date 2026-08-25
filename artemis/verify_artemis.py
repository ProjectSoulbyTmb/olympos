"""Verify ARTEMIS - red/green suite for the hunt kernel.

Every test runs against sandbox directories through the ctx
injection seams; the real workspace is never touched. Pins:

  A8   every ledger line is a valid buskit envelope ('incidents')
  6    'fleet.repair' letters ride the 'updates' topic only
  L013/L017 bounded autonomy: repairs capped, escalation fires once,
       cooldown stands down, then re-arms
  quarantine over destruction: corrupt letters are counted, not purged

Run:  python artemis/verify_artemis.py
Exit: 0 all green, 1 any test failed.
"""

import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from artemis import hunt                          # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def sandbox():
    tmp = tempfile.mkdtemp(prefix="artemis-verify-")
    ctx = hunt.make_ctx(
        here=tmp,
        post_root=os.path.join(tmp, "data", "post"),
        ledger_path=os.path.join(tmp, "data", "artemis", "hunt.jsonl"),
        state_path=os.path.join(tmp, "data", "artemis",
                                "hunt-state.json"),
        config={},
    )
    return tmp, ctx


def finding(sig="sig", target="t", repairable=False):
    return {"signature": sig, "target": target,
            "detail": "verify fixture", "severity": "T3",
            "repairable": repairable}


def lint_ledger(path):
    from buskit import envelope
    bad = []
    with open(path, encoding="utf-8") as fh:
        for no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                _, problems = envelope.loads(line, strict=False)
            except ValueError as exc:
                bad.append((no, str(exc)))
                continue
            if problems:
                bad.append((no, "; ".join(problems)))
    return bad


# --------------------------------------------------------------- tests

@test
def envelope_contract():
    """A8: recorded findings validate as buskit envelopes."""
    tmp, ctx = sandbox()
    try:
        hunt.record(ctx, finding(), "observed")
        hunt.record(ctx, finding(target="u"), "repaired")
        bad = lint_ledger(ctx["ledger_path"])
        assert not bad, f"invalid ledger lines: {bad}"
        lines = [json.loads(l) for l in
                 open(ctx["ledger_path"], encoding="utf-8")
                 if l.strip()]
        assert all(l.get("error") is None or
                   isinstance(l.get("error"), str) for l in lines)
        assert {l["from"] for l in lines} == {"artemis"}
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def gitignore_drift_repair():
    """Missing required ignores are detected then repaired once."""
    tmp, ctx = sandbox()
    try:
        gi = os.path.join(tmp, ".gitignore")
        with open(gi, "w", encoding="utf-8") as fh:
            fh.write("data/\n*.pyc\n")     # __pycache__/ .worktrees/ missing
        sigs = [("gitignore-drift", hunt.hunt_gitignore_drift,
                 hunt.repair_gitignore_drift)]
        s1 = hunt.sweep(ctx, signatures=sigs)
        assert s1["repairs"] == 1, s1
        text = open(gi, encoding="utf-8").read()
        for req in hunt.REQUIRED_IGNORES:
            assert req in text.splitlines(), (req, text)
        s2 = hunt.sweep(ctx, signatures=sigs)
        assert s2["findings"] == 0, s2
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def stale_lock_hunted_and_repaired():
    """Only dead locks are flagged; repair unlinks just those."""
    tmp, ctx = sandbox()
    try:
        lockdir = os.path.join(ctx["post_root"], "locks")
        os.makedirs(lockdir)
        dead = os.path.join(lockdir, "res-a.lock")
        fresh = os.path.join(lockdir, "res-b.lock")
        for p in (dead, fresh):
            open(p, "w").close()
        old = time.time() - (hunt.LOCK_DEAD_S + 60)
        os.utime(dead, (old, old))
        found = hunt.hunt_stale_locks(ctx)
        assert [f["target"] for f in found] == [dead], found
        assert hunt.repair_stale_lock(ctx, found[0]) is True
        assert not os.path.exists(dead) and os.path.exists(fresh)
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def corrupt_letters_counted_not_purged():
    """Quarantine over destruction: evidence preserved, drift reported."""
    tmp, ctx = sandbox()
    try:
        seen_dir = os.path.join(ctx["post_root"], "hypnos", "seen")
        os.makedirs(seen_dir)
        for i in range(hunt.CORRUPT_ALERT + 2):
            open(os.path.join(seen_dir, f"corrupt-{i}.json"),
                 "w").close()
        quiet = os.path.join(ctx["post_root"], "gaia", "seen")
        os.makedirs(quiet)
        open(os.path.join(quiet, "corrupt-only.json"), "w").close()
        found = hunt.hunt_corrupt_letters(ctx)
        assert len(found) == 1 and found[0]["target"] == "hypnos", found
        assert f"{hunt.CORRUPT_ALERT + 2} quarantined" \
            in found[0]["detail"], found
        left = len(os.listdir(seen_dir))
        assert left == hunt.CORRUPT_ALERT + 2, "evidence was purged"
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def compile_break_reports_file_and_line():
    """Broken entrypoints surface file:line; clean ones stay silent."""
    tmp, ctx = sandbox()
    try:
        good = os.path.join(tmp, "good.py")
        bad = os.path.join(tmp, "bad.py")
        open(good, "w").write("VALUE = 1\n")
        open(bad, "w").write("def broken(:\n    pass\n")
        ctx["realms"] = [
            {"name": "good", "lang": "python", "path": "good.py"},
            {"name": "bad", "lang": "python", "path": "bad.py"},
        ]
        found = hunt.hunt_compile_breaks(ctx)
        assert len(found) == 1, found
        assert found[0]["target"] == "bad.py"
        assert re_line.search(found[0]["detail"]), found
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


re_line = re.compile(r"line \d+")


@test
def retired_ports_parsed_from_netstat():
    """Squatters on retired ports are named with their pid."""
    tmp, ctx = sandbox()
    try:
        ctx["netstat_text"] = (
            "\n"
            "  TCP    127.0.0.1:43590    0.0.0.0:0   LISTENING   4242\n"
            "  TCP    127.0.0.1:43901    0.0.0.0:0   LISTENING   999\n"
            "  TCP    127.0.0.1:43591    0.0.0.0:0   LISTENING   777\n"
        )
        found = hunt.hunt_retired_ports(ctx)
        ports = sorted(int(f["target"]) for f in found)
        assert ports == [43590, 43591], found
        pids = " ".join(f["detail"] for f in found)
        assert "4242" in pids and "777" in pids and "999" not in pids
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def escalation_fires_once_then_cooldowns():
    """Unrepairable findings escalate once at the cap, then stand down."""
    tmp, ctx = sandbox()
    try:
        old_after, old_cooldown = hunt.ESCALATE_AFTER, \
            hunt.COOLDOWN_SWEEPS
        hunt.ESCALATE_AFTER, hunt.COOLDOWN_SWEEPS = 3, 4
        try:
            sigs = [("stub", lambda c: [finding("stub", "x")], None)]
            actions = []
            for _ in range(6):
                hunt.sweep(ctx, signatures=sigs)
            lines = [json.loads(l) for l in
                     open(ctx["ledger_path"], encoding="utf-8")
                     if l.strip()]
            stub_lines = [l for l in lines
                          if l["payload"].get("signature") == "stub"]
            actions = [l["payload"]["action"] for l in stub_lines]
            escalations = sum(1 for a in actions
                              if a.startswith("escalated"))
            assert escalations == 1, actions
            assert actions[0] == "observed" and \
                actions[1] == "observed", actions
            assert actions[2].startswith("escalated"), actions
            assert all(a == "watching" for a in actions[3:]), actions
            state = hunt.load_state(ctx)
            rec = state["targets"]["stub::x"]
            assert rec["escalated"] is True and rec["cooldown"] > 0, rec
            bad = lint_ledger(ctx["ledger_path"])
            assert not bad, f"invalid lines after escalation: {bad}"
        finally:
            hunt.ESCALATE_AFTER, hunt.COOLDOWN_SWEEPS = \
                old_after, old_cooldown
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def repairs_capped_before_escalation():
    """A failing repair is attempted MAX_ATTEMPTS times, no more."""
    tmp, ctx = sandbox()
    try:
        calls = []

        def failing_repair(c, f):
            calls.append(1)
            return False

        sigs = [("flaky", lambda c: [finding("flaky", "y",
                                             repairable=True)],
                 failing_repair)]
        for _ in range(5):
            hunt.sweep(ctx, signatures=sigs)
        assert len(calls) == hunt.MAX_ATTEMPTS, calls
        lines = [json.loads(l) for l in
                 open(ctx["ledger_path"], encoding="utf-8")
                 if l.strip()]
        flaky = [l["payload"]["action"] for l in lines
                 if l["payload"].get("signature") == "flaky"]
        assert flaky.count("repair-failed") == 2, flaky
        assert any(a.startswith("repair-failed+escalated")
                   for a in flaky), flaky
        assert flaky[-1] == "cooldown", flaky   # stood down afterwards
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def fleet_repair_letter_on_success():
    """Landed repairs broadcast fleet.repair on the updates topic."""
    tmp, ctx = sandbox()
    try:
        gi = os.path.join(tmp, ".gitignore")
        open(gi, "w").close()          # everything missing -> one repair
        sigs = [("gitignore-drift", hunt.hunt_gitignore_drift,
                 hunt.repair_gitignore_drift)]
        hunt.sweep(ctx, signatures=sigs)
        topic_file = os.path.join(ctx["post_root"], "topics",
                                  "updates.jsonl")
        assert os.path.isfile(topic_file), "no updates topic letter"
        letters = [json.loads(l) for l in open(topic_file,
                                               encoding="utf-8")
                   if l.strip()]
        kinds = {l.get("kind") for l in letters}
        frm = {l.get("from") for l in letters}
        assert kinds == {"fleet.repair"}, kinds
        assert frm == {"artemis"}, frm
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def heartbeat_stamped_per_sweep():
    """Liveness: artemis beats through ratatosk like every organ."""
    tmp, ctx = sandbox()
    try:
        hunt.sweep(ctx, signatures=[])
        hb = os.path.join(ctx["post_root"], "artemis",
                          "heartbeat.json")
        assert os.path.isfile(hb), "no heartbeat written"
        data = json.load(open(hb, encoding="utf-8"))
        assert data.get("organ") == "artemis", data
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def hunter_crash_does_not_stop_the_hunt():
    """Circuit breaker per INTEGRATION section 8: crash becomes a T2."""
    tmp, ctx = sandbox()
    try:
        def boom(c):
            raise RuntimeError("bowstring snapped")

        sigs = [("boom", boom, None)]
        summary = hunt.sweep(ctx, signatures=sigs)
        assert summary["findings"] == 1, summary
        lines = [json.loads(l) for l in
                 open(ctx["ledger_path"], encoding="utf-8")
                 if l.strip()]
        hit = [l for l in lines
               if "snapped" in l["payload"].get("detail", "")]
        assert hit, lines
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def roster_claims_every_signature_exactly_once():
    """The retinue owns the whole board - no orphans, no double claims."""
    from artemis import nymphs
    registry = {name: (fn, rep) for name, fn, rep in hunt.SIGNATURES}
    board = set(registry)
    claims = nymphs.coverage()
    assert set(claims) == board, (sorted(claims), sorted(board))
    assert len(claims) == len(board), "double claim on the board"
    yielded = list(nymphs.dispatch(hunt))
    assert len(yielded) == len(board), yielded
    for nymph_name, sig_name, fn, rep in yielded:
        owner = dict((n.name, n) for n in nymphs.NYMPHS)[nymph_name]
        assert sig_name in owner.signatures
        assert (fn, rep) == registry[sig_name], sig_name
    return True, ""


@test
def ledger_lines_carry_nymph_attribution():
    """Every finding knows which nymph hunted it (or '-')."""
    tmp, ctx = sandbox()
    try:
        gi = os.path.join(tmp, ".gitignore")
        open(gi, "w").close()
        hunt.sweep(ctx)                       # roster-led sweep
        explicit = [("-", "sig-x", lambda c: [finding("sig-x", "t")],
                     None)]
        hunt.sweep(ctx, signatures=explicit)  # explicit attribution
        lines = [json.loads(l) for l in
                 open(ctx["ledger_path"], encoding="utf-8")
                 if l.strip()]
        by_sig = {l["payload"]["signature"]: l["payload"]
                  for l in lines if l.get("payload")}
        assert by_sig["gitignore-drift"]["nymph"] == "maera", by_sig
        assert by_sig["sig-x"]["nymph"] == "-", by_sig
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def drill_proves_nymphs_inside_the_jail():
    """Advanced automation path: every nymph gates green via DAEDELUS."""
    from artemis import nymphs
    tmp, ctx = sandbox()
    try:
        real_here = nymphs.here
        nymphs.here = lambda: tmp            # sandbox guests/artifacts
        try:
            summary = nymphs.drill(ctx, lanes=2)
        finally:
            nymphs.here = real_here
            nymphs.restore_workshop_paths()
        assert not summary["degraded"], summary
        assert summary["green"] == summary["total"] == 6, summary
        arts = os.path.join(tmp, "data", "artemis", "drill",
                            "daedalus", "artifacts")
        sealed = os.listdir(arts)
        assert len(sealed) == 6, sealed      # one artifact per nymph
        lines = [json.loads(l) for l in
                 open(ctx["ledger_path"], encoding="utf-8")
                 if l.strip()]
        drills = [l for l in lines
                  if l["payload"].get("signature") == "drill"]
        assert len(drills) == 6, drills
        assert all(l["payload"]["action"] == "gate-green"
                   for l in drills), drills
        bad = lint_ledger(ctx["ledger_path"])
        assert not bad, f"invalid lines after drill: {bad}"
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def drill_degrades_when_the_workshop_is_dark():
    """No DAEDELUS -> recorded degradation, never a crash."""
    from artemis import nymphs

    def dark(lanes=2):
        raise RuntimeError("workshop is closed")

    tmp, ctx = sandbox()
    try:
        summary = nymphs.drill(ctx, workshop_factory=dark)
        assert summary["degraded"] is True, summary
        assert summary["green"] == 0 and \
            len(summary["results"]) == 6, summary
        lines = [json.loads(l) for l in
                 open(ctx["ledger_path"], encoding="utf-8")
                 if l.strip()]
        hit = [l for l in lines
               if l["payload"].get("signature") == "drill-degraded"]
        assert hit and "closed" in hit[0]["payload"]["detail"], lines
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def registry_lists_all_signatures():
    """The full board: nine signatures, each owned and moded."""
    rows = {name: (owner, mode)
            for owner, name, mode in hunt.list_signatures()}
    owners = {"daphne": {"compile-break"},
              "cyrene": {"retired-port-squatter"},
              "arethusa": {"corrupt-letters", "stale-lock"},
              "britomartis": {"ledger-corruption",
                              "missing-baseline"},
              "taygete": {"stale-organ"},
              "maera": {"tracked-artifacts", "gitignore-drift"}}
    modes = {"tracked-artifacts", "gitignore-drift", "stale-lock"}
    assert len(rows) == 9, rows
    for name, (owner, mode) in rows.items():
        assert name in owners[owner], (name, owner)
        want = "repair" if name in modes else "report"
        assert mode == want, (name, mode)
    return True, ""


# --------------------------------------------------------------- runner

def main():
    failed = []
    for fn in TESTS:
        name = fn.__name__
        try:
            ok, note = fn()
        except AssertionError as exc:
            ok, note = False, str(exc)
        except Exception as exc:      # noqa: BLE001
            ok, note = False, f"{type(exc).__name__}: {exc}"
        print(f"{'PASS' if ok else 'FAIL'}  {name}"
              + (f" - {note}" if note and not ok else ""))
        if not ok:
            failed.append(name)
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} green")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
