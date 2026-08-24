"""ATLAS verifier - the hypervisor contract, checked.

Every check runs against a throwaway guests dir + audit trail; the
live data directory is never touched. Exit 0 = all green.
"""

import contextlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from atlas import content                        # noqa: E402
from atlas.kernel import AtlasError, Hypervisor, \
    resolve_within                               # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@contextlib.contextmanager
def sandbox():
    outer = tempfile.mkdtemp(prefix="atlas-verify-")
    saved = {f: getattr(content, f) for f in
             ("DATA_DIR", "AUDIT_PATH", "GUESTS_DIR")}
    saved_env = os.environ.get("RATATOSK_ROOT")
    data = os.path.join(outer, "data")
    content.DATA_DIR = data
    content.AUDIT_PATH = os.path.join(data, "audit.jsonl")
    content.GUESTS_DIR = os.path.join(data, "guests")
    os.environ["RATATOSK_ROOT"] = os.path.join(outer, "post")
    os.makedirs(content.GUESTS_DIR, exist_ok=True)
    try:
        yield Hypervisor()
    finally:
        for f, v in saved.items():
            setattr(content, f, v)
        if saved_env is None:
            os.environ.pop("RATATOSK_ROOT", None)
        else:
            os.environ["RATATOSK_ROOT"] = saved_env
        shutil.rmtree(outer, ignore_errors=True)


PY = sys.executable

# ------------------------------------------------------------- identity


@check
def guest_id_validation():
    with sandbox() as hv:
        for bad in ("../evil", "", "x" * 40, "has space"):
            try:
                hv.create(bad)
                raise AssertionError(f"accepted bad id {bad!r}")
            except AtlasError:
                pass
        hv.create("good-1")
        try:
            hv.create("good-1")
            raise AssertionError("duplicate accepted")
        except AtlasError:
            pass


# ---------------------------------------------------------- confinement


@check
def confinement_escape_is_refused():
    root = os.path.normpath(os.path.join("ws"))
    try:
        resolve_within(root, "../../outside")
        raise AssertionError("escape allowed")
    except AtlasError as exc:
        assert "outside" in str(exc)
    try:
        resolve_within(root, "ok/../..")
        raise AssertionError("sneak escape allowed")
    except AtlasError:
        pass


# ------------------------------------------------------------ execution


@check
def exec_captures_output_and_exit_code():
    with sandbox() as hv:
        hv.create("g1")
        r = hv.exec("g1", [PY, "-c",
                           "print('out-ok'); "
                           "import sys; sys.stderr.write('err-ok')"])
        assert r["ok"] and r["exit_code"] == 0, r
        assert "out-ok" in r["stdout"] and "err-ok" in r["stderr"], r
        # failing command reports honestly
        r2 = hv.exec("g1", [PY, "-c", "raise SystemExit(3)"])
        assert not r2["ok"] and r2["exit_code"] == 3, r2


@check
def timeout_kills_and_stays_under_ceiling():
    import time
    with sandbox() as hv:
        hv.create("slow")
        started = time.time()
        r = hv.exec("slow", [PY, "-c", "import time; time.sleep(120)"],
                    timeout_s=2)
        took = time.time() - started
        assert r["timed_out"] and not r["ok"], r
        assert took < 15, f"kill took too long: {took}"


@check
def output_cap_truncates_floods():
    with sandbox() as hv:
        hv.create("flood")
        r = hv.exec("flood", [PY, "-c",
                              "print('x' * (1024 * 1024))"])
        limit = content.RUN_OUTPUT_MAX_BYTES
        assert len(r["stdout"]) <= limit + 32, len(r["stdout"])


@check
def environment_is_scrubbed():
    os.environ["ATLAS_CANARY"] = "host-secret"
    try:
        with sandbox() as hv:
            hv.create("env")
            r = hv.exec("env", [PY, "-c",
                                "import os;"
                                "print(os.environ.get("
                                "'ATLAS_CANARY','MISSING'))"])
            assert "MISSING" in r["stdout"], r
    finally:
        os.environ.pop("ATLAS_CANARY", None)


# ------------------------------------------------------------ lifecycle


@check
def stop_then_purge_removes_world():
    with sandbox() as hv:
        hv.create("mortal")
        root = hv.guests["mortal"].root
        hv.stop("mortal")
        out = hv.purge("mortal")
        assert out["purged"] == "mortal" and not os.path.exists(root)
        try:
            hv.purge("mortal")
            raise AssertionError("purging a ghost succeeded")
        except KeyError:
            pass


@check
def max_guests_are_enforced():
    old = content.MAX_GUESTS
    content.MAX_GUESTS = 3
    try:
        with sandbox() as hv:
            for i in range(3):
                hv.create(f"g{i}")
            try:
                hv.create("g3")
                raise AssertionError("over-capacity guest accepted")
            except AtlasError as exc:
                assert "full" in str(exc)
    finally:
        content.MAX_GUESTS = old


# ----------------------------------------------------------------- wire


@check
def wire_roundtrip_with_rights():
    from atlas.server import AtlasServer
    with sandbox() as hv:
        server = AtlasServer(port=0, auto_reap=False, hypervisor=hv)
        server.start_async()
        try:
            # operator default: create + exec over the wire
            r = server.handle("create", {"name": "wire"}, cid=1)
            assert r["error"] is None, r
            r = server.handle(
                "exec",
                {"name": "wire", "argv": [PY, "-c", "print('via-wire')"]},
                cid=1)
            assert r["error"] is None and r["result"]["ok"], r
            assert "via-wire" in r["result"]["stdout"], r
            # watcher: compute is refused, reads stay open
            server.profiles[2] = "watcher"
            r = server.handle("create", {"name": "nope"}, cid=2)
            assert "right_denied" in str(r.get("error")), r
            r = server.handle("guests", {}, cid=2)
            assert r["error"] is None, "watcher lost read access"
        finally:
            server.running = False


@check
def sdk_surface_matches_registry():
    from atlas.server import AtlasSDK
    from norn import rights
    missing = [v for v in rights.ATLAS_PROFILES["watcher"]
               if v not in AtlasSDK._VALID]
    assert not missing, f"rights name verbs that do not exist: {missing}"


# ---------------------------------------------------------------- audit


@check
def audit_trail_is_tamper_evident():
    with sandbox() as hv:
        hv.create("aud")
        hv.stop("aud")
        ok, count, bad = hv.audit.verify()
        assert ok and count >= 2, (ok, count, bad)
        lines = open(hv.audit.path, encoding="utf-8").readlines()
        forged = json.loads(lines[0])
        forged["kind"] = "forged"
        lines[0] = json.dumps(forged, sort_keys=True,
                              separators=(",", ":")) + "\n"
        with open(hv.audit.path, "w", encoding="utf-8",
                  newline="") as fh:
            fh.writelines(lines)
        ok, _c, bad = hv.audit.verify()
        assert not ok and bad == 1, (ok, bad)


def main():
    print("=" * 64)
    print("ATLAS HYPERVISOR GATE - jailed worlds, hardened lanes")
    print("=" * 64)
    failures = []
    for fn in CHECKS:
        try:
            result = fn()
            if result is not True and result is not None:
                raise AssertionError(result)
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:              # noqa: BLE001 - gate
            failures.append(fn.__name__)
            print(f"[FAIL] {fn.__name__}: "
                  f"{type(exc).__name__}: {exc}")
    total = len(CHECKS)
    print("-" * 64)
    print(f"{total - len(failures)}/{total} checks green"
          + ("" if not failures else " - FAILURES PRESENT"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
