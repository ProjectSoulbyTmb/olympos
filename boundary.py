r"""BOUNDARY - two-sided isolation guard for PROJECT VOLTAGE.

Canonical authority for the V1 isolation contract (ADR-0002,
docs/plans/project-voltage-roadmap.md): Olympos lanes and VOLTAGE
lanes share one disk but never share runtime state. This module is
the single file both fleets run; polarity is derived from posture,
not from edited copies:

  Side A - foreign territory (any fleet that is NOT voltage):
      D:\VOLTAGE is foreign soil. Every touch refused, loud.
  Side B - path jail (the voltage fleet itself, once armed):
      every path a voltage organ dispatches must live inside
      D:\VOLTAGE. The sole sanctioned exception is the mirror push
      lane; it opts out by declaring its extra roots in the
      VOLTAGE_JAIL_EXEMPT env var (semicolon-separated), never by
      editing this file.

Posture detection: setting VOLTAGE_ROOT arms the jail and flips
side A off (a fleet's own home is not foreign to itself). Unset -
as on Olympos today - side A is on and side B is inert, so this
module changes no existing behavior until the day it must.

Organs call `guard_dispatch` at their path seams (ratatosk bus
mailboxes are wired already); gates call the CLI:

    python boundary.py check <path>...   # judge as an Olympos lane
    python boundary.py jail <path>...    # judge under $VOLTAGE_ROOT
    python boundary.py policy            # print effective posture
    python boundary.py foreign-root      # print the foreign root

Exit 0 = allowed. Exit 1 = violation / bad invocation.

Stdlib-only. Env vars exist for tests and deployment config only;
production policy constants below change via PR (L033 precedent).
"""

import os
import sys

# ------------------------------------------------------------- constants
# Operator-set 2026-08-25 (ADR-0002 open item #2 ratified by acceptance).
FOREIGN_DEFAULT = "D:\\VOLTAGE"

# Jail arm switch + sanctioned-lane exemptions. Read fresh on every
# call so tests and task launchers can arm/disarm without reloads.
JAIL_ENV = "VOLTAGE_ROOT"
EXEMPT_ENV = "VOLTAGE_JAIL_EXEMPT"


class BoundaryViolation(PermissionError):
    """A lane tried to cross the isolation boundary. Fail loud."""

    def __init__(self, side, path, roots, op):
        self.side = side
        self.path = path
        self.roots = list(roots)
        self.op = op
        pretty = ", ".join(self.roots) if self.roots else "(none)"
        super().__init__(
            f"[{side}] {op} refused: {self.path!r} crosses the "
            f"isolation boundary (allowed: {pretty})")


# ------------------------------------------------------------ primitives
def normalize(path):
    """Absolute, backslash-normalized, case-folded path string."""
    return os.path.normpath(os.path.abspath(path)).lower()


def _under(path_norm, root_norm):
    return path_norm == root_norm or \
        path_norm.startswith(root_norm.rstrip("\\") + "\\")


# ----------------------------------------------------------------- side A
def foreign_roots():
    """Roots this fleet must never touch.

    Unarmed (Olympos posture): D:\\VOLTAGE. Armed (voltage posture):
    empty - the jail owns outbound exclusion, and home is not foreign
    to itself.
    """
    if jail_root():
        return []
    return [FOREIGN_DEFAULT]


def is_foreign(path, roots=None):
    """True iff path lives under one of `roots` (default: policy)."""
    if roots is None:
        roots = foreign_roots()
    p = normalize(path)
    return any(_under(p, normalize(r)) for r in roots)


def refuse_foreign(path, op="touch", roots=None):
    """Raise BoundaryViolation iff path is foreign territory."""
    if roots is None:
        roots = foreign_roots()
    if is_foreign(path, roots):
        raise BoundaryViolation("foreign-territory", path, roots, op)


# ----------------------------------------------------------------- side B
def jail_root():
    """Armed jail root, or None when the jail is inert."""
    env = os.environ.get(JAIL_ENV, "")
    return env.strip() or None


def exempt_roots():
    """Extra roots the armed jail permits (push lane declares these)."""
    raw = os.environ.get(EXEMPT_ENV, "")
    return [r for r in (s.strip() for s in raw.split(";")) if r]


def jail_check(path, op="write"):
    """Raise BoundaryViolation iff armed and path leaves the jail.

    Paths under an explicitly declared exempt root (the sanctioned
    mirror push lane) are allowed through; everything else outside
    the jail root fails loud.
    """
    root = jail_root()
    if root is None:
        return                    # inert posture: nothing to enforce
    p = normalize(path)
    if _under(p, normalize(root)):
        return
    for ex in exempt_roots():
        if _under(p, normalize(ex)):
            return
    raise BoundaryViolation(
        "path-jail", path, [root] + exempt_roots(), op)


# ------------------------------------------------------- dispatch seam
def guard_dispatch(path, op="write"):
    """The one call organs make at their path seams.

    Refuses foreign territory always (whichever side of the boundary
    this process sits on) and, when the jail is armed, refuses
    anything outside the jail as well. Inert on Olympos today.
    """
    refuse_foreign(path, op=op)
    jail_check(path, op=op)


# ------------------------------------------------------------------ CLI
def _policy_lines():
    root = jail_root()
    lines = ["boundary policy:"]
    if root:
        lines.append(f"  posture   : VOLTAGE (jail ARMED at {root})")
        ex = exempt_roots()
        lines.append("  exemptions: " + ("; ".join(ex) if ex
                                           else "(none declared)"))
    else:
        lines.append("  posture   : OLYMPOS (jail inert)")
        lines.append(f"  foreign   : {FOREIGN_DEFAULT} - any touch fails")
    lines.append("  authority : boundary.py (ADR-0002 isolation contract)")
    return lines


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("check", "jail", "policy",
                                   "foreign-root"):
        print(__doc__)
        return 1

    if argv[0] == "foreign-root":
        # Resolution seam for scripts: the one place allowed to speak
        # the literal (verify_boundary allowlist) so no other
        # executable ever has to hard-code it.
        print(FOREIGN_DEFAULT)
        return 0

    if argv[0] == "policy":
        print("\n".join(_policy_lines()))
        return 0

    mode = argv[0]
    targets = argv[1:]
    if not targets:
        print(f"usage: {mode} <path> [path...]")
        return 1

    bad = []
    for t in targets:
        try:
            if mode == "check":
                refuse_foreign(t, op="cli-check")
            else:
                jail_check(t, op="cli-check")
            print(f"ALLOWED  {t}")
        except BoundaryViolation as exc:
            bad.append(t)
            print(f"DENIED   {t}  ({exc})")
    if bad:
        print(f"[FAIL] {len(bad)} path(s) outside the "
              f"{'jail' if mode == 'jail' else 'allowed territory'}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
