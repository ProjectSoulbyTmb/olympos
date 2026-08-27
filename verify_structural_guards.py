"""Structural guards verification: proves repo_health catches real issues.

Throwaway fixtures, no live machine state. Each test constructs a
minimal filesystem or git repo, runs the check, and asserts the
expected findings.

Run:  python verify_structural_guards.py
Exit: 0 all green, 1 failure.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import verify_repo_health as health

PASS = 0
FAIL = 0


def _assert(condition, label):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}")


def _make_git_repo(path):
    """Initialize a minimal git repo at path."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True,
                   check=True)
    subprocess.run(["git", "config", "user.email", "test@test"],
                   cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "test"],
                   cwd=path, capture_output=True, check=True)


# --- fixture tests ---


def test_config_integrity_required_files():
    """Missing required files are detected."""
    with tempfile.TemporaryDirectory() as tmp:
        old_root = health.ROOT
        health.ROOT = tmp
        try:
            findings = health.check_config_integrity()
            _assert(len(findings) >= 6,
                    "config-integrity: detects all missing required files")
            _assert(any("fleet.json" in f for f in findings),
                    "config-integrity: flags missing fleet.json")
        finally:
            health.ROOT = old_root


def test_config_integrity_valid_json():
    """Valid JSON files pass cleanly."""
    with tempfile.TemporaryDirectory() as tmp:
        # create all required files
        for rel in health.REQUIRED_FILES:
            full = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as fh:
                fh.write("{}" if rel.endswith(".json") else "# doc")
        old_root = health.ROOT
        health.ROOT = tmp
        try:
            findings = health.check_config_integrity()
            _assert(len(findings) == 0,
                    "config-integrity: valid files pass clean")
        finally:
            health.ROOT = old_root


def test_config_integrity_corrupt_json():
    """Corrupt JSON is detected."""
    with tempfile.TemporaryDirectory() as tmp:
        for rel in health.REQUIRED_FILES:
            full = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as fh:
                fh.write("{invalid}" if rel.endswith(".json") else "# doc")
        old_root = health.ROOT
        health.ROOT = tmp
        try:
            findings = health.check_config_integrity()
            json_errors = [f for f in findings if "invalid JSON" in f]
            _assert(len(json_errors) >= 1,
                    "config-integrity: corrupt JSON detected")
        finally:
            health.ROOT = old_root


def test_fleet_consistency_missing_dirs():
    """Fleet realms pointing to missing directories are flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        fleet = {
            "realms": [
                {"name": "exists", "path": "exists"},
                {"name": "missing", "path": "no-such-dir"},
            ],
            "satellites": [
                {"name": "sat-miss", "path": "also-missing"},
            ]
        }
        with open(os.path.join(tmp, "fleet.json"), "w") as fh:
            json.dump(fleet, fh)
        os.makedirs(os.path.join(tmp, "exists"))
        old_root = health.ROOT
        health.ROOT = tmp
        try:
            findings = health.check_fleet_consistency()
            _assert(any("missing" in f and "missing on disk" in f
                        for f in findings),
                    "fleet-consistency: missing realm dir detected")
            _assert(any("sat-miss" in f for f in findings),
                    "fleet-consistency: missing satellite dir detected")
        finally:
            health.ROOT = old_root


def test_fleet_consistency_all_present():
    """All fleet dirs present = clean."""
    with tempfile.TemporaryDirectory() as tmp:
        fleet = {
            "realms": [{"name": "a", "path": "a"}],
            "satellites": []
        }
        with open(os.path.join(tmp, "fleet.json"), "w") as fh:
            json.dump(fleet, fh)
        os.makedirs(os.path.join(tmp, "a"))
        old_root = health.ROOT
        health.ROOT = tmp
        try:
            findings = health.check_fleet_consistency()
            _assert(len(findings) == 0,
                    "fleet-consistency: all present passes clean")
        finally:
            health.ROOT = old_root


def test_registry_sync_mismatch():
    """Registry/fleet.json name mismatches are detected."""
    with tempfile.TemporaryDirectory() as tmp:
        fleet = {"realms": [{"name": "alpha"}], "satellites": []}
        registry = {"realms": [{"name": "beta"}]}
        os.makedirs(os.path.join(tmp, "realms"))
        with open(os.path.join(tmp, "fleet.json"), "w") as fh:
            json.dump(fleet, fh)
        with open(os.path.join(tmp, "realms", "registry.json"), "w") as fh:
            json.dump(registry, fh)
        old_root = health.ROOT
        health.ROOT = tmp
        try:
            findings = health.check_registry_sync()
            _assert(any("alpha" in f for f in findings),
                    "registry-sync: fleet-only realm detected")
            _assert(any("beta" in f for f in findings),
                    "registry-sync: registry-only realm detected")
        finally:
            health.ROOT = old_root


def test_registry_sync_duplicate_ports():
    """Duplicate port claims are detected."""
    with tempfile.TemporaryDirectory() as tmp:
        fleet = {"realms": [{"name": "a"}, {"name": "b"}], "satellites": []}
        registry = {"realms": [
            {"name": "a", "port": 9999},
            {"name": "b", "port": 9999},
        ]}
        os.makedirs(os.path.join(tmp, "realms"))
        with open(os.path.join(tmp, "fleet.json"), "w") as fh:
            json.dump(fleet, fh)
        with open(os.path.join(tmp, "realms", "registry.json"), "w") as fh:
            json.dump(registry, fh)
        old_root = health.ROOT
        health.ROOT = tmp
        try:
            findings = health.check_registry_sync()
            _assert(any("port 9999" in f for f in findings),
                    "registry-sync: duplicate port detected")
        finally:
            health.ROOT = old_root


def test_git_drift_clean_repo():
    """A clean repo produces no drift findings."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_git_repo(tmp)
        # commit a file so the repo has a HEAD
        with open(os.path.join(tmp, "test.txt"), "w") as fh:
            fh.write("hello")
        subprocess.run(["git", "add", "test.txt"], cwd=tmp,
                       capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp,
                       capture_output=True)
        old_repos = health.CORE_REPOS
        health.CORE_REPOS = [tmp]
        try:
            findings = health.check_git_drift()
            _assert(len(findings) == 0,
                    "git-drift: clean repo passes")
        finally:
            health.CORE_REPOS = old_repos


def test_git_drift_modified_file():
    """Modified files are detected."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_git_repo(tmp)
        with open(os.path.join(tmp, "test.txt"), "w") as fh:
            fh.write("hello")
        subprocess.run(["git", "add", "test.txt"], cwd=tmp,
                       capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp,
                       capture_output=True)
        # modify the file
        with open(os.path.join(tmp, "test.txt"), "w") as fh:
            fh.write("changed")
        old_repos = health.CORE_REPOS
        health.CORE_REPOS = [tmp]
        try:
            findings = health.check_git_drift()
            _assert(any("unstaged" in f for f in findings),
                    "git-drift: modified file detected")
        finally:
            health.CORE_REPOS = old_repos


def test_worktree_artifacts_detected():
    """Orphaned worktree artifact dirs are flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_git_repo(tmp)
        os.makedirs(os.path.join(tmp, "poseidon-gate-abc123"))
        os.makedirs(os.path.join(tmp, "hypnos-v-xyz789"))
        os.makedirs(os.path.join(tmp, "normal-dir"))
        old_repos = health.CORE_REPOS
        health.CORE_REPOS = [tmp]
        try:
            findings = health.check_worktree_artifacts()
            _assert(len(findings) == 1,
                    "worktree-artifacts: artifacts detected in one repo")
            _assert("poseidon-gate-abc123" in findings[0],
                    "worktree-artifacts: specific artifact named")
        finally:
            health.CORE_REPOS = old_repos


def test_large_untracked_detected():
    """Large untracked files are flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_git_repo(tmp)
        big = os.path.join(tmp, "big.bin")
        with open(big, "wb") as fh:
            fh.write(b"\0" * (11 * 1024 * 1024))  # 11 MiB
        old_repos = health.CORE_REPOS
        health.CORE_REPOS = [tmp]
        try:
            findings = health.check_large_untracked()
            _assert(any("big.bin" in f for f in findings),
                    "large-untracked: big file detected")
        finally:
            health.CORE_REPOS = old_repos


def test_human_size():
    """Size formatting works."""
    _assert(health._human_size(0) == "0B", "human-size: 0B")
    _assert(health._human_size(1024) == "1KiB", "human-size: 1KiB")
    _assert(health._human_size(10 * 1024 * 1024) == "10MiB",
            "human-size: 10MiB")


# --- main ---


def main():
    print("=" * 64)
    print("STRUCTURAL GUARDS VERIFICATION")
    print("=" * 64)

    test_config_integrity_required_files()
    test_config_integrity_valid_json()
    test_config_integrity_corrupt_json()
    test_fleet_consistency_missing_dirs()
    test_fleet_consistency_all_present()
    test_registry_sync_mismatch()
    test_registry_sync_duplicate_ports()
    test_git_drift_clean_repo()
    test_git_drift_modified_file()
    test_worktree_artifacts_detected()
    test_large_untracked_detected()
    test_human_size()

    print("-" * 64)
    print(f"{PASS + FAIL} tests: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
