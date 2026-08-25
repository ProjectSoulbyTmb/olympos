r"""BOUNDARY verify - proves the ADR-0002 isolation contract works.

V1 acceptance (roadmap): an attempted cross-boundary write fails on
BOTH sides. Every check runs against temp fixtures or injected roots -
no live machine state beyond the repo itself, no network, and nothing
is ever written to D:\VOLTAGE by this suite.

    python verify_boundary.py     (exit 0 = all green)
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import boundary                                    # noqa: E402
from boundary import BoundaryViolation             # noqa: E402

CHECKS = []
FOREIGN = boundary.FOREIGN_DEFAULT


def check(fn):
    CHECKS.append(fn)
    return fn


class armed_jail:
    """Temporarily arm the jail at a fixture root; restore after."""

    def __init__(self, root, exempt=None):
        self.root = root
        self.exempt = exempt
        self._saved = {}

    def __enter__(self):
        for key, val in ((boundary.JAIL_ENV, self.root),
                         (boundary.EXEMPT_ENV, self.exempt)):
            self._saved[key] = os.environ.get(key)
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        return self

    def __exit__(self, *exc):
        for key, val in self._saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        return False


def ensure_unarmed(fn):
    """Run a check with the jail guaranteed inert."""
    def wrapper():
        with armed_jail(None):
            fn()
    wrapper.__name__ = fn.__name__
    return wrapper


# ------------------------------------------------------------- side A

@check
@ensure_unarmed
def foreign_detection_exact_and_siblings():
    assert boundary.is_foreign(FOREIGN), FOREIGN
    assert boundary.is_foreign(os.path.join(FOREIGN, "data", "post"))
    assert boundary.is_foreign(FOREIGN.lower())      # case-insensitive
    assert boundary.is_foreign(FOREIGN + "\\sub\\..\\..\\deep") \
        or not boundary.is_foreign(
            os.path.normpath(FOREIGN + r"\sub\..\..\deep")), \
        "normalized escapes must still judge correctly"
    # sibling-prefix trap: VOLTAGEx is NOT inside VOLTAGE
    assert not boundary.is_foreign(FOREIGN + "x\\innocent")
    assert not boundary.is_foreign(HERE)             # our own repo


@check
@ensure_unarmed
def refuse_foreign_fails_loud():
    try:
        boundary.refuse_foreign(os.path.join(FOREIGN, "seeds"),
                                op="write")
    except BoundaryViolation as exc:
        assert exc.side == "foreign-territory"
        assert exc.op == "write"
        assert FOREIGN.lower() in str(exc).lower()
    else:
        raise AssertionError("foreign touch must fail loud")
    # non-foreign passes untouched
    boundary.refuse_foreign(HERE, op="write")


# ------------------------------------------------------------- side B

@check
@ensure_unarmed
def jail_inert_when_unarmed():
    assert boundary.jail_root() is None
    boundary.jail_check(r"C:\anywhere\at\all")       # no-op, no raise
    boundary.guard_dispatch(r"C:\anywhere\at\all")


@check
def jail_armed_refuses_outside():
    with tempfile.TemporaryDirectory(prefix="boundary-jail-") as jail:
        inside = os.path.join(jail, "data", "post")
        with armed_jail(jail):
            assert boundary.jail_root() == jail
            boundary.jail_check(inside)              # home passes
            for outside in (os.path.dirname(jail),
                            os.path.join(HERE, "ratatosk"),
                            "C:\\Windows"):
                try:
                    boundary.jail_check(outside, op="write")
                except BoundaryViolation as exc:
                    assert exc.side == "path-jail"
                    assert exc.op == "write"
                else:
                    raise AssertionError(
                        f"jail escape not refused: {outside}")
            # prefix trap: sibling of the jail root is outside
            try:
                boundary.jail_check(jail.rstrip("\\/") + "x")
            except BoundaryViolation:
                pass
            else:
                raise AssertionError("sibling of jail must be refused")


@check
def jail_exempt_lane_honored():
    with tempfile.TemporaryDirectory(prefix="boundary-jail-") as jail:
        lane = tempfile.mkdtemp(prefix="boundary-pushlane-")
        try:
            with armed_jail(jail, exempt=lane):
                boundary.jail_check(lane)            # sanctioned lane
                try:
                    boundary.jail_check(os.path.join(
                        lane, "..", "elsewhere"))
                except BoundaryViolation:
                    pass                             # normalization wins
                else:
                    raise AssertionError(
                        "exemption must not admit normalized escapes")
            with armed_jail(jail):
                try:
                    boundary.jail_check(lane)
                except BoundaryViolation:
                    pass                             # exempt gone: refused
                else:
                    raise AssertionError(
                        "exemption without env declaration must refuse")
        finally:
            shutil.rmtree(lane, ignore_errors=True)


# ---------------------------------------------------------- acceptance

@check
@ensure_unarmed
def acceptance_olympos_side_refuses_voltage_write():
    r"""V1 acceptance, side one: an Olympos lane writing into
    D:\VOLTAGE fails loud before any disk touch."""
    target = os.path.join(FOREIGN, "data", "post", "olympos", "inbox")
    try:
        boundary.guard_dispatch(target, op="mailbox-write")
    except BoundaryViolation:
        pass
    else:
        raise AssertionError("olympos lane reached foreign territory")
    assert not os.path.exists(target), "refusal must precede any write"


@check
def acceptance_voltage_side_refuses_outside_write():
    """V1 acceptance, side two: an armed voltage organ writing
    outside its jail fails loud."""
    with tempfile.TemporaryDirectory(prefix="voltage-home-") as home:
        target = os.path.join(home, "..", "escape.txt")
        with armed_jail(home):
            try:
                boundary.guard_dispatch(target, op="organ-write")
            except BoundaryViolation:
                pass
            else:
                raise AssertionError("voltage organ left the jail")
            # and the polarity flip: home is NOT foreign to voltage
            assert boundary.foreign_roots() == []
            boundary.guard_dispatch(os.path.join(home, "data"))


# ------------------------------------------------- ratatosk dispatch seam

@check
def ratatosk_post_refuses_foreign_root():
    """Live proof the organ seam fires: constructing a Post aimed at
    the foreign root raises BEFORE creating anything."""
    script = "\n".join([
        "import os, sys",
        "os.environ.pop('VOLTAGE_ROOT', None)",
        "sys.path.insert(0, '.')",
        "import ratatosk.bus as bus",
        "try:",
        f"    bus.Post(root=r'{FOREIGN}\\data\\post')",
        "except Exception as exc:",
        "    print(type(exc).__name__)",
        "    sys.exit(0)",
        "sys.exit('FAIL: foreign Post construction was not refused')",
    ])
    env = dict(os.environ)
    env.pop("VOLTAGE_ROOT", None)
    r = subprocess.run([sys.executable, "-c", script], cwd=HERE,
                       capture_output=True, text=True, timeout=60,
                       env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "BoundaryViolation" in r.stdout, r.stdout


@check
def ratatosk_post_accepts_local_root():
    """Positive control: ordinary lanes keep working unchanged."""
    with tempfile.TemporaryDirectory(prefix="boundary-ok-") as outer:
        script = "\n".join([
            "import os, sys",
            "os.environ.pop('VOLTAGE_ROOT', None)",
            "sys.path.insert(0, '.')",
            "import ratatosk.bus as bus",
            "p = bus.Post(root=os.path.join(r'" + outer +
            "', 'post'))",
            "p.register('smoke')",
            "print('ok')",
        ])
        env = dict(os.environ)
        env.pop("VOLTAGE_ROOT", None)
        r = subprocess.run([sys.executable, "-c", script], cwd=HERE,
                           capture_output=True, text=True, timeout=60,
                           env=env)
        assert r.returncode == 0 and "ok" in r.stdout, \
            r.stdout + r.stderr


@check
def ratatosk_armed_jail_refuses_escape():
    """Inside a fixture 'voltage' tree, the bus refuses to place mail
    outside the jail - the exported organ inherits the contract."""
    with tempfile.TemporaryDirectory(prefix="voltage-bus-") as home:
        script = "\n".join([
            "import os, sys",
            "sys.path.insert(0, '.')",
            "import ratatosk.bus as bus",
            "try:",
            "    bus.Post(root=r'" + os.path.dirname(home) +
            "')",                     # outside the jail
            "except Exception as exc:",
            "    print(type(exc).__name__)",
            "    sys.exit(0)",
            "sys.exit('FAIL: armed bus accepted an outside root')",
        ])
        env = dict(os.environ)
        env[boundary.JAIL_ENV] = home
        r = subprocess.run([sys.executable, "-c", script], cwd=HERE,
                           capture_output=True, text=True, timeout=60,
                           env=env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "BoundaryViolation" in r.stdout, r.stdout


# ---------------------------------------------------------------- CLI

@check
@ensure_unarmed
def cli_exit_codes_and_policy():
    py = sys.executable
    def run(*args, **kw):
        e = dict(os.environ)
        e.setdefault("VOLTAGE_ROOT", kw.pop("jail", "") or "")
        if not e["VOLTAGE_ROOT"]:
            e.pop("VOLTAGE_ROOT", None)
        e.update(kw)
        return subprocess.run([py, os.path.join(HERE, "boundary.py"),
                               *args], capture_output=True, text=True,
                              timeout=60, env=e)

    r = run("check", FOREIGN)
    assert r.returncode == 1 and "DENIED" in r.stdout, r.stdout
    r = run("check", HERE)
    assert r.returncode == 0 and "ALLOWED" in r.stdout, r.stdout
    r = run("policy")
    assert r.returncode == 0 and "OLYMPOS" in r.stdout \
        and FOREIGN in r.stdout, r.stdout
    with tempfile.TemporaryDirectory(prefix="boundary-cli-") as jail:
        r = run("policy", jail=jail)
        assert "VOLTAGE" in r.stdout and "ARMED" in r.stdout, r.stdout
        r = run("jail", HERE, jail=jail)
        assert r.returncode == 1 and "DENIED" in r.stdout, r.stdout
        r = run("jail", os.path.join(jail, "in"), jail=jail)
        assert r.returncode == 0, r.stdout


# ----------------------------------------------------- content scan

SCAN_EXT = {".py", ".ps1", ".js", ".mjs", ".cmd", ".bat"}
ALLOW_SCAN = {
    "boundary.py": "self: declares the policy constant",
    "verify_boundary.py": "self: scans for stray references",
}


@check
@ensure_unarmed
def tracked_executables_never_name_the_foreign_root():
    """Scope rule (ADR-0002): no olympos executable may hard-code the
    voltage root; docs (.md/.json) may discuss it freely."""
    import re
    out = subprocess.run(["git", "-c", "safe.directory=*", "ls-files",
                          "-z"], cwd=HERE, capture_output=True,
                         check=True).stdout
    files = [p.decode("utf-8") for p in out.split(b"\0") if p]
    needle = re.compile(re.escape(FOREIGN.replace("\\", "/"))
                        .replace("/", "[/\\\\]"), re.IGNORECASE)
    hits = []
    scanned = 0
    for path in files:
        base = path.replace("\\", "/").rsplit("/", 1)[-1]
        ext = os.path.splitext(base)[1].lower()
        if ext not in SCAN_EXT or base in ALLOW_SCAN:
            continue
        scanned += 1
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for no, line in enumerate(fh, start=1):
                    if needle.search(line):
                        hits.append(f"{path}:{no}: {line.strip()[:90]}")
        except OSError:
            continue
    print(f"  scan: {scanned} executables checked for "
          f"'{FOREIGN}' literals")
    assert not hits, "foreign-root literals in executables:\n" \
        + "\n".join(hits)


def main():
    print("=" * 64)
    print("BOUNDARY VERIFY - ADR-0002 two-sided isolation contract")
    print("=" * 64)
    failures = []
    for fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:              # noqa: BLE001 - verifier
            failures.append(fn.__name__)
            print(f"[FAIL] {fn.__name__}: {type(exc).__name__}: {exc}")
    print("-" * 64)
    ok = len(CHECKS) - len(failures)
    print(f"{ok}/{len(CHECKS)} checks green"
          + ("" if not failures else f" - FAILING: {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
