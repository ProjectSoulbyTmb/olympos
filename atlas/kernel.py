"""ATLAS kernel - guest lifecycle over hardened execution lanes.

A guest is a jailed directory plus one running process at a time.
Every exec is argv-only (never a shell), confined to the guest's
workspace, under a hard timeout with tree-kill, capped output capture
and a scrubbed environment. The audit trail is hash-chained so a
silent edit is detectable (rule 16).
"""

import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import threading
import time

from atlas import content

try:                                # optional glue, never load-bearing
    from norn.pulse import Pulse
except ImportError:                 # pragma: no cover
    Pulse = None


class AtlasError(Exception):
    """Rejected intent - audited, never fatal."""


def _now():
    return time.time()


def _iso(epoch=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S",
                         time.localtime(epoch or _now()))


def _slug(name):
    out = "".join(c if (c.isalnum() or c in "-_") else "_"
                  for c in str(name)).strip("_")[:content.MAX_GUEST_NAME_LEN]
    return out or "guest"


class _Chain:
    """Minimal append-only hash-chained JSONL trail (rule 16)."""

    def __init__(self, path):
        self.path = path
        self.head = self._tail(path)
        self._lock = threading.Lock()

    @staticmethod
    def _canonical(entry):
        body = {k: v for k, v in entry.items() if k != "sha"}
        return json.dumps(body, sort_keys=True, separators=(",", ":"),
                          default=str)

    @staticmethod
    def _tail(path):
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 4096))
                tail = fh.read().decode("utf-8", errors="replace")
            last = [ln for ln in tail.splitlines() if ln.strip()][-1]
            return json.loads(last).get("sha", "genesis")
        except (OSError, ValueError, IndexError):
            return "genesis"

    def append(self, entry):
        with self._lock:
            entry["prev"] = self.head
            digest = hashlib.sha256(self._canonical(entry)
                                    .encode("utf-8")).hexdigest()
            entry["sha"] = digest
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                rotate = (os.path.getsize(self.path)
                          if os.path.exists(self.path) else 0) \
                    > content.AUDIT_MAX_BYTES
                if rotate:
                    os.replace(self.path, self.path + ".1")
                    entry["prev"] = "genesis"
                    digest = hashlib.sha256(self._canonical(entry)
                                            .encode("utf-8")).hexdigest()
                    entry["sha"] = digest
                with open(self.path, "a", encoding="utf-8",
                          newline="\n") as fh:
                    fh.write(json.dumps(entry, sort_keys=True,
                                        separators=(",", ":"),
                                        default=str) + "\n")
                self.head = digest
            except OSError:
                pass
            return digest

    def verify(self):
        ok, count, first_bad = True, 0, None
        prev = "genesis"
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for seq, ln in enumerate(
                        (l for l in fh if l.strip()), 1):
                    count = seq
                    try:
                        entry = json.loads(ln)
                        recomputed = hashlib.sha256(
                            self._canonical(entry)
                            .encode("utf-8")).hexdigest()
                        chain_ok = (
                            entry.get("prev") == prev
                            and hmac.compare_digest(
                                entry.get("sha", ""), recomputed))
                    except ValueError:
                        ok = False
                        first_bad = first_bad or seq
                        continue
                    if not chain_ok:
                        ok = False
                        first_bad = first_bad or seq
                    prev = entry.get("sha", prev)
        except OSError:
            return True, 0, None
        return ok, count, first_bad


class Guest:
    """One jailed world: its own directory, at most one live process."""

    def __init__(self, gid, root):
        self.id = gid
        self.root = root
        self.proc = None
        self.created_at = _now()
        self.last_exit = None
        self.execs = 0
        os.makedirs(os.path.join(root, "workspace"), exist_ok=True)
        os.makedirs(os.path.join(root, ".tmp"), exist_ok=True)

    @property
    def workspace(self):
        return os.path.join(self.root, "workspace")

    @property
    def busy(self):
        return self.proc is not None and self.proc.poll() is None

    def snapshot(self):
        return {"id": self.id, "busy": self.busy,
                "execs": self.execs, "last_exit": self.last_exit,
                "created_at": round(self.created_at, 3),
                "age_s": round(_now() - self.created_at, 1)}


def resolve_within(guest_root, rel):
    """Resolve `rel` inside the guest workspace; refuse escapes."""
    if not isinstance(rel, str) or not rel.strip():
        raise AtlasError("path missing")
    cand = os.path.normpath(os.path.join(guest_root, rel))
    root = os.path.normpath(guest_root)
    if cand != root and not cand.startswith(root + os.sep):
        raise AtlasError(f"path outside guest world: {rel}")
    return cand


def _scrubbed_env(guest_root):
    env = {k: v for k, v in os.environ.items()
           if k in content.ENV_ALLOWLIST}
    tmp = os.path.join(guest_root, ".tmp")
    env["TEMP"] = tmp
    env["TMP"] = tmp
    return env


def _kill_tree(pid):
    """Kill pid and its children; taskkill walks the tree on Windows."""
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


class Hypervisor:
    """Owns every guest; the only door into their worlds."""

    def __init__(self, audit_path=None):
        self.guests = {}
        self.audit = _Chain(audit_path or content.AUDIT_PATH)
        self.started_at = _now()
        os.makedirs(content.GUESTS_DIR, exist_ok=True)
        for name in sorted(os.listdir(content.GUESTS_DIR)):
            path = os.path.join(content.GUESTS_DIR, name)
            if os.path.isdir(path):
                g = Guest(name, path)      # adopt orphans from last run
                self.guests[name] = g

    # ------------------------------------------------------------ audit --

    def log(self, kind, **fields):
        return self.audit.append({"t": round(_now(), 3), "ts": _iso(),
                                  "kind": kind, **fields})

    # ------------------------------------------------------- lifecycle --

    def create(self, name):
        gid = _slug(name)
        if len(gid) != len(str(name).strip()) or \
                not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", str(name)):
            raise AtlasError("guest id must be 1-32 chars of "
                             "letters/digits/-/_")
        if gid in self.guests:
            raise AtlasError(f"guest exists: {gid}")
        if len(self.guests) >= content.MAX_GUESTS:
            raise AtlasError(f"hypervisor full ({content.MAX_GUESTS} "
                             "guests); reap or purge first")
        root = os.path.join(content.GUESTS_DIR, gid)
        if os.path.exists(root):
            raise AtlasError("stale directory occupies this guest id")
        self.guests[gid] = Guest(gid, root)
        self.log("create", guest=gid)
        return self.guests[gid].snapshot()

    def get(self, name):
        g = self.guests.get(_slug(name))
        if g is None:
            raise KeyError(f"no such guest: {name}")
        return g

    def stop(self, name):
        g = self.get(name)
        if not g.busy:
            # every lifecycle command is auditable, even no-ops
            self.log("stop", guest=g.id, was_running=False)
            return {"stopped": g.id, "was_running": False}
        _kill_tree(g.proc.pid)
        try:
            g.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            g.proc.kill()
        g.last_exit = g.proc.returncode
        g.proc = None
        self.log("stop", guest=g.id)
        return {"stopped": g.id, "was_running": True}

    def reap(self):
        """Finalize guests whose process died on its own."""
        reaped = []
        for g in self.guests.values():
            if g.proc is not None and g.proc.poll() is not None:
                g.last_exit = g.proc.returncode
                g.proc = None
                reaped.append(g.id)
        return reaped

    def purge(self, name):
        g = self.get(name)
        if g.busy:
            raise AtlasError("guest is running; stop it first")
        shutil.rmtree(g.root, ignore_errors=True)
        del self.guests[g.id]
        self.log("purge", guest=g.id)
        return {"purged": g.id}

    # ------------------------------------------------------------- exec --

    def exec(self, name, argv, timeout_s=None, cwd=""):
        g = self.get(name)
        if g.busy:
            raise AtlasError("guest is busy; one process per world")
        if not isinstance(argv, list) or not argv or \
                not all(isinstance(a, str) for a in argv):
            raise AtlasError("argv must be a non-empty list of strings")
        timeout = min(float(timeout_s or content.GUEST_TIMEOUT_S),
                      content.MAX_GUEST_TIMEOUT_S)
        workdir = resolve_within(g.workspace, cwd or ".")
        env = _scrubbed_env(g.root)
        started = _now()
        creation = subprocess.CREATE_NEW_PROCESS_GROUP \
            if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                argv, cwd=workdir, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=creation)
        except FileNotFoundError as exc:
            raise AtlasError(f"cannot start: {exc}") from exc
        g.proc = proc
        g.execs += 1
        self.log("exec-start", guest=g.id, argv=argv[:6],
                 timeout_s=timeout)
        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc.pid)
            out, err = proc.communicate()
        duration = round(_now() - started, 3)
        cap = content.RUN_OUTPUT_MAX_BYTES

        def _cap(raw):
            text = raw.decode("utf-8", errors="replace")
            return text[:cap] + ("\n...[truncated]" if len(text) > cap
                                 else "")
        exit_code = None if timed_out else proc.returncode
        g.last_exit = exit_code
        if g.proc is proc:
            g.proc = None
        result = {"guest": g.id, "ok": not timed_out and exit_code == 0,
                  "exit_code": exit_code, "timed_out": timed_out,
                  "duration_s": duration,
                  "stdout": _cap(out or b""),
                  "stderr": _cap(err or b"")}
        self.log("exec-done", guest=g.id, ok=result["ok"],
                 exit_code=exit_code, timed_out=timed_out,
                 duration_s=duration)
        return result

    # --------------------------------------------------------- reporting --

    def status(self):
        return {"atlas": True, "version": content.VERSION,
                "guests": len(self.guests),
                "busy": sum(1 for g in self.guests.values() if g.busy),
                "uptime_s": round(_now() - self.started_at, 1),
                "audit": {"head": self.audit.head[:12],
                          "verify": self.audit.verify()[0]}}

    def listing(self):
        return [g.snapshot() for g in self.guests.values()]
