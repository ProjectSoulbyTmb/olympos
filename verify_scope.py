"""SCOPE gate: retired-scope regression guard.

Yggdrasil is an autonomous open-source game and app development
platform (INTEGRATION.md section 0). Content derived from the retired
MMORPG sandbox is gone forever; this gate fails any tracked file that
reintroduces its naming, so it can never creep back through a merge,
a dependency, or a careless paste.

Scans git-tracked files only - generated or untracked artifacts are
the site policy's problem, not this gate's. Allowlisted paths are
skipped and reported with their reasons.

Run:  python verify_scope.py
Exit: 0 clean, 1 violations found.
"""

import re
import subprocess
import sys

# Retired-scope markers, matched case-insensitively anywhere in text.
PATTERNS = [
    r"osrs",
    r"runescape",
    r"rune\s?scape",
    r"old\s?school",
    r"jagex",
    r"hiscores?",
    r"\bge_?prices?\b",
    r"\brsps\b",
    r"muspelheim",
]

# path -> reason (prefix match). Skipped files are reported, not failed.
ALLOW = {
    "verify_scope.py": "self: pattern definitions live here",
    "INTEGRATION.md": "section 9 reconciliation manifest names retired paths",
}

_RX = re.compile("|".join(PATTERNS), re.IGNORECASE)


def tracked_files():
    # -c safe.directory=* keeps the gate working inside linked
    # worktrees whose metadata lives on ownership-blind filesystems.
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "ls-files", "-z"],
        capture_output=True, check=True).stdout
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def allow_reason(path):
    for prefix, reason in ALLOW.items():
        if path == prefix or path.startswith(prefix.rstrip("/\\") + "/"):
            return reason
    return None


def scan(paths):
    """Yield (path, line_no, line_text) for every pattern hit."""
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for no, line in enumerate(fh, start=1):
                    if _RX.search(line):
                        yield path, no, line.strip()
        except OSError:
            continue  # unreadable (deleted/locked): not a naming violation


def main():
    files = tracked_files()
    skipped = [(p, r) for p in files if (r := allow_reason(p))]
    scannable = [p for p in files if p not in {s for s, _ in skipped}]
    hits = list(scan(scannable))

    print("verify_scope")
    for path, reason in skipped:
        print(f"  SKIP  {path:<46} {reason}")
    for path, no, line in hits:
        print(f"  FAIL  {path}:{no}: {line[:100]}")
    verdict = "CLEAN" if not hits else f"{len(hits)} violation(s)"
    print(f"scope: {len(scannable)} files scanned, "
          f"{len(skipped)} allowlisted -> {verdict}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
