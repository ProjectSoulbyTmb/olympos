"""REPO HEALTH guard: structural integrity across the fleet.

Born from real drift: worktree artifacts piling up, uncommitted changes
silently accumulating, fleet.json diverging from disk reality, config
files going corrupt. Every check exists because it bit us once.

Checks:
  1. git-drift ......... uncommitted/untracked files in core repos
  2. worktree-artifacts  orphaned poseidon-gate-*, hypnos-v-*, etc.
  3. fleet-consistency   fleet.json realms match actual directories
  4. registry-sync ...... registry.json entries match fleet.json
  5. config-integrity    required files present and valid JSON
  6. split-brain ........ repos outside D:\\ policy
  7. large-untracked .... untracked files > 10 MiB (leak risk)
  8. stale-tmp ......... .tmp files left by runtime processes
  9. detached-head ..... repos in detached HEAD state

Run:     python verify_repo_health.py
Auto-fix: python verify_repo_health.py --fix
JSON:    python verify_repo_health.py --json
Exit:    0 healthy, 1 issues found.
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
D_DRIVE = os.path.dirname(ROOT)

# --- configuration ---

CORE_REPOS = [
    ROOT,
    os.path.join(D_DRIVE, "olympos"),
    os.path.join(D_DRIVE, "project-soul"),
    os.path.join(D_DRIVE, "riley"),
    os.path.join(D_DRIVE, "aphrodite"),
]

REQUIRED_FILES = [
    "fleet.json",
    os.path.join("realms", "registry.json"),
    "DESIGN.md",
    "INTEGRATION.md",
    "FLOW.md",
    "AGENTS.md",
]

REQUIRED_JSON = [
    "fleet.json",
    os.path.join("realms", "registry.json"),
]

WORKTREE_ARTIFACT_PREFIXES = [
    "poseidon-gate-",
    "hypnos-v-",
    "hebe-gate-",
    "norn-vulcan-",
    "norn-zeus-",
    "ptah-agent-",
    "relay-verify-",
]

LARGE_UNTRACKED_BYTES = 10 * 1024 * 1024  # 10 MiB

# --- helpers ---


def _git(cwd, *args):
    """Run git in cwd, return stdout (stripped). Returns '' on failure."""
    try:
        proc = subprocess.run(
            ["git", "-c", "safe.directory=*", *args],
            cwd=cwd, capture_output=True, text=True, timeout=15)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _git_lines(cwd, *args):
    out = _git(cwd, *args)
    return [l for l in out.splitlines() if l]


def _is_git_repo(path):
    return os.path.isdir(os.path.join(path, ".git"))


def _human_size(nbytes):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if nbytes < 1024:
            return f"{nbytes:.0f}{unit}"
        nbytes /= 1024
    return f"{nbytes:.0f}TiB"


# --- checks ---


def check_git_drift():
    """Detect uncommitted and untracked files in core repos."""
    findings = []
    for repo in CORE_REPOS:
        if not _is_git_repo(repo):
            findings.append(f"not a git repo: {repo}")
            continue
        name = os.path.basename(repo)
        modified = _git_lines(repo, "diff", "--name-only")
        staged = _git_lines(repo, "diff", "--cached", "--name-only")
        untracked = _git_lines(repo, "ls-files", "--others", "--exclude-standard")
        if modified:
            findings.append(
                f"{name}: {len(modified)} unstaged change(s): "
                + ", ".join(modified[:5])
                + ("..." if len(modified) > 5 else ""))
        if staged:
            findings.append(
                f"{name}: {len(staged)} staged change(s): "
                + ", ".join(staged[:5])
                + ("..." if len(staged) > 5 else ""))
        if untracked:
            # filter out known worktree artifacts
            real = [u for u in untracked
                    if not any(u.startswith(p)
                               for p in WORKTREE_ARTIFACT_PREFIXES)]
            if real:
                findings.append(
                    f"{name}: {len(real)} untracked file(s): "
                    + ", ".join(real[:5])
                    + ("..." if len(real) > 5 else ""))
    return findings


def check_worktree_artifacts():
    """Detect orphaned worktree artifact directories."""
    findings = []
    for repo in CORE_REPOS:
        if not _is_git_repo(repo):
            continue
        name = os.path.basename(repo)
        try:
            entries = os.listdir(repo)
        except OSError:
            continue
        artifacts = []
        for entry in entries:
            for prefix in WORKTREE_ARTIFACT_PREFIXES:
                if entry.startswith(prefix):
                    artifacts.append(entry)
                    break
        if artifacts:
            findings.append(
                f"{name}: {len(artifacts)} worktree artifact(s): "
                + ", ".join(artifacts[:5])
                + ("..." if len(artifacts) > 5 else ""))
    return findings


def check_fleet_consistency():
    """Verify fleet.json realms have matching directories on disk."""
    findings = []
    fleet_path = os.path.join(ROOT, "fleet.json")
    try:
        with open(fleet_path, encoding="utf-8") as fh:
            fleet = json.load(fh)
    except (OSError, ValueError) as exc:
        findings.append(f"fleet.json unreadable: {exc}")
        return findings

    for realm in fleet.get("realms", []):
        name = realm.get("name", "?")
        path = realm.get("path", "")
        if not path:
            continue
        # absolute paths (external repos) used as-is; relative joined with ROOT
        if os.path.isabs(path):
            full = path.rstrip("/").rstrip("\\")
        else:
            full = os.path.join(ROOT, path.rstrip("/").rstrip("\\"))
        if not os.path.exists(full):
            findings.append(f"fleet realm '{name}' missing on disk: {path}")
        elif realm.get("verify"):
            verify_cmd = realm["verify"]
            if isinstance(verify_cmd, list) and len(verify_cmd) >= 2:
                # skip file check for package-manager commands (npm test, etc.)
                if verify_cmd[0] not in ("npm", "node", "npx"):
                    verify_file = verify_cmd[-1]
                    if os.path.isabs(verify_file):
                        verify_path = verify_file
                    elif os.path.isabs(path):
                        # external repo: verify script relative to repo dir
                        verify_path = os.path.join(full, verify_file)
                    else:
                        verify_path = os.path.join(ROOT, verify_file)
                    if not os.path.isfile(verify_path):
                        findings.append(
                            f"fleet realm '{name}' verify missing: {verify_file}")

    for sat in fleet.get("satellites", []):
        name = sat.get("name", "?")
        path = sat.get("path", "")
        if not path:
            continue
        if os.path.isabs(path):
            full = path.rstrip("/").rstrip("\\")
        else:
            full = os.path.join(ROOT, path.rstrip("/").rstrip("\\"))
        if not os.path.exists(full):
            findings.append(
                f"fleet satellite '{name}' missing on disk: {path}")

    return findings


def check_registry_sync():
    """Verify registry.json entries are consistent with fleet.json."""
    findings = []
    fleet_path = os.path.join(ROOT, "fleet.json")
    registry_path = os.path.join(ROOT, "realms", "registry.json")
    try:
        with open(fleet_path, encoding="utf-8") as fh:
            fleet = json.load(fh)
        with open(registry_path, encoding="utf-8") as fh:
            registry = json.load(fh)
    except (OSError, ValueError) as exc:
        findings.append(f"config unreadable: {exc}")
        return findings

    fleet_names = {r["name"] for r in fleet.get("realms", [])}
    reg_names = {r["name"] for r in registry.get("realms", [])}

    in_registry_not_fleet = reg_names - fleet_names
    in_fleet_not_registry = fleet_names - reg_names

    for name in sorted(in_registry_not_fleet):
        findings.append(f"registry has '{name}' but fleet.json does not")
    for name in sorted(in_fleet_not_registry):
        findings.append(f"fleet.json has '{name}' but registry does not")

    # check for duplicate ports in registry
    ports_seen = {}
    for realm in registry.get("realms", []):
        port = realm.get("port")
        if port:
            if port in ports_seen:
                findings.append(
                    f"port {port} claimed by both "
                    f"'{ports_seen[port]}' and '{realm['name']}'")
            ports_seen[port] = realm["name"]

    return findings


def check_config_integrity():
    """Verify required files exist and JSON configs parse."""
    findings = []
    for rel in REQUIRED_FILES:
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            findings.append(f"missing required file: {rel}")

    for rel in REQUIRED_JSON:
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8") as fh:
                json.load(fh)
        except (ValueError, OSError) as exc:
            findings.append(f"invalid JSON {rel}: {exc}")

    return findings


def check_split_brain():
    """Detect repos outside D:\\ policy (report only, not blocking)."""
    findings = []
    try:
        from safeguards.repo_home_guard import find_repos, is_allowed
    except ImportError:
        # fallback: inline check
        def is_allowed(path):
            return os.path.normcase(os.path.normpath(path)).startswith(
                os.path.normcase(os.path.normpath(D_DRIVE)))
        def find_repos(root, maxdepth=3):
            return []  # skip if module unavailable

    # known frozen exceptions
    frozen = {
        os.path.normcase(os.path.normpath(
            os.path.join(os.environ.get("USERPROFILE", ""),
                         "OneDrive", "Documents", "Default Project"))),
    }

    # check common locations outside D:\
    check_roots = []
    userprofile = os.environ.get("USERPROFILE", "")
    if userprofile:
        for subdir in ("Projects", "Documents", "Desktop"):
            p = os.path.join(userprofile, subdir)
            if os.path.isdir(p):
                check_roots.append(p)

    for root in check_roots:
        for repo_dir in find_repos(root, maxdepth=2):
            normed = os.path.normcase(os.path.normpath(repo_dir))
            if normed in frozen:
                continue
            if not is_allowed(repo_dir):
                findings.append(f"repo outside D:\\ policy: {repo_dir}")

    return findings


def check_large_untracked():
    """Detect large untracked files that may be accidental leaks."""
    findings = []
    for repo in CORE_REPOS:
        if not _is_git_repo(repo):
            continue
        name = os.path.basename(repo)
        untracked = _git_lines(repo, "ls-files", "--others",
                               "--exclude-standard")
        for rel in untracked:
            full = os.path.join(repo, rel)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > LARGE_UNTRACKED_BYTES:
                findings.append(
                    f"{name}: large untracked {rel} ({_human_size(size)})")
    return findings


def check_stale_tmp():
    """Detect .tmp files left behind by runtime processes."""
    findings = []
    stale_patterns = ["*.tmp", "*.json.tmp"]
    for repo in CORE_REPOS:
        if not _is_git_repo(repo):
            continue
        name = os.path.basename(repo)
        untracked = _git_lines(repo, "ls-files", "--others",
                               "--exclude-standard")
        tmps = [u for u in untracked if u.endswith(".tmp")]
        if tmps:
            findings.append(
                f"{name}: {len(tmps)} stale .tmp file(s): "
                + ", ".join(tmps[:5])
                + ("..." if len(tmps) > 5 else ""))
    return findings


def check_detached_head():
    """Detect repos in detached HEAD state."""
    findings = []
    for repo in CORE_REPOS:
        if not _is_git_repo(repo):
            continue
        name = os.path.basename(repo)
        head = _git(repo, "symbolic-ref", "-q", "HEAD")
        if not head:
            findings.append(f"{name}: detached HEAD")
    return findings


# --- auto-repair ---


def repair_worktree_artifacts():
    """Remove orphaned worktree artifact directories."""
    import shutil
    removed = 0
    for repo in CORE_REPOS:
        if not _is_git_repo(repo):
            continue
        try:
            entries = os.listdir(repo)
        except OSError:
            continue
        for entry in entries:
            for prefix in WORKTREE_ARTIFACT_PREFIXES:
                if entry.startswith(prefix):
                    target = os.path.join(repo, entry)
                    try:
                        shutil.rmtree(target)
                        removed += 1
                        print(f"  [FIXED] removed {entry}")
                    except OSError as exc:
                        print(f"  [WARN] failed to remove {entry}: {exc}")
                    break
    return removed


def repair_stale_tmp():
    """Remove stale .tmp files from tracked repos."""
    removed = 0
    for repo in CORE_REPOS:
        if not _is_git_repo(repo):
            continue
        untracked = _git_lines(repo, "ls-files", "--others",
                               "--exclude-standard")
        for rel in untracked:
            if rel.endswith(".tmp"):
                full = os.path.join(repo, rel)
                try:
                    os.remove(full)
                    removed += 1
                    print(f"  [FIXED] removed {rel}")
                except OSError as exc:
                    print(f"  [WARN] failed to remove {rel}: {exc}")
    return removed


REPAIRS = {
    "worktree-artifacts": repair_worktree_artifacts,
    "stale-tmp": repair_stale_tmp,
}


# --- orchestration ---


ALL_CHECKS = [
    ("git-drift", check_git_drift),
    ("worktree-artifacts", check_worktree_artifacts),
    ("fleet-consistency", check_fleet_consistency),
    ("registry-sync", check_registry_sync),
    ("config-integrity", check_config_integrity),
    ("split-brain", check_split_brain),
    ("large-untracked", check_large_untracked),
    ("stale-tmp", check_stale_tmp),
    ("detached-head", check_detached_head),
]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="REPO HEALTH GUARD")
    parser.add_argument("--fix", action="store_true",
                        help="auto-repair safe issues (worktree artifacts, stale tmp)")
    parser.add_argument("--json", action="store_true",
                        help="output results as JSON")
    args = parser.parse_args()

    if not args.json:
        print("=" * 64)
        print("REPO HEALTH GUARD")
        print("=" * 64)
    t0 = time.time()
    total_findings = []
    results = {}
    for name, check_fn in ALL_CHECKS:
        try:
            findings = check_fn()
        except Exception as exc:
            findings = [f"{name} check crashed: {exc}"]
        results[name] = findings
        if findings:
            if not args.json:
                for f in findings:
                    print(f"  [FAIL]  {name:<24} {f}")
            total_findings.extend(findings)
        else:
            if not args.json:
                print(f"  [PASS]  {name:<24} clean")

    # auto-repair pass
    if args.fix and total_findings:
        if not args.json:
            print("-" * 64)
            print("AUTO-REPAIR")
        failing_names = {name for name, findings in results.items() if findings}
        for check_name, repair_fn in REPAIRS.items():
            if check_name in failing_names:
                repair_fn()

    elapsed = time.time() - t0
    if args.json:
        import json as _json
        output = {
            "checks": results,
            "total_findings": len(total_findings),
            "healthy": len(total_findings) == 0,
            "elapsed_s": round(elapsed, 1),
        }
        print(_json.dumps(output, indent=2))
    else:
        print("-" * 64)
        verdict = "HEALTHY" if not total_findings else \
                  f"{len(total_findings)} issue(s)"
        print(f"{elapsed:.1f}s - {len(ALL_CHECKS)} checks -> {verdict}")
    return 1 if total_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
