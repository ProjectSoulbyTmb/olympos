"""SECRETS hygiene gate: no credentials in tracked files, ever.

Complements verify_scope (retired-scope guard) with credential
patterns: cloud keys, provider tokens, private key blocks, generic
api_key/password assignments with long values.

High-precision patterns only - a gate that cries wolf gets ignored.
Allowlisted paths are skipped and reported (self by definition).

Run:  python verify_secrets.py
Exit: 0 clean, 1 findings.
"""

import re
import subprocess
import sys

PATTERNS = [
    ("aws-access-key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("anthropic-key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    ("openai-key", r"\bsk-proj-[A-Za-z0-9_\-]{20,}|\bsk-[A-Za-z0-9]{40,}\b"),
    ("github-token", r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    ("slack-token", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),
    ("private-key-block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("generic-secret-assign",
     r"(?i)\b(api[_-]?key|secret|password|passwd|token)"
     r"\b\s*[:=]\s*[\"'][A-Za-z0-9_\-/+=]{24,}[\"']"),
]

ALLOW = {
    "verify_secrets.py": "self: pattern definitions live here",
}


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True,
                         check=True).stdout
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def allow_reason(path):
    for prefix, reason in ALLOW.items():
        if path == prefix or path.startswith(prefix.rstrip("/\\") + "/"):
            return reason
    return None


def scan(paths):
    compiled = [(name, re.compile(rx)) for name, rx in PATTERNS]
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for no, line in enumerate(fh, start=1):
                    for name, rx in compiled:
                        if rx.search(line):
                            yield path, no, name, line.strip()
        except OSError:
            continue


def main():
    files = tracked_files()
    skipped = [(p, r) for p in files if (r := allow_reason(p))]
    scannable = [p for p in files if p not in {s for s, _ in skipped}]
    hits = list(scan(scannable))
    print("verify_secrets")
    for path, reason in skipped:
        print(f"  SKIP  {path:<44} {reason}")
    for path, no, kind, line in hits:
        shown = line[:80] + ("..." if len(line) > 80 else "")
        print(f"  FAIL  {path}:{no}: [{kind}] {shown}")
    verdict = "CLEAN" if not hits else f"{len(hits)} finding(s)"
    print(f"secrets: {len(scannable)} files scanned -> {verdict}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
