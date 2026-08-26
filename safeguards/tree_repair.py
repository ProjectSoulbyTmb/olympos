r"""TREE REPAIR - automatic detection + safe repair of git-tree damage.

Born from incidents on 2026-08-24/25: stale ref locks blocked every
fetch, a killed pull left an index half-advanced past HEAD, a lane
branch carried squash-duplicates of already-merged PRs, and ~70
tracked files went missing from a worktree disk after a ref-only
move. Each of those cost a debugging session; this module turns the
rescues into one command.

Philosophy (rule 9): quarantine, never destroy. Every repair is
mechanical, evidence-checked, logged to a hash-chained ledger, and
refuses to touch anything a live writer may be holding.

Detectors and what --fix does:

    stale-locks         *.lock under .git with no live git process and
                        age > grace        -> remove the lock file
    missing-tracked     tracked files absent from disk whose last write
                        predates the protect window -> checkout HEAD
    generated-dirt      known-generated paths modified -> checkout HEAD
    duplicate-branch    local auto/* branch whose unique commits are all
                        patch-id-equivalent upstream -> move ref to
                        origin/main (zero content change)
    worktree-gone       admin entries for deleted worktrees -> prune
    interrupted-op      MERGE_HEAD / rebase dirs in progress -> REPORT
                        ONLY (aborting is a judgment call)
    split-brain         repos outside the D:\ policy -> REPORT ONLY,
                        via safeguards/repo_home_guard.py

Usage:
    python safeguards/tree_repair.py [--root D:\THOTH] [--fix] [--json]
                                     [--protect-minutes 30]

Exit 0 = clean or all found issues repaired; exit 1 = issues remain
that need human judgment (or repairs failed).
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


LOCK_GRACE_S = 60.0

# Generated artifacts: safe to reset because their engine regenerates
# them from tracked sources (knowledge engine self-invalidates).
GENERATED_PATHS = ("knowledge/.index.json",)


def _git(root, *args):
    """Run git in root; return stdout or None on failure."""
    try:
        r = subprocess.run(["git", "-C", root, *args],
                           capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git_live_processes():
    """Best-effort count of running git.exe processes (Windows-aware)."""
    n = 0
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        arr = (ctypes.c_ulong * 4096)()
        needed = ctypes.c_ulong()
        if k32.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr),
                             ctypes.byref(needed)):
            import ctypes.wintypes as wt
            for pid in arr[: needed.value // ctypes.sizeof(ctypes.c_ulong)]:
                if not pid:
                    continue
                h = k32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED
                if h:
                    exe = ctypes.create_unicode_buffer(260)
                    size = wt.DWORD(260)
                    if k32.QueryFullProcessImageNameW(h, 0, exe,
                                                      ctypes.byref(size)):
                        if exe.value.lower().endswith("\\git.exe"):
                            n += 1
                    k32.CloseHandle(h)
    except Exception:                       # noqa: BLE001 - probe only
        pass
    return n


# ------------------------------------------------------------------ ledger

def ledger_path(root):
    """Each repo keeps its OWN repair history - a mirror must never
    inherit fixture or foreign-repo entries."""
    return os.path.join(root, "data", "tree_repair.jsonl")


def _ledger_append(root, entry):
    path = ledger_path(root)
    prev = "genesis"
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    prev = json.loads(line).get("sha", prev)
    except OSError:
        pass
    entry["prev"] = prev
    body = json.dumps(entry, sort_keys=True).encode("utf-8")
    entry["sha"] = hashlib.sha256(body).hexdigest()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def ledger_verify(root):
    """Recompute the chain; return (ok, count)."""
    path = ledger_path(root)
    prev = "genesis"
    count = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line)
                sha = e.pop("sha", "")
                if hashlib.sha256(
                        json.dumps(e, sort_keys=True)
                        .encode("utf-8")).hexdigest() != sha:
                    return False, count
                if e.get("prev") != prev:
                    return False, count
                prev = sha
                count += 1
        return True, count
    except OSError:
        return True, 0                      # empty ledger is valid


# --------------------------------------------------------------- detectors

def find_stale_locks(root):
    """Lock files in their KNOWN homes - never a full .git walk
    (objects/ has thousands of fan-out dirs; USB drives turn that
    into minutes of crawling for zero extra coverage):
      <gitdir>/*.lock, refs/**.lock, worktrees/*/...lock"""
    hits = []
    gitdir = os.path.join(root, ".git")
    if os.path.isfile(gitdir):              # worktree: points at main .git
        try:
            with open(gitdir, encoding="utf-8") as fh:
                linked = fh.read().split("gitdir:", 1)[1].strip()
                gitdir = os.path.join(root, linked)
        except OSError:
            return hits
    now = time.time()

    def scan_dir(d):
        try:
            for f in os.listdir(d):
                p = os.path.join(d, f)
                if os.path.isdir(p):
                    if f != "objects":       # refs/ nests; objects/ doesn't
                        scan_dir(p)
                elif f.endswith(".lock"):
                    try:
                        age = now - os.path.getmtime(p)
                    except OSError:
                        continue
                    hits.append({"path": p, "age_s": round(age, 1)})
        except OSError:
            pass

    scan_dir(gitdir)
    return hits


def fix_stale_locks(root, findings, live_git_procs):
    fixed = []
    for hit in findings:
        if live_git_procs:
            break                           # never race a live git
        if hit["age_s"] < LOCK_GRACE_S:
            continue                        # too fresh - could be active
        try:
            os.remove(hit["path"])
            fixed.append(hit["path"])
        except OSError:
            pass
    return fixed


def find_missing_tracked(root, protect_minutes):
    """Tracked files absent from disk (unstaged deletions)."""
    out = []
    names = _git(root, "diff", "--name-only", "--diff-filter=D")
    if not names:
        return out
    protect_s = float(protect_minutes) * 60.0
    for rel in names.splitlines():
        if not rel.strip():
            continue
        out.append({"path": rel, "_protect_s": protect_s})
    return out


def fix_missing_tracked(root, findings):
    fixed = []
    for f in findings:
        target = os.path.join(root, f["path"])
        # live-writer signal: a RECENTLY WRITTEN SIBLING means someone
        # is working in this directory right now. The deleted file's
        # own absence bumps the dir mtime, so the directory itself
        # proves nothing (rule 9: quarantine, not destroy)
        parent = os.path.dirname(target) or root
        cutoff = time.time() - f["_protect_s"]
        try:
            for entry in os.scandir(parent):
                try:
                    if entry.is_file() and entry.stat().st_mtime > cutoff:
                        f["skipped_hot_dir"] = True
                        break
                except OSError:
                    continue
            if f.get("skipped_hot_dir"):
                continue
        except OSError:
            pass
        if _git(root, "checkout", "HEAD", "--", f["path"]) is not None:
            fixed.append(f["path"])
    return fixed


def find_generated_dirt(root):
    out = []
    for g in GENERATED_PATHS:
        dirty = _git(root, "diff", "--name-only", "--", g)
        if dirty and g in dirty.splitlines():
            out.append({"path": g})
    return out


def fix_generated_dirt(root, findings):
    fixed = []
    for f in findings:
        if _git(root, "checkout", "HEAD", "--", f["path"]) is not None:
            fixed.append(f["path"])
    return fixed


def find_duplicate_branches(root):
    """auto/* branches whose unique commits are all patch-equivalent
    upstream - squash-merge residue, zero unique content."""
    out = []
    if _git(root, "rev-parse", "--verify", "origin/main") is None:
        return out
    for b in (_git(root, "for-each-ref", "--format=%(refname:short)",
                   "refs/heads/") or "").splitlines():
        if not b.startswith("auto/"):
            continue
        cherry = _git(root, "cherry", "origin/main", b) or ""
        marks = [ln[:1] for ln in cherry.splitlines() if ln.strip()]
        if marks and all(m == "-" for m in marks):
            out.append({"branch": b,
                        "duplicate_commits": len(marks)})
    return out


def fix_duplicate_branches(root, findings):
    fixed = []
    for f in findings:
        target = _git(root, "rev-parse", "origin/main")
        if target and _git(root, "update-ref",
                           f"refs/heads/{f['branch']}",
                           target.strip()) is not None:
            fixed.append(f["branch"])
    return fixed


def find_stale_worktrees(root):
    out = []
    listing = _git(root, "worktree", "list", "--porcelain") or ""
    for block in listing.split("\n\n"):
        lines = block.splitlines()
        path = next((l[9:] for l in lines if l.startswith("worktree ")),
                    None)
        detached = any(l.startswith("detached") for l in lines)
        if path and detached and not os.path.isdir(path):
            out.append({"path": path})
    return out


def find_interrupted_ops(root):
    ops = []
    gd = os.path.join(root, ".git")
    if os.path.isfile(gd):
        return ops                          # worktrees: report at mirror
    for marker, name in (("MERGE_HEAD", "merge"),
                         ("rebase-merge", "rebase-merge"),
                         ("rebase-apply", "rebase-apply")):
        if os.path.exists(os.path.join(gd, marker)):
            ops.append({"op": name})
    return ops


def find_split_brain(report_only=True):
    try:
        from safeguards.repo_home_guard import default_probe_roots, \
            find_repos, is_allowed
    except Exception as exc:                # noqa: BLE001 - optional dep
        return [{"error": str(exc)}]
    out = []
    for probe in default_probe_roots():
        for repo in find_repos(probe):
            if not is_allowed(repo):
                out.append({"repo": repo, "policy": "D:\\"})
    return out


# -------------------------------------------------------------------- main

def sweep(root, fix=False, protect_minutes=30, include_machine=True):
    findings = []
    actions = []

    def record(detector, items, fixed=None):
        entry = {"detector": detector, "found": len(items),
                 "items": items}
        if fixed is not None:
            entry["fixed"] = fixed
        findings.append(entry)

    locks = find_stale_locks(root)
    if locks:
        fixed = fix_stale_locks(root, locks, _git_live_processes()) \
            if fix else None
        record("stale-locks", locks, fixed)
        if fixed:
            actions.append({"repair": "stale-locks", "count": len(fixed)})
        locks = [l for l in locks if l["path"] not in (fixed or [])]
        for p in fixed:
            _ledger_append(root, {"t": time.time(),
                                  "repair": "stale-locks", "path": p})

    miss = find_missing_tracked(root, protect_minutes)
    if miss:
        fixed = fix_missing_tracked(root, miss) if fix else None
        record("missing-tracked", miss, fixed)
        if fixed:
            actions.append({"repair": "missing-tracked",
                            "count": len(fixed)})
        miss = [m for m in miss if m["path"] not in (fixed or [])]
        for p in fixed:
            _ledger_append(root, {"t": time.time(),
                                  "repair": "missing-tracked", "path": p})

    gen = find_generated_dirt(root)
    if gen:
        fixed = fix_generated_dirt(root, gen) if fix else None
        record("generated-dirt", gen, fixed)
        if fixed:
            actions.append({"repair": "generated-dirt",
                            "count": len(fixed)})
        gen = [g for g in gen if g["path"] not in (fixed or [])]
        for p in fixed:
            _ledger_append(root, {"t": time.time(),
                                  "repair": "generated-dirt", "path": p})

    dups = find_duplicate_branches(root)
    if dups:
        fixed = fix_duplicate_branches(root, dups) if fix else None
        record("duplicate-branch", dups, fixed)
        if fixed:
            actions.append({"repair": "duplicate-branch",
                            "count": len(fixed)})
        dups = [d for d in dups if d["branch"] not in (fixed or [])]
        for b in fixed:
            _ledger_append(root, {"t": time.time(),
                                  "repair": "duplicate-branch",
                                  "branch": b})

    stale_wt = find_stale_worktrees(root)
    if stale_wt and fix:
        _git(root, "worktree", "prune")
    if stale_wt:
        record("stale-worktrees", stale_wt,
               [w["path"] for w in stale_wt] if fix else None)

    interrupted = find_interrupted_ops(root)
    if interrupted:
        record("interrupted-op", interrupted)          # never auto-fixed

    if include_machine:
        split = find_split_brain()
        if split:
            record("split-brain", split)           # operator decision

    remaining = 0
    for e in findings:
        if e.get("fixed") is None:
            remaining += e["found"]
        else:
            remaining += max(0, e["found"] - len(e["fixed"]))
    return {"root": root, "fix": fix,
            "findings": findings, "actions": actions,
            "remaining": remaining}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--fix", action="store_true",
                    help="apply safe repairs (default: detect+report)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--protect-minutes", type=float, default=30.0)
    args = ap.parse_args(argv)

    result = sweep(args.root, fix=args.fix,
                   protect_minutes=args.protect_minutes,
                   include_machine=os.environ.get(
                       "TREE_REPAIR_NO_MACHINE") != "1")
    ok, entries = ledger_verify(args.root)
    result["ledger_ok"] = ok
    result["ledger_entries"] = entries

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("=" * 64)
        print("TREE REPAIR - %s (%s)" % (
            result["root"], "FIX" if args.fix else "detect only"))
        print("=" * 64)
        for e in result["findings"]:
            state = ("%d repaired" % len(e["fixed"])) \
                if e.get("fixed") is not None else "report only"
            print("[%s] %s: %d found (%s)" % (
                "FIXED" if e.get("fixed") else "CHECK",
                e["detector"], e["found"], state))
            for item in e["items"][:6]:
                print("    %s" % (item if isinstance(item, str)
                                  else json.dumps(item)[:160]))
        if not result["findings"]:
            print("- tree clean: nothing to repair")
        print("- ledger chain: %s (%d entries)"
              % ("ok" if ok else "BROKEN", entries))
    return 0 if result["remaining"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
