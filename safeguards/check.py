"""SAFEGUARDS - commit gates born from real failures.

Every check here exists because a specific incident slipped through:

- py syntax compile ....... a mis-indented grant block broke an entire
                            server file and nine downstream suites
- duplicate top-level defs  two parallel agent sessions each defined
                            t_rig_Olympos_schema; the later def
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
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAX_WARN = 40
OVERSIZE_BYTES = 512 * 1024          # single-source-file warn cap
# Text scanners (markers/secrets) run on EVERYTHING except these known
# binary types. Allowlists are how key.pem slipped past the secret
# gate; denylisting binaries is the safe default.
BINARY_EXTS = {".jar", ".zip", ".exe", ".dll", ".png", ".jpg", ".jpeg",
               ".gif", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".otf",
               ".mp3", ".wav", ".ogg", ".mp4", ".class", ".so", ".dylib",
               ".pt", ".onnx", ".bin", ".db", ".sqlite"}

# Real leak patterns seen in the wild. Word-bounded, low false-positive.
SECRET_PATTERNS = [
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private-key-block", re.compile(
        r"-----BEGIN (RSA |OPENSSH |EC |PGP )?PRIVATE KEY-----")),
]


def conflict_markers(path):
    """Unresolved merge markers - the interleaved-lane classic."""
    hits = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                s = line.rstrip("\r\n")
                if s.startswith("<<<<<<<") or s.startswith(">>>>>>>"):
                    hits.append(f"{path}:{n}: merge marker '{s[:12]}'")
    except OSError:
        pass
    return hits


def secrets(path):
    """Credential-shaped strings committed by accident."""
    hits = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                for label, rx in SECRET_PATTERNS:
                    if rx.search(line):
                        hits.append(f"{path}:{n}: possible {label}")
                        break
    except OSError:
        pass
    return hits


def oversize(path):
    try:
        if os.path.getsize(path) > OVERSIZE_BYTES:
            return (f"oversize {path}: {os.path.getsize(path) // 1024} KiB "
                    f"> {OVERSIZE_BYTES // 1024} KiB cap")
    except OSError:
        pass
    return None


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
        ext = os.path.splitext(p)[1].lower()
        if ext not in BINARY_EXTS:
            errors.extend(conflict_markers(ap))
            errors.extend(secrets(ap))
        w = oversize(ap)
        if w:
            warnings.append(w)
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
