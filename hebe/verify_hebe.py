"""HEBE gate - proves the scribe records, refuses and ships.

Every scenario runs inside throwaway fixture repositories (bare origin
+ working clone) under the system temp dir; the real workspace is only
read for imports. No network, no real ``gh``: PR/merge is simulated by
a fake that performs an honest squash against the bare origin via git
plumbing.

Run:  python hebe/verify_hebe.py
Exit: 0 green, 1 failures.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from hebe import content as C          # noqa: E402
from hebe.content import FAIL_LIMIT    # noqa: E402
from hebe.kernel import (              # noqa: E402
    Refusal, Scribe)

CHECKS = []
FAILS = []

BRANCH_REF = "refs/heads/auto/hebe"

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "hebe-test",
    "GIT_AUTHOR_EMAIL": "hebe@test",
    "GIT_COMMITTER_NAME": "hebe-test",
    "GIT_COMMITTER_EMAIL": "hebe@test",
}


def check(fn):
    CHECKS.append(fn)
    return fn


def git(root, *args, check_=True):
    env = dict(os.environ)
    env.update(GIT_ENV)
    proc = subprocess.run(["git", "-C", root] + list(args),
                          capture_output=True, text=True,
                          timeout=120, env=env)
    if check_ and proc.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args),
                                           proc.stderr.strip()[:300]))
    return proc.stdout.strip()


class Fixture:
    """bare origin + a live clone, both disposable."""

    def __init__(self):
        self.base = tempfile.mkdtemp(prefix="hebe-gate-")
        self.bare = os.path.join(self.base, "origin.git")
        self.root = os.path.join(self.base, "mirror")
        git(self.base, "init", "--bare", "-b", "main", "origin.git")
        git(self.base, "clone", "origin.git", "mirror",
            check_=False)  # warns on empty repo; fine
        with open(os.path.join(self.root, ".gitignore"), "w") as fh:
            fh.write(".worktrees/\ndata/\nhebe/data/\nposeidon/data/\n")
        with open(os.path.join(self.root, "file.txt"), "w") as fh:
            fh.write("line-1\nline-2\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", "seed")
        git(self.root, "push", "-u", "origin", "main")
        git(self.root, "config", "user.name", "hebe-test")
        git(self.root, "config", "user.email", "hebe@test")

    def engine(self, mode="local"):
        return Scribe(root=self.root, mode=mode, bus=False,
                      interval=60.0)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as fh:
            return fh.read()

    def exists(self, rel):
        return os.path.exists(os.path.join(self.root, rel))

    def origin_ref(self, ref):
        out = subprocess.run(
            ["git", "--git-dir", self.bare, "rev-parse", "--verify",
             "--quiet", ref],
            capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else None

    def origin_blob(self, ref, rel):
        proc = subprocess.run(
            ["git", "--git-dir", self.bare, "show",
             "%s:%s" % (ref, rel)],
            capture_output=True, text=True)
        return proc.stdout if proc.returncode == 0 else None

    def squash_on_origin(self):
        """Honest fake of `gh pr merge --squash`."""
        tip = self.origin_ref(BRANCH_REF)
        parent = self.origin_ref("refs/heads/main")
        tree = git(self.bare, "log", "-1", "--format=%T", tip)
        new = git(self.bare, "commit-tree", tree, "-p", parent,
                  "-m", "squash: hebe decree (simulated)")
        git(self.bare, "update-ref", "refs/heads/main", new)
        git(self.bare, "update-ref", "-d", BRANCH_REF)

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)


# ------------------------------------------------------------- tests

@check
def legal_knowledge_catalog_integrity():
    assert C.DISCLAIMER and "not legal advice" in C.DISCLAIMER
    assert C.knowledge_topics(), "no knowledge topics"
    for spdx, entry in C.LICENSES.items():
        assert entry["name"] and entry["kind"], spdx
        assert entry["obligations"], "%s lacks obligations" % spdx
    full = [s for s, e in C.LICENSES.items() if e.get("text")]
    assert {"proprietary", "mit", "apache-2.0"} <= set(full), full
    for spdx in full:
        body = C.license_text(spdx, year="2026", holder="Tmb")
        assert len(body) > 200, spdx
        assert "{year}" not in body and "{holder}" not in body, spdx
    stub = C.license_text("cc-by-4.0", year="2026", holder="Tmb",
                          title="Design")
    assert "CC BY 4.0" in stub and "2026" in stub
    try:
        C.license_text("no-such-license")
        raise AssertionError("unknown spdx must raise")
    except KeyError:
        pass


@check
def license_seeding_and_oath_are_idempotent():
    fx = Fixture()
    try:
        assert not fx.exists("LICENSE"), "fixture must start bare"
        eng = fx.engine()
        rep = eng.once()
        assert rep["verdict"] == "shipped", rep
        lic = fx.read("LICENSE")
        assert "All rights reserved" in lic and "2026" in lic, lic[:120]
        oaths = [json.loads(x) for x in
                 open(eng.oaths_path, encoding="utf-8")]
        assert len(oaths) == 1 and \
            oaths[0]["grant"]["grant_class"] == "L2"
        seals = [json.loads(x) for x in
                 open(eng.ip_path, encoding="utf-8")]
        assert seals and all(s["kind"] == "ip-seal" for s in seals)
        # operator amends the license by hand: HEBE never overwrites
        # it, but the operator's text still flows through her lane
        fx.write("LICENSE", "custom operator license\n")
        rep2 = eng.once()
        assert rep2["verdict"] == "shipped", rep2
        assert fx.read("LICENSE") == "custom operator license\n"
        tip = fx.origin_ref(BRANCH_REF)
        assert "custom operator license" in fx.origin_blob(
            tip, "LICENSE"), "operator's own words must survive"
    finally:
        fx.cleanup()


@check
def dictation_privileges_and_refusals():
    fx = Fixture()
    try:
        eng = fx.engine()
        row = eng.dictate("docs/legal/memo.md", "# memo\nbody\n",
                          title="memo", classification="confidential")
        assert row["verdict"] == "written" and \
            row["classification"] == "confidential", repr(row)
        assert fx.read(os.path.join("docs", "legal", "memo.md")) \
            .startswith("# memo")
        bad = [
            ("docs/.env", "X=1\n"),
            (".git/hebe-intrusion.md", "[core]\n"),
            (".worktrees/hermes/x.md", "hi\n"),
            ("../escape.md", "hi\n"),
            ("keys/server.key", "material\n"),
            ("creds/id_rsa", "material\n"),
        ]
        for rel, text in bad:
            try:
                eng.dictate(rel, text)
                raise AssertionError("must refuse: %s" % rel)
            except Refusal:
                pass
            assert not fx.exists(rel), "refusal wrote anyway: %s" % rel
        try:
            eng.dictate(
                "docs/ok.md",
                "curl -H 'Authorization: Bearer"
                " AbCdEf123456GhIjKlMnOpQrStUvWx' target\n")
            raise AssertionError("secret content must be refused")
        except Refusal as exc:
            assert "secret-formation" in str(exc)
        assert not fx.exists("docs/ok.md")
        ledger = open(eng.ledger_path, encoding="utf-8").read()
        assert '"refused"' in ledger, \
            "refusals not journaled: %r" % ledger[-400:]
        assert "load-bearing-wall:.git" in ledger, \
            "wall refusal reason missing: %r" % ledger[-400:]
    finally:
        fx.cleanup()


@check
def scoped_ship_leaves_foreign_drift_alone():
    fx = Fixture()
    try:
        eng = fx.engine()
        eng.dictate("docs/legal/charter.md", "# charter\nfull text\n")
        # foreign drift another writer owns: none of HEBE's business
        fx.write("file.txt", "line-1 FOREIGN\nline-2\n")
        rep = eng.once()
        assert rep["verdict"] == "shipped", rep
        tip = fx.origin_ref(BRANCH_REF)
        assert tip, "branch never reached origin"
        blob = fx.origin_blob(tip, "docs/legal/charter.md")
        assert "full text" in blob
        foreign = fx.origin_blob(tip, "file.txt")
        assert "FOREIGN" not in foreign, \
            "HEBE swept a stranger's drift"
        d = eng.scoped_drift(["file.txt"])
        assert d["tracked"] == ["file.txt"], \
            "foreign drift must survive untouched in root"
        st = eng._load_state()
        assert st["seq"] == 1
    finally:
        fx.cleanup()


@check
def squash_mode_settles_the_mirror():
    fx = Fixture()
    try:
        eng = fx.engine(mode="squash")
        eng.dictate("docs/legal/policy.md", "# policy\ntext here\n")
        fx.write("file.txt", "line-1 STILL-MINE\nline-2\n")
        calls = []

        def fake_gh(*args):
            calls.append(tuple(args[:2]))
            if args[0] == "pr":
                if args[1] == "list":
                    return ""
                if args[1] == "create":
                    return "7"
                if args[1] == "merge":
                    fx.squash_on_origin()
                    return ""
            raise AssertionError("unexpected gh call %s" % (args,))

        eng._gh = fake_gh
        rep = eng.once()
        assert rep["verdict"] == "shipped" and rep.get("settled"), rep
        assert "text here" in fx.read(
            os.path.join("docs", "legal", "policy.md")), \
            "policy content wrong after settle: %r" % fx.read(
                os.path.join("docs", "legal", "policy.md"))
        assert fx.read("file.txt") == "line-1 STILL-MINE\nline-2\n", \
            "settle must never touch foreign files"
        log = git(fx.root, "log", "--oneline", "-2", "origin/main")
        assert "squash:" in log, "no squash commit on main: %r" % log
        assert ("pr", "merge") in calls, \
            "no merge call: %r" % (calls,)
    finally:
        fx.cleanup()

@check
def conflict_never_destroys_local_work():
    """A rival takes the same lines on main; HEBE's decree surfaces
    the clash at the PR layer - and her local words survive whole."""
    fx = Fixture()
    try:
        rival = os.path.join(fx.base, "rival")
        git(fx.base, "clone", "origin.git", "rival")
        with open(os.path.join(rival, "file.txt"), "w") as fh:
            fh.write("line-1 RIVAL\nline-2\n")
        git(rival, "commit", "-am", "rival wins the line")
        git(rival, "push", "origin", "main")

        eng = fx.engine(mode="squash")
        eng.dictate("file.txt", "line-1 HEBE\nline-2\n")

        def clashing_merge(*args):
            if args[:2] == ("pr", "merge"):
                raise RuntimeError("merge conflict on main")
            return ""
        eng._gh = clashing_merge
        rep = eng.once()
        assert rep["verdict"] == "failed", rep
        assert fx.read("file.txt") == "line-1 HEBE\nline-2\n", \
            "a failed decree destroyed local work"
        st = eng._load_state()
        assert st["failures"] == 1
        assert not eng.quarantined(st), \
            "single failure must not trip the breaker"
    finally:
        fx.cleanup()


@check
def repeated_failures_trip_the_breaker_then_resume():
    """An outage at the PR layer (gh down) fails every cycle that
    carries new work; after FAIL_LIMIT consecutive failures the
    scribe quarantines herself, and resume reopens the lane."""
    fx = Fixture()
    try:
        eng = fx.engine(mode="squash")
        eng._gh = lambda *a: (_ for _ in ()).throw(
            RuntimeError("github unreachable"))
        for attempt in range(1, FAIL_LIMIT + 1):
            # fresh dictated work each cycle = a real shipping try
            eng.dictate("docs/outage-%d.md" % attempt,
                        "cycle %d\n" % attempt)
            rep = eng.once()
            assert rep["verdict"] == "failed", (attempt, rep)
            assert fx.read(os.path.join(
                "docs", "outage-%d.md" % attempt)) == \
                "cycle %d\n" % attempt, "local work destroyed"
        st = eng._load_state()
        assert eng.quarantined(st), "breaker did not trip"
        rep_q = eng.once()
        assert rep_q["verdict"] == "quarantined", rep_q
        eng.resume()
        assert not eng.quarantined()
        assert eng._load_state()["failures"] == 0
    finally:
        fx.cleanup()


@check
def ip_register_is_append_only_with_digests():
    fx = Fixture()
    try:
        eng = fx.engine()
        eng.dictate("DESIGN.md", "# architecture v1\n")
        first = eng.seal_ip("DESIGN.md", "confidential")
        rows_before = open(eng.ip_path, encoding="utf-8").read()
        eng.dictate("DESIGN.md", "# architecture v2 amended\n")
        second = eng.seal_ip("DESIGN.md", "confidential")
        rows_after = open(eng.ip_path, encoding="utf-8").read()
        assert rows_after.startswith(rows_before), \
            "register rewrote history"
        assert first["sha256"] != second["sha256"]
        assert second["sha256"] == hashlib_sha(fx, "DESIGN.md"), \
            "seal digest must match the sealed bytes"
    finally:
        fx.cleanup()


def hashlib_sha(fx, rel):
    import hashlib
    with open(os.path.join(fx.root, rel), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@check
def inbox_letters_are_drained_and_filed():
    fx = Fixture()
    try:
        eng = fx.engine()
        inbox = os.path.join(eng.inbox_dir)
        os.makedirs(inbox, exist_ok=True)
        with open(os.path.join(inbox, "letter-1.json"), "w") as fh:
            json.dump({"path": "docs/from-letter.md",
                       "title": "via letter",
                       "text": "recorded from a letter"}, fh)
        with open(os.path.join(inbox, "letter-2.json"), "w") as fh:
            json.dump({"action": "seal-ip", "path": "FLOW.md",
                       "classification": "internal"}, fh)
        rep = eng.once()
        assert rep["verdict"] == "shipped", rep
        assert "recorded from a letter" in fx.read(
            os.path.join("docs", "from-letter.md"))
        assert eng.pending_letters() == [], "inbox not drained"
        filed = os.listdir(eng.filed_dir)
        assert len(filed) == 2, filed
        seals = open(eng.ip_path, encoding="utf-8").read()
        assert '"path":"FLOW.md"' in seals or '"path": "FLOW.md"' \
            in seals
    finally:
        fx.cleanup()


@check
def dry_run_touches_nothing():
    fx = Fixture()
    try:
        eng = fx.engine()
        before_files = sorted(
            os.listdir(eng.data_dir)) if os.path.exists(
            eng.data_dir) else []
        rep = eng.once(dry_run=True)
        assert rep["verdict"] == "dry-run"
        assert rep["plan"]["will_seed_license"] is True
        after_files = sorted(
            os.listdir(eng.data_dir)) if os.path.exists(
            eng.data_dir) else []
        assert before_files == after_files, "dry-run wrote state"
        assert not fx.exists("LICENSE")
        assert eng.status()["seq"] == 0
    finally:
        fx.cleanup()


def main():
    print("=" * 64)
    print("HEBE GATE - record everything, fear nothing, destroy "
          "nothing")
    print("=" * 64)
    for fn in CHECKS:
        try:
            fn()
            print("[PASS] %s" % fn.__name__)
        except AssertionError as exc:
            FAILS.append(fn.__name__)
            print("[FAIL] %s: %s" % (fn.__name__, exc))
        except Exception as exc:              # noqa: BLE001 - gate
            FAILS.append(fn.__name__)
            print("[FAIL] %s: %s: %s"
                  % (fn.__name__, type(exc).__name__, exc))
    total = len(CHECKS)
    print("-" * 64)
    print("%d/%d checks green" % (total - len(FAILS), total))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
