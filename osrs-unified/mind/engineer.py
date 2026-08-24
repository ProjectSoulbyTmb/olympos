import os
import re
import subprocess
import sys
import time

from mind import releaser

HEURISTICS = [
    (re.compile(r"ModuleNotFoundError: No module named 'torch'"),
     "install torch: pip install torch",
     "auto-fixable"),
    (re.compile(r"ModuleNotFoundError: No module named 'numpy'"),
     "install numpy: pip install numpy",
     "auto-fixable"),
    (re.compile(r"ModuleNotFoundError: No module named '(\w+)'"),
     "missing module '{0}' - run: pip install {{0}}",
     "auto-fixable"),
    (re.compile(r"could not reach LLM at (\S+)"),
     "LLM endpoint {0} unreachable - start Ollama or set LLM_BASE_URL",
     "environmental"),
    (re.compile(r"corrupt session"),
     "corrupt sessions are quarantined automatically by the moderator",
     "auto-fixed"),
    (re.compile(r"SyntaxError"),
     "syntax error in source - manual review required",
     "manual"),
]


def find_python():
    return sys.executable


def run_tests(root, timeout=600):
    t0 = time.time()
    proc = subprocess.run(
        [find_python(), "-m", "unittest", "discover", "-s", "tests"],
        cwd=root, capture_output=True, text=True, errors="replace",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW)
    output = (proc.stdout or "") + (proc.stderr or "")
    m = re.search(r"Ran (\d+) tests?", output)
    ran = int(m.group(1)) if m else 0
    ok = proc.returncode == 0
    return {"ok": ok, "ran": ran, "returncode": proc.returncode,
            "duration_s": round(time.time() - t0, 1), "output": output[-8000:]}


def diagnose(test_result):
    advice = []
    text = test_result.get("output", "")
    for pattern, fix, kind in HEURISTICS:
        m = pattern.search(text)
        if m:
            try:
                fix = fix.format(*m.groups())
            except IndexError:
                pass
            advice.append({"fix": fix, "kind": kind})
    if not test_result.get("ok") and not advice:
        advice.append({"fix": "unclassified failure - see test output; "
                       "use --llm for AI diagnosis", "kind": "manual"})
    return advice


def auto_heal(root, state=None, dry_run=False):
    actions = []
    needed = [os.path.join("knowledge", "live"),
              os.path.join("knowledge", "raw")]
    for rel in needed:
        path = os.path.join(root, rel)
        if not os.path.isdir(path):
            if not dry_run:
                os.makedirs(path, exist_ok=True)
            actions.append(f"recreated missing dir {rel}")
    marker = os.path.join(root, "knowledge", "digest.md")
    if not os.path.exists(marker):
        actions.append("knowledge digest missing - schedule update-data")
    return actions


def llm_diagnose(root, test_result, base_url=None, model=None):
    try:
        sys.path.insert(0, root)
        from agent.llm import LLMClient
    except Exception as e:
        return {"error": f"llm unavailable: {e}"}
    client = LLMClient(base_url=base_url, model=model, temperature=0.1)
    system = ("You are MIND, the autonomous software engineer for the "
              "osrs-unified project. Given failing test output, produce a "
              "short diagnosis and a minimal unified-diff patch proposal. "
              "Never invent files that were not mentioned. Be terse.")
    user = (f"Test result: ok={test_result['ok']} "
            f"ran={test_result['ran']}\n\nOutput tail:\n"
            f"{test_result['output'][-4000:]}")
    try:
        answer = client.chat(system, user)
    except RuntimeError as e:
        return {"error": str(e)}
    proposals = os.path.join(root, "mind", "proposals")
    os.makedirs(proposals, exist_ok=True)
    name = time.strftime("proposal_%Y%m%d_%H%M%S.md")
    with open(os.path.join(proposals, name), "w", encoding="utf-8") as f:
        f.write(f"# MIND engineering proposal\n\n"
                f"tests ok={test_result['ok']} ran={test_result['ran']}\n\n"
                f"{answer}\n")
    try:
        from mind.bus import EventBus
        EventBus(root).publish(
            "thoth.proposal",
            {"file": os.path.join("mind", "proposals", name),
             "tests_ok": test_result["ok"], "ran": test_result["ran"],
             "excerpt": answer[:800]}, source="thoth")
    except Exception:
        pass
    return {"saved": os.path.join("mind", "proposals", name),
            "answer": answer}


def list_proposals(root):
    d = os.path.join(root, "mind", "proposals")
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".md"):
            p = os.path.join(d, fn)
            out.append({"file": os.path.relpath(p, root),
                        "mtime": os.path.getmtime(p),
                        "size": os.path.getsize(p)})
    return out


def parse_patch(text):
    """Extract the largest unified diff from a proposal markdown."""
    blocks = re.findall(r"```(?:diff)?\s*\n(.*?)```", text, re.S)
    candidates = [b for b in blocks if b.lstrip().startswith("---")]
    if not candidates:
        lines = text.splitlines()
        idx = next((i for i, ln in enumerate(lines)
                    if ln.startswith("---")), None)
        candidates = ["\n".join(lines[idx:])] if idx is not None else []
    if not candidates:
        return None
    best = max(candidates, key=lambda b: len(b.splitlines()))
    return best.rstrip() + "\n" if best.strip() else None


def apply_proposal(root, proposal_path, dry_run=False, verify=True,
                   state=None, log=print):
    """Conservatively apply a proposed patch.

    Requires: clean git tree, parseable unified diff, `git apply --check`
    passing. After a real apply the test suite must pass again or the
    change is reverted.
    """
    import json as _json
    path = proposal_path
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return {"ok": False, "error": f"unreadable proposal: {e}"}
    patch = parse_patch(text)
    if not patch:
        return {"ok": False,
                "error": "no unified diff found in proposal"}
    if _tree_dirty_ignoring_proposals(root):
        return {"ok": False,
                "error": "working tree dirty - refusing to apply"}
    check = _git_apply(root, patch, check_only=True)
    if check.returncode != 0:
        return {"ok": False,
                "error": "git apply --check failed",
                "detail": (check.stderr or check.stdout)[-800:]}
    if dry_run:
        return {"ok": True, "dry_run": True,
                "patch_lines": len(patch.splitlines())}
    applied = _git_apply(root, patch, check_only=False)
    if applied.returncode != 0:
        return {"ok": False, "error": "git apply failed",
                "detail": (applied.stderr or applied.stdout)[-800:]}
    result = {"ok": True, "applied": True}
    if verify:
        tr = run_tests(root)
        result["tests_ok"] = tr["ok"]
        result["tests_ran"] = tr["ran"]
        if not tr["ok"]:
            releaser._git(root, "checkout", "--", ".")
            _git_apply_undo_untracked(root)
            result["reverted"] = True
            result["ok"] = False
            log("tests failed after apply - reverted")
    if result.get("ok"):
        try:
            from mind.bus import EventBus
            EventBus(root).publish("thoth.proposal.applied",
                                   {"file": os.path.relpath(path, root),
                                    "tests_ran": result.get(
                                        "tests_ran")},
                                   source="mind")
        except Exception:
            pass
        if state is not None:
            state.log("engineer", "proposal-applied",
                      os.path.relpath(path, root))
    return result


def _tree_dirty_ignoring_proposals(root):
    """Dirty check that ignores queued proposals under mind/proposals."""
    r = releaser._git(root, "status", "--porcelain", "--",
                      ":(exclude)mind/proposals")
    return bool((r.stdout or "").strip())


def _git_apply(root, patch, check_only):
    args = ["apply"]
    if check_only:
        args.append("--check")
    return subprocess.run(["git", *args, "-"], cwd=root,
                          input=patch, capture_output=True, text=True,
                          errors="replace")


def _git_apply_undo_untracked(root):
    """git checkout cannot remove files a patch created - drop them."""
    r = releaser._git(root, "status", "--porcelain")
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("?? ") and len(ln) > 3:
            junk = os.path.join(root, ln[3:].strip().strip('"'))
            if os.path.isfile(junk) and (os.sep + "mind" + os.sep
                                         not in junk):
                try:
                    os.remove(junk)
                except OSError:
                    pass
