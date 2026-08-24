"""HYPNOS hands - the small verbs a task letter may ask for.

Every verb is local and bounded: paths must resolve inside an allowed
root, runs are argv lists under hard timeouts, outputs are capped. A
verb never raises past the executor - it returns a result dict instead,
so one bad step can never kill a whole task silently.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time

from hypnos import content


class ActionError(Exception):
    """Rejected spec - audited as a failed action, never fatal."""


# ------------------------------------------------------------- confinement

def resolve(path):
    """Resolve `path` against the workspace; refuse escapes."""
    if not isinstance(path, str) or not path.strip():
        raise ActionError("path missing")
    raw = path.strip()
    if os.path.isabs(raw):
        cand = os.path.normpath(raw)
    else:
        cand = os.path.normpath(os.path.join(content.WORKSPACE, raw))
    cand = os.path.normcase(cand)
    for root in content.ALLOWED_ROOTS:
        r = os.path.normcase(os.path.normpath(root))
        if cand == r or cand.startswith(r + os.sep):
            return cand
    raise ActionError("path outside allowed roots: %s" % path)


def _text(value, cap=None):
    if value is None:
        return ""
    out = value.decode("utf-8", errors="replace") \
        if isinstance(value, bytes) else str(value)
    limit = content.RUN_OUTPUT_MAX_BYTES if cap is None else cap
    if len(out.encode("utf-8", errors="replace")) > limit:
        out = out[:limit]
        out += "\n...[truncated]"
    return out


# ------------------------------------------------------------------ verbs

def _do_run(spec):
    argv = spec.get("argv")
    if not isinstance(argv, list) or not argv or \
            not all(isinstance(a, str) for a in argv):
        raise ActionError("argv must be a non-empty list of strings")
    cwd = content.WORKSPACE
    if spec.get("cwd"):
        cwd = resolve(spec["cwd"])
        if not os.path.isdir(cwd):
            raise ActionError("cwd not a directory: %s" % spec["cwd"])
    try:
        timeout = float(spec.get("timeout_s",
                                 content.DEFAULT_RUN_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout = content.DEFAULT_RUN_TIMEOUT_S
    timeout = max(0.1, min(timeout, content.MAX_RUN_TIMEOUT_S))

    started = time.time()
    timed_out = False
    code = None
    out = err = b""
    try:
        proc = subprocess.run(
            argv, cwd=cwd, shell=content.SHELL_ALLOWED,
            capture_output=True, timeout=timeout)
        code = proc.returncode
        out, err = proc.stdout or b"", proc.stderr or b""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out = getattr(exc, "stdout", None) or b""
        err = getattr(exc, "stderr", None) or b""
    except FileNotFoundError as exc:
        raise ActionError("executable not found: %s" % exc)
    duration = round(time.time() - started, 3)
    return {"ok": (code == 0) and not timed_out,
            "exit_code": code, "timed_out": timed_out,
            "duration_s": duration,
            "stdout": _text(out),
            "stderr": _text(err)}


def _atomic_write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _do_write_file(spec):
    path = resolve(spec.get("path"))
    text = _text(spec.get("text", ""))
    _atomic_write_text(path, text)
    return {"ok": True, "path": spec.get("path"),
            "bytes": len(text.encode("utf-8"))}


def _do_append_file(spec):
    path = resolve(spec.get("path"))
    text = _text(spec.get("text", ""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)
    return {"ok": True, "path": spec.get("path"),
            "bytes": len(text.encode("utf-8"))}


def _do_mkdir(spec):
    path = resolve(spec.get("path"))
    os.makedirs(path, exist_ok=True)
    return {"ok": True, "path": spec.get("path")}


def _pair(spec):
    src, dst = resolve(spec.get("src")), resolve(spec.get("dst"))
    if not os.path.exists(src):
        raise ActionError("src missing: %s" % spec.get("src"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    return src, dst


def _do_move(spec):
    src, dst = _pair(spec)
    try:
        os.replace(src, dst)
    except OSError:
        shutil.move(src, dst)
    return {"ok": True, "src": spec.get("src"), "dst": spec.get("dst")}


def _do_copy(spec):
    src, dst = _pair(spec)
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return {"ok": True, "src": spec.get("src"), "dst": spec.get("dst")}


def _do_delete(spec):
    path = resolve(spec.get("path"))
    if not os.path.exists(path):
        raise ActionError("nothing to delete: %s" % spec.get("path"))
    if os.path.isdir(path):
        if not spec.get("recursive"):
            raise ActionError("refusing directory without recursive flag")
        shutil.rmtree(path)
    else:
        os.unlink(path)
    return {"ok": True, "path": spec.get("path")}


def _do_sleep(spec):
    try:
        seconds = float(spec.get("seconds", 0))
    except (TypeError, ValueError):
        seconds = 0.0
    seconds = max(0.0, min(seconds, content.MAX_SLEEP_S))
    time.sleep(seconds)
    return {"ok": True, "slept_s": round(seconds, 3)}


def _do_mail(spec, post):
    if post is None:
        raise ActionError("no post office wired")
    to = spec.get("to")
    if not isinstance(to, str) or not to.strip():
        raise ActionError("mail needs a recipient organ")
    lid = post.send(to, spec.get("kind", "note"),
                    spec.get("payload", {}), frm=content.ORGAN)
    return {"ok": True, "letter_id": lid, "to": to}


def _do_broadcast(spec, post):
    if post is None:
        raise ActionError("no post office wired")
    seq = post.broadcast(spec.get("topic", content.TOPIC),
                         spec.get("kind", "event"),
                         spec.get("payload", {}), frm=content.ORGAN)
    return {"ok": True, "topic_seq": seq}


# --------------------------------------------------------------- dispatch

_VERBS = {
    "run": _do_run,
    "write_file": _do_write_file,
    "append_file": _do_append_file,
    "mkdir": _do_mkdir,
    "move": _do_move,
    "copy": _do_copy,
    "delete": _do_delete,
    "sleep": _do_sleep,
}

_POST_VERBS = {
    "mail": _do_mail,
    "broadcast": _do_broadcast,
}

VERBS = sorted(list(_VERBS) + list(_POST_VERBS))


def execute(spec, post=None):
    """Run one action spec; always returns a JSON-safe result dict."""
    name = ""
    try:
        if not isinstance(spec, dict):
            raise ActionError("action must be an object")
        name = str(spec.get("do", "")).strip()
        fn = _VERBS.get(name) or _POST_VERBS.get(name)
        if fn is None:
            raise ActionError("unknown verb: %s (known: %s)"
                              % (name or "<empty>", ", ".join(VERBS)))
        result = fn(spec) if fn in _VERBS.values() else fn(spec, post)
        result.update({"do": name})
        return result
    except ActionError as exc:
        return {"do": name or "?", "ok": False, "error": str(exc)}
    except OSError as exc:
        return {"do": name or "?", "ok": False, "error": repr(exc)}
