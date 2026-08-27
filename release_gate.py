"""Release engineering gate - tag-driven release validation.

Run before tagging a release:

    python release_gate.py v1.2.3

Checks:
1. VERSION file matches the tag
2. doctor --ci green
3. Changelog has an entry for this version
4. No uncommitted changes in tracked files

Exit 0 = release-ready. Exit 1 = gate failed.
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(HERE, "VERSION")
CHANGELOG_FILE = os.path.join(HERE, "CHANGELOG.md")


def check_version_match(tag):
    """VERSION file must match the tag (strip leading 'v')."""
    if not os.path.exists(VERSION_FILE):
        return False, "VERSION file missing"
    with open(VERSION_FILE, encoding="utf-8") as f:
        version = f.read().strip()
    expected = tag.lstrip("v")
    if version != expected:
        return False, f"VERSION={version} but tag={tag}"
    return True, f"VERSION={version} matches tag"


def check_changelog_entry(tag):
    """Changelog must have an entry for this version (if changelog exists)."""
    if not os.path.exists(CHANGELOG_FILE):
        return True, "no CHANGELOG.md (skipped)"
    with open(CHANGELOG_FILE, encoding="utf-8") as f:
        content = f.read()
    version = tag.lstrip("v")
    patterns = [
        rf"^## v?{re.escape(version)}\b",
        rf"^## {re.escape(version)}\b",
        rf"^# v?{re.escape(version)}\b",
    ]
    for pat in patterns:
        if re.search(pat, content, re.MULTILINE | re.IGNORECASE):
            return True, f"changelog has entry for {version}"
    return False, f"no changelog entry for {version}"


def check_clean_tree():
    """No uncommitted changes in tracked files."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=HERE, capture_output=True, text=True
    )
    dirty = [line for line in result.stdout.splitlines()
             if line and not line.startswith("??")]
    if dirty:
        return False, f"{len(dirty)} uncommitted change(s)"
    return True, "working tree clean"


def check_doctor_ci():
    """doctor --ci must be green."""
    result = subprocess.run(
        [sys.executable, "doctor.py", "--ci"],
        cwd=HERE, capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        tail = result.stdout.strip().splitlines()[-5:]
        return False, f"doctor --ci red: {'; '.join(tail)}"
    return True, "doctor --ci green"


def main():
    if len(sys.argv) < 2:
        print("usage: python release_gate.py <tag>", file=sys.stderr)
        print("example: python release_gate.py v1.2.3", file=sys.stderr)
        return 2

    tag = sys.argv[1]
    if not re.match(r"^v?\d+\.\d+\.\d+", tag):
        print(f"error: tag {tag!r} doesn't look like a version", file=sys.stderr)
        return 2

    print(f"== release gate for {tag} ==")
    checks = [
        ("version match", check_version_match(tag)),
        ("changelog entry", check_changelog_entry(tag)),
        ("clean tree", check_clean_tree()),
        ("doctor --ci", check_doctor_ci()),
    ]

    failed = []
    for name, (ok, detail) in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  {status:4s}  {name:<18s}  {detail}")
        if not ok:
            failed.append(name)

    print("-" * 50)
    if failed:
        print(f"RELEASE GATE RED: {len(failed)} check(s) failed")
        print(f"  failing: {', '.join(failed)}")
        return 1

    print("RELEASE GATE GREEN - ready to tag")
    print(f"  git tag -a {tag} -m 'release {tag}'")
    print(f"  git push origin {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
