"""PTAH tools - the audited action surface.

Every tool follows the Action -> Observation pattern:

  args   : plain JSON dict produced by the agent
  ctx    : ToolContext (workspace, repo_root, state, memory_path)
  return : Observation (output, error, exit_code, truncated)

Built-ins:
  terminal      run a shell command, scoped to the workspace, timed
  file_editor   view / create / str_replace (no delete op: fail-safe)
  task_tracker  persistent plan with todo/doing/done states
  grep          regex content search across workspace files
  verify_gate   run a Olympos realm verify suite and report its tail
  memory        remember/recall lessons across conversations (JSONL)

Deletion is deliberately absent from the editor; destructive shell work
is still possible, which is exactly what the security layer gates.
"""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field

from ptah import content


@dataclass
class Observation:
    output: str = ""
    error: str = ""
    exit_code: int = 0
    truncated: bool = False

    @property
    def ok(self):
        return self.exit_code == 0 and not self.error

    def render(self):
        parts = []
        if self.output:
            parts.append(self.output)
        if self.error:
            parts.append(f"[error] {self.error}")
        if self.truncated:
            parts.append("[output truncated]")
        if not parts:
            parts.append("(no output)" if self.ok else "(failed)")
        return "\n".join(parts)


@dataclass
class ToolContext:
    workspace: object                       # LocalWorkspace
    repo_root: str = ""                     # Olympos root when embedded
    state: dict = field(default_factory=dict)   # per-conversation scratch
    memory_path: str = ""                   # persistent lessons JSONL

    @classmethod
    def build(cls, workspace, repo_root=None, memory_path=None):
        return cls(
            workspace=workspace,
            repo_root=repo_root or os.path.dirname(workspace.root),
            state={},
            memory_path=memory_path or os.path.join(
                content.data_dir(), "memory.jsonl"))


class Tool:
    name = "tool"
    description = ""
    schema_text = ""

    def run(self, args, ctx):
        raise NotImplementedError

    def describe(self):
        return f"- {self.name}: {self.description}\n  args: {self.schema_text}"


def _require(args, *keys):
    missing = [k for k in keys if k not in args or args[k] in (None, "")]
    if missing:
        raise ValueError(f"missing required arg(s): {', '.join(missing)}")
    return tuple(args[k] for k in keys)


def _kill_tree(proc):
    """Kill a timed-out process and every child it spawned."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass


# ------------------------------------------------------------------ terminal
class TerminalTool(Tool):
    name = "terminal"
    description = ("Run one shell command inside the workspace. "
                   "Security-classified; destructive commands need "
                   "confirmation.")
    schema_text = ('{"command": "<shell command>", "timeout_s": <int?, '
                   'default 60>, "cwd": "<rel dir?, default .>"}')

    def run(self, args, ctx):
        (command,) = _require(args, "command")
        timeout = min(int(args.get("timeout_s", content.TERMINAL_TIMEOUT_S)),
                      content.TERMINAL_TIMEOUT_S)
        cwd_rel = args.get("cwd") or "."
        try:
            cwd = ctx.workspace.resolve(cwd_rel)
        except Exception as exc:               # PathEscape and friends
            return Observation(error=f"bad cwd {cwd_rel!r}: {exc}",
                               exit_code=2)
        if not os.path.isdir(cwd):
            return Observation(error=f"cwd does not exist: {cwd_rel}",
                               exit_code=2)
        popen_kwargs = {}
        if os.name != "nt":
            # own process group so the whole tree can be killed
            popen_kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(
                str(command), cwd=cwd, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, shell=True, **popen_kwargs)
        except OSError as exc:
            return Observation(error=f"spawn failed: {exc}", exit_code=126)
        try:
            out_b, err_b = proc.communicate(timeout=max(1, timeout))
            out = out_b.decode("utf-8", errors="replace")
            err = err_b.decode("utf-8", errors="replace")
            code = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                out_b, err_b = proc.communicate(timeout=5)
            except (subprocess.TimeoutExpired, ValueError):
                out_b, err_b = b"", b""
            return Observation(
                error=f"timed out after {timeout}s",
                output=out_b.decode("utf-8", errors="replace")[:512],
                exit_code=124)
        except OSError as exc:
            return Observation(error=f"spawn failed: {exc}", exit_code=126)
        except subprocess.TimeoutExpired:
            return Observation(error=f"timed out after {timeout}s",
                               exit_code=124)
        except OSError as exc:
            return Observation(error=f"spawn failed: {exc}", exit_code=126)
        cap = content.TERMINAL_OUTPUT_CAP
        truncated = len(out) + len(err) > cap
        return Observation(output=out[:cap], error=err[:cap], exit_code=code,
                           truncated=truncated)


# --------------------------------------------------------------- file_editor
class FileEditorTool(Tool):
    name = "file_editor"
    description = ("View, create or edit text files inside the workspace. "
                   "create refuses existing files; str_replace demands a "
                   "unique match.")
    schema_text = ('{"op": "view|create|str_replace", "path": "<rel>", '
                   '"content": "<create only>", "old": "<str_replace only>", '
                   '"new": "<str_replace only>"}')

    def run(self, args, ctx):
        op, path = _require(args, "op", "path")
        try:
            if op == "view":
                text = ctx.workspace.read_file(path)
                lines = text.splitlines()
                numbered = "\n".join(f"{i + 1}: {ln}"
                                     for i, ln in enumerate(lines[:2000]))
                extra = ("\n... (truncated at 2000 lines)"
                         if len(lines) > 2000 else "")
                return Observation(output=numbered + extra)
            if op == "create":
                (blob,) = _require(args, "content")
                info = ctx.workspace.write_file(path, blob, overwrite=False)
                return Observation(
                    output=f"created {info['path']} ({info['bytes']} bytes)")
            if op == "str_replace":
                old, new = _require(args, "old", "new")
                text = ctx.workspace.read_file(path)
                hits = text.count(old)
                if hits == 0:
                    return Observation(error="old string not found",
                                       exit_code=1)
                if hits > 1:
                    return Observation(
                        error=f"old string matches {hits} times; "
                              "make it unique", exit_code=1)
                ctx.workspace.write_file(path, text.replace(old, new, 1))
                return Observation(output=f"edited {path}")
            return Observation(error=f"unknown op: {op!r}", exit_code=2)
        except FileNotFoundError as exc:
            return Observation(error=str(exc), exit_code=1)
        except Exception as exc:                # PathEscape, SizeLimit...
            return Observation(error=f"{type(exc).__name__}: {exc}",
                               exit_code=2)


# --------------------------------------------------------------- task_tracker
VALID_STATES = ("todo", "doing", "done")


class TaskTrackerTool(Tool):
    name = "task_tracker"
    description = ("Keep a visible plan: add tasks, move them through "
                   "todo/doing/done so progress survives turns.")
    schema_text = ('{"op": "add|update|list", "title": "<add only>", '
                   '"id": <update only>, "status": "<update only>"}')

    def run(self, args, ctx):
        plan = ctx.state.setdefault("plan", [])
        op = args.get("op", "list")
        if op == "add":
            (title,) = _require(args, "title")
            tid = 1 + max((t["id"] for t in plan), default=0)
            plan.append({"id": tid, "title": str(title), "status": "todo"})
            return Observation(output=f"added task #{tid}: {title}")
        if op == "update":
            tid, status = _require(args, "id", "status")
            status = str(status).lower()
            if status not in VALID_STATES:
                return Observation(
                    error=f"status must be one of {VALID_STATES}",
                    exit_code=2)
            for t in plan:
                if t["id"] == int(tid):
                    t["status"] = status
                    return Observation(
                        output=f"task #{tid} -> {status}: {t['title']}")
            return Observation(error=f"no task #{tid}", exit_code=1)
        if op == "list":
            if not plan:
                return Observation(output="(empty plan)")
            rows = [f"#{t['id']} [{t['status']}] {t['title']}"
                    for t in plan]
            return Observation(output="\n".join(rows))
        return Observation(error=f"unknown op: {op!r}", exit_code=2)


# ---------------------------------------------------------------------- grep
class GrepTool(Tool):
    name = "grep"
    description = ("Regex search across workspace files (text files only). "
                   "Returns path:line:text matches.")
    schema_text = ('{"pattern": "<regex>", "glob": "<suffix filter?, e.g. '
                   '.py>", "max_results": <int?, default 50>}')

    SNIFF_LIMIT = 1024 * 1024              # skip files above 1 MB

    def run(self, args, ctx):
        (pattern,) = _require(args, "pattern")
        glob = args.get("glob") or ""
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return Observation(error=f"bad regex: {exc}", exit_code=2)
        limit = min(int(args.get("max_results", 50)), 200)
        hits = []
        scanned = 0
        for rel in ctx.workspace.walk_files():
            if glob and not rel.endswith(glob):
                continue
            path = ctx.workspace.resolve(rel)
            try:
                if os.path.getsize(path) > self.SNIFF_LIMIT:
                    continue
                with open(path, "r", encoding="utf-8",
                          errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(f"{rel}:{lineno}: "
                                        f"{line.rstrip()[:200]}")
                            scanned += 1
                            if scanned >= limit:
                                break
            except OSError:
                continue
            if scanned >= limit:
                break
        if not hits:
            return Observation(output="(no matches)")
        note = "" if scanned < limit else f"\n(stopped at {limit} results)"
        return Observation(output="\n".join(hits) + note)


# ---------------------------------------------------------------- verify_gate
REALM_GATES = {
    "ptah": os.path.join("ptah", "verify_ptah.py"),
    "zeus": os.path.join("zeus", "verify_zeus.py"),
    "vulcan": os.path.join("vulcan", "verify_vulcan.py"),
    "hades": os.path.join("hades", "verify_hades.py"),
}


class VerifyGateTool(Tool):
    name = "verify_gate"
    description = ("Run a Olympos realm verification suite (proof of "
                   "work). Never claim success without a green gate.")
    schema_text = '{"realm": "ptah|zeus|vulcan|hades"}'

    TIMEOUT_S = 240

    def run(self, args, ctx):
        (realm,) = _require(args, "realm")
        rel = REALM_GATES.get(str(realm).lower())
        if rel is None:
            return Observation(error=f"unknown realm {realm!r}; known: "
                                     f"{sorted(REALM_GATES)}", exit_code=2)
        script = os.path.join(ctx.repo_root or "", *rel.split(os.sep))
        if not os.path.isfile(script):
            return Observation(error=f"gate script not found: {rel}",
                               exit_code=2)
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, "-u", script],
                cwd=ctx.repo_root or ".", capture_output=True,
                timeout=self.TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return Observation(error=f"gate exceeded {self.TIMEOUT_S}s",
                               exit_code=124)
        except OSError as exc:
            return Observation(error=f"spawn failed: {exc}", exit_code=126)
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip()
        keep = 12
        lines = tail.splitlines()[-keep:]
        secs = round(time.time() - t0, 1)
        verdict = "PASS" if proc.returncode == 0 else "FAIL"
        return Observation(output=f"{verdict} ({secs}s)\n" + "\n".join(lines),
                           exit_code=proc.returncode)


# -------------------------------------------------------------------- memory
class MemoryTool(Tool):
    name = "memory"
    description = ("Persistent cross-conversation lessons: remember(text), "
                   "recall([query]) returns matching history.")
    schema_text = ('{"op": "remember|recall", "text": "<remember text or '
                   'recall query?>", "limit": <int?, default 5>}')

    def run(self, args, ctx):
        op = args.get("op", "recall")
        mem_path = ctx.memory_path
        if op == "remember":
            (text,) = _require(args, "text")
            entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime()), "text": str(text)}
            os.makedirs(os.path.dirname(mem_path), exist_ok=True)
            with open(mem_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return Observation(output=f"remembered ({len(ctx.state.get('memories', [])) + 1} this session)")
        if op == "recall":
            query = str(args.get("text") or "").lower()
            limit = min(int(args.get("limit", 5)), 50)
            rows = []
            if os.path.isfile(mem_path):
                with open(mem_path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        if not query or query in str(rec.get("text", "")).lower():
                            rows.append(f"{rec.get('ts', '?')} "
                                        f"{rec.get('text', '')}")
            rows = rows[-limit:] if limit else rows[-5:]
            if not rows:
                return Observation(output="(no memories)")
            return Observation(output="\n".join(rows))
        return Observation(error=f"unknown op: {op!r}", exit_code=2)


# ------------------------------------------------------------------- registry
class ToolRegistry:
    """Ordered tool collection; order defines prompt presentation."""

    def __init__(self, tools=()):
        self._tools = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool):
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name):
        return self._tools.get(name)

    def names(self):
        return list(self._tools)

    def describe_all(self):
        return "\n".join(t.describe() for t in self._tools.values())


def default_registry():
    """The standard PTAH toolkit."""
    return ToolRegistry([
        TerminalTool(),
        FileEditorTool(),
        GrepTool(),
        TaskTrackerTool(),
        VerifyGateTool(),
        MemoryTool(),
    ])
