"""SYSTEM gate - end-to-end proof of the integration guarantees.

INTEGRATION.md section 1 makes five guarantees; per-organ suites prove
each one in isolation. This suite wires the machinery together and
proves the seams between organs:

  G1 deterministic replay .... norn.replay records a seeded scenario
                               and replays it to an identical state
                               digest; a different seed diverges (A4)
  G2 mutation attestation .... norn.witness journals every mutating
                               verb crossing the SDK, failures
                               included (A5)
  G4 no partial reads ........ ratatosk broadcast -> since() delivers
                               every record exactly once per consumer
                               with strictly monotonic seqs, and every
                               (topic, kind) pair is catalogue-legal
                               under the buskit contract
  A8 ledger lint ............. the sentinel incidents ledger parses;
                               strict buskit envelopes for new lines,
                               documented legacy v1 lines tolerated -
                               and the current writer emits v2

Stdlib-only. Exit 0 green / 1 red, like every verify suite.

Run:  python verify_system.py
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from norn.clockwork import Clockwork          # noqa: E402
from norn.replay import run_seed_file, state_digest, write_seed  # noqa
from norn.witness import Witness, WitnessSDK  # noqa: E402
from ratatosk.bus import Post                 # noqa: E402
from buskit import envelope                   # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name))
        print(f"  PASS  {name:<44} {detail}")
    except Exception as exc:  # noqa: BLE001 - failure is evidence
        RESULTS.append((False, name))
        print(f"  FAIL  {name:<44} {type(exc).__name__}: {exc}")


# --------------------------------------------------------------- scenario

class ProvisionWorld:
    """Tiny deterministic world: organs draw stock and earn xp.

    Every bit of chance flows through Clockwork, so a seed pins the
    whole session. save() is JSON-canonical - it is what norn.replay
    digests.
    """

    def __init__(self, seed):
        self.clock = Clockwork(seed=seed)
        self.stock = {"bolt": 3, "gear": 3}
        self.xp = {}
        self.coins = 0            # WitnessSDK instruments coin deltas
        self.log = []

    @property
    def tick(self):
        return self.clock.tick      # witness journals read world.tick

    def save(self):
        return {"tick": self.clock.tick, "stock": self.stock,
                "xp": self.xp, "coins": self.coins, "log": self.log}

    def drain(self, item):
        """Mutating verb: empty a stock slot (test scaffolding made
        honest - scarcity enters the session THROUGH the SDK surface,
        so replay reproduces it exactly)."""
        self.stock[item] = 0
        self.clock.advance()
        self.log.append(f"drain:{item}")
        return 0

    def provision(self, organ, item):
        """Mutating verb: consume one item, credit random xp."""
        if self.stock.get(item, 0) <= 0:
            raise RuntimeError(f"out of {item}")
        self.stock[item] -= 1
        gain = self.clock.randint(1, 5)
        self.xp[organ] = self.xp.get(organ, 0) + gain
        self.clock.advance()
        self.log.append(f"{organ}+{item}+{gain}")
        return gain


def world_factory(seed):
    # The world IS its own SDK - mutating verbs are its public methods,
    # so norn.replay records/replays them directly.
    world = ProvisionWorld(seed)
    return world, world


def scenario(world, sdk):
    """The recorded session: successes AND one engineered failure.
    Every state change flows through SDK verbs so the recorded seed
    replays byte-identically."""
    sdk.provision("vulcan", "bolt")
    sdk.provision("zeus", "gear")
    sdk.drain("bolt")                 # deterministic future refusal
    try:
        sdk.provision("ptah", "bolt")
    except RuntimeError:
        pass                          # failure is part of the record
    sdk.provision("norn", "gear")


def _read_lines(path, attempts=6):
    """Read a freshly written journal, tolerating transient Windows
    file locks (AV/indexer) with short backoff."""
    import time
    last = None
    for _ in range(attempts):
        try:
            with open(path, encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
        except PermissionError as exc:
            last = exc
            time.sleep(0.05)
    raise last


# ------------------------------------------------------------------ G1/A4

def t_replay_digest():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "scenario.jsonl")
        digest = write_seed(path, seed=7, script=scenario,
                            world_factory=world_factory,
                            note="system gate provisioning run")
        if not digest:
            raise AssertionError("recording produced no digest")
        note = run_seed_file(path, world_factory=world_factory)
        if note != "system gate provisioning run":
            raise AssertionError(f"unexpected note: {note!r}")

        other = os.path.join(tmp, "other-seed.jsonl")
        digest8 = write_seed(other, seed=8, script=scenario,
                             world_factory=world_factory,
                             note="divergence control")
        if digest8 == digest:
            raise AssertionError("different seed reproduced same digest")
    return "record -> replay -> identical digest; seeds diverge"


# ------------------------------------------------------------------ G2/A5

def t_witness_covers_every_verb():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["RATATOSK_ROOT"] = os.path.join(tmp, "post")
        w = None
        try:
            world = ProvisionWorld(7)
            w = Witness(log_dir=os.path.join(tmp, "witness"),
                        actor="sysgate", world=world)
            sdk = WitnessSDK(world, w, actor="sysgate")
            scenario(world, sdk)
        finally:
            if w is not None:
                w.close()
            entries = _read_lines(w.path)
            os.environ.pop("RATATOSK_ROOT", None)

        verbs = [e["verb"] for e in entries]
        if verbs.count("provision") != 4 or verbs.count("drain") != 1:
            raise AssertionError(f"expected 4 provisions (incl. the "
                                 f"refusal) + 1 drain, got {verbs}")
        failed = [e for e in entries if not e["ok"]]
        if len(failed) != 1 or "error" not in failed[0]:
            raise AssertionError("the refused provision was not "
                                 "journalled with its error")
        for e in entries:
            problems = []
            if e.get("actor") != "sysgate":
                problems.append("actor")
            if not isinstance(e.get("args_sha"), str) or \
                    len(e["args_sha"]) != 16:
                problems.append("args_sha")
            if problems:
                raise AssertionError(f"malformed entry {e}: {problems}")
    return "3 calls + 1 failure journalled with digests"


# ------------------------------------------------------------------ G4

def t_bus_roundtrip_envelopes():
    from buskit.envelope import TOPICS
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["RATATOSK_ROOT"] = os.path.join(tmp, "post")
        try:
            post = Post()
            seqs = []
            for i in range(5):
                env = envelope.make(
                    "incident", "sentinel",
                    {"name": f"gate{i}", "detail": "pass"},
                    topic="incidents", rights="watcher")
                seq = post.broadcast("incidents", "incident",
                                     {"name": f"gate{i}",
                                      "detail": "pass",
                                      "env_id": env["id"]},
                                     frm="sentinel")
                seqs.append(seq)
            if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
                raise AssertionError(f"seqs not strictly monotonic: {seqs}")
            allowed = TOPICS.get("incidents", frozenset())
            if "incident" not in allowed:
                raise AssertionError("'incident' missing from catalogue")

            readers = {}
            for consumer in ("gaia", "auditor"):
                recs = post.since("incidents", consumer)
                readers[consumer] = [r["payload"]["name"] for r in recs]
            expected = [f"gate{i}" for i in range(5)]
            if readers["gaia"] != expected or readers["auditor"] != expected:
                raise AssertionError(f"exactly-once violated: {readers}")

            replayed = post.since("incidents", "gaia")
            if replayed:
                raise AssertionError(f"cursor did not advance: {replayed}")
        finally:
            os.environ.pop("RATATOSK_ROOT", None)
    return "5/5 records, two consumers exactly-once, seqs monotonic"


# ------------------------------------------------------------------ A8

LEGACY_V1_KEYS = {"ts", "kind", "name", "detail"}


def lint_incidents_line(line):
    """One ledger line -> list of violations.

    v2 (current writer): strict buskit envelope on topic 'incidents'.
    v1 (legacy): exact quadruple ts/kind/name/detail, tolerated so
    history written before the migration stays green forever.
    Anything else is a violation.
    """
    try:
        obj = json.loads(line)
    except ValueError as exc:
        return [f"unparseable line: {exc}"]
    if not isinstance(obj, dict):
        return ["ledger entry is not an object"]
    if set(obj) == LEGACY_V1_KEYS:
        return []                      # documented legacy v1 shape
    return envelope.validate(obj)


def t_ledger_lint_and_writer():
    real_ledger = os.path.join(HERE, "data", "sentinel",
                               "incidents.jsonl")
    bad_total = 0
    scanned = 0
    if os.path.exists(real_ledger):
        with open(real_ledger, encoding="utf-8") as fh:
            for no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                scanned += 1
                problems = lint_incidents_line(line)
                if problems:
                    bad_total += 1
                    print(f"        ledger:{no}: {problems}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_ledger = os.path.join(tmp, "sentinel", "incidents.jsonl")
        import sentinel
        saved = sentinel.LEDGER
        sentinel.LEDGER = tmp_ledger
        try:
            sentinel.ledger("gate", "sysgate probe", "pass")
        finally:
            sentinel.LEDGER = saved
        with open(tmp_ledger, encoding="utf-8") as fh:
            fresh = fh.read().strip()
        env, problems = envelope.loads(fresh, strict=True)
        if problems:
            raise AssertionError(f"writer emitted invalid envelope: "
                                 f"{problems}")
        if env.get("topic") != "incidents" or \
                env.get("kind") != "incident" or \
                env.get("payload", {}).get("name") != "sysgate probe":
            raise AssertionError(f"wrong envelope shape: {env}")

    if bad_total:
        raise AssertionError(f"{bad_total}/{scanned} ledger lines violate "
                             "both v2 envelope and legacy v1 schema")
    return f"{scanned} live lines clean; writer emits strict v2"


def main():
    print("verify_system")
    check("seeded session replays to identical digest", t_replay_digest)
    check("every mutating verb attested by witness", t_witness_covers_every_verb)
    check("bus round-trip exactly-once + catalogue", t_bus_roundtrip_envelopes)
    check("incidents ledger lint + v2 writer", t_ledger_lint_and_writer)
    failed = [n for ok, n in RESULTS if not ok]
    print(f"system: {len(RESULTS) - len(failed)}/{len(RESULTS)} "
          "checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
