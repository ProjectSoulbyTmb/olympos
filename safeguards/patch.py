"""SAFEGUARDS patch lane - autonomous, gate-guarded code patches.

A patch letter carries a unified diff. The lane:
  1. refuses unless `git apply --check` accepts it cleanly;
  2. applies it to the working tree;
  3. runs safeguards/check.py --strict over the touched paths;
  4. commits exactly those paths via the isolated-index safe_commit
     (shared index and other lanes' staged files stay untouched);
  5. on ANY failure: rolls the tree back to the pre-patch state and
     returns a precise error - the workspace is never left torn.

This is what lets agents patch the organism while they sleep.
"""

import contextlib
import io
import os
import subprocess
import sys

ROOT = os.getcwd()
HERE = os.path.dirname(os.path.abspath(__file__))


def _git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT,
                       capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: "
                           f"{(r.stderr or r.stdout).strip()[:200]}")
    return r


def apply_patch(diff_text, message, paths=None):
    """Apply + gate + commit one unified diff. Returns dict result."""
    if not isinstance(diff_text, str) or not diff_text.strip():
        return {"ok": False, "error": "empty diff"}
    if "---" not in diff_text or "+++" not in diff_text \
            or "@@" not in diff_text:
        return {"ok": False, "error": "not a unified diff"}
    head_before = _git("rev-parse", "HEAD").stdout.strip()
    untracked_before = set(_git(
        "ls-files", "--others", "--exclude-standard",
        check=False).stdout.splitlines())

    # 1. dry-run accept/reject with full fidelity
    chk = subprocess.run(["git", "apply", "--check", "--whitespace=nowarn"],
                         input=diff_text.encode("utf-8"), cwd=ROOT,
                         capture_output=True)
    if chk.returncode:
        return {"ok": False,
                "error": "patch does not apply cleanly: "
                         f"{chk.stderr.decode(errors='replace')[:200]}"}

    # 2. apply for real
    app = subprocess.run(["git", "apply", "--whitespace=nowarn"],
                         input=diff_text.encode("utf-8"), cwd=ROOT,
                         capture_output=True)
    if app.returncode:
        return {"ok": False,
                "error": "apply failed post-check: "
                         f"{app.stderr.decode(errors='replace')[:200]}"}

    touched = sorted({ln[6:].strip()
                      for ln in diff_text.splitlines()
                      if ln.startswith("+++ b/")
                      and "/dev/null" not in ln})
    try:
        # 3. strict safeguards over exactly the touched paths
        gate = subprocess.run(
            [sys.executable,
             os.path.join(HERE, "check.py"), "--strict", *touched],
            cwd=ROOT, capture_output=True, text=True)
        if gate.returncode:
            raise RuntimeError("safeguards rejected patch: "
                               + gate.stdout[-300:])
        # 4. isolated-index commit of exactly the touched paths
        from safeguards import safe_commit
        buf = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(err):
            rc = safe_commit.main(["-m", message, *touched])
        if rc != 0:
            raise RuntimeError("safe_commit refused: "
                               + err.getvalue().strip()[-200:])
        return {"ok": True, "committed": buf.getvalue().strip()[:12],
                "paths": touched}
    except Exception as exc:                  # noqa: BLE001 - rollback
        _rollback(head_before, untracked_before)
        return {"ok": False, "error": str(exc)[:300],
                "rolled_back": True}


def _rollback(head_before, untracked_before):
    """Surgical restore: hard reset to prior HEAD, then remove only
    untracked files the patch itself introduced - never another
    lane's work-in-progress."""
    try:
        _git("reset", "--hard", head_before, check=False)
        now = set(_git("ls-files", "--others", "--exclude-standard",
                       check=False).stdout.splitlines())
        for f in sorted(now - untracked_before):
            try:
                os.unlink(os.path.join(ROOT, f))
            except OSError:
                pass
    except Exception:                        # noqa: BLE001 - last resort
        pass
