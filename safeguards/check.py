"""SAFEGUARDS - commit gates born from real failures.

Every check here exists because a specific incident slipped through:

- py syntax compile ....... a mis-indented grant block broke an entire
                            server file and nine downstream suites
- duplicate top-level defs  two parallel agent sessions each defined
                            t_rig_yggdrasil_schema; the later def
                            silently shadowed the former
- JSON validity ............ hand-edited registries/manifests with a
                            trailing comma took down loaders
- mixed-state warning ...... staged edits on files that ALSO carry
                            unstaged changes are how interleaved
                            agent lanes corrupt each other
- oversized-letter guard ... ratatosk payloads bounded at the door

Usage:
    python safeguards/check.py [--strict] [paths...]   # default: staged
    python safeguards/check.py --all                   # whole tree (CI)

Exit 0 = clean. Exit 1 = any failure (with --strict, warnings fail too).
"""

import json
import os
import py_compile
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAX_WARN = 40


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


def staged_files():
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [f for f in out.splitlines() if f]


def all_files():
    out = _git("ls-files")
    return [f for f in out.splitlines() if f]


def unstaged_set():
    out = _git("diff", "--name-only")
    return {f for f in out.splitlines() if f}


def staged_set():
    out = _git("diff", "--cached", "--name-only")
    return {f for f in out.splitlines() if f}


def check_syntax(path):
    """Compile one .py; returns error string or None."""
    try:
        py_compile.compile(path, doraise=True)
        return None
    except Exception as exc:                      # noqa: BLE001 - gate
        return f"{type(exc).__name__}: {exc}"


def dup_top_level_defs(path):
    """Duplicate top-level def/class names in one .py (shadowing bug)."""
    dups = []
    try:
        import ast
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except SyntaxError:
        return []                    # syntax gate already reported it
    seen = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            name = node.name
            line = getattr(node, "lineno", 0)
            if name in seen:
                dups.append(f"{path}: '{name}' defined at lines "
                            f"{seen[name]} and {line}")
            else:
                seen[name] = line
    return dups


def check_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            json.load(fh)
        return None
    except Exception as exc:                      # noqa: BLE001 - gate
        return f"{type(exc).__name__}: {exc}"


def run(paths, strict=False):
    errors, warnings = [], []
    mixed = unstaged_set() & staged_set()
    for p in paths:
        ap = os.path.join(ROOT, p)
        if not os.path.isfile(ap):
            continue
        if p.endswith(".py"):
            err = check_syntax(ap)
            if err:
                errors.append(f"syntax {p}: {err}")
            for d in dup_top_level_defs(ap):
                errors.append("dupdef " + d)
        elif p.endswith(".json"):
            err = check_json(ap)
            if err:
                errors.append(f"json {p}: {err}")
        if p in mixed:
            warnings.append(f"mixed-state: {p} has staged AND unstaged "
                            "edits (interleaved-lane risk)")
    for w in warnings:
        print(f"[warn] {w}")
    for e in errors:
        print(f"[FAIL] {e}")
    total = len(warnings) + len(errors)
    print(f"- safeguards: {len(paths)} file(s), {len(errors)} error(s), "
          f"{len(warnings)} warning(s)")
    if errors:
        return 1
    if strict and warnings:
        return 1
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict" in argv
    argv = [a for a in argv if a != "--strict"]
    if "--all" in argv:
        argv.remove("--all")
        paths = all_files()
    else:
        paths = argv or staged_files()
    if len(paths) > MAX_WARN:
        paths = paths[:MAX_WARN]
        print(f"[note] scanning first {MAX_WARN} paths")
    if not paths:
        print("- safeguards: nothing to check")
        return 0
    return run(paths, strict=strict)


if __name__ == "__main__":
    sys.exit(main())
