"""PTAH verify suite - gates every behavioral change to the kernel.

Run: python ptah/verify_ptah.py   (exit 0 = all checks pass)

Scenario-driven like every Olympos gate: builds throwaway workspaces,
drives the real agent loop with scripted brains, attacks security from
every angle (denials, confirmations, escapes), replays conversations,
boots the REST server on an ephemeral port and even exercises the CLI.
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ptah import content                            # noqa: E402
from ptah.agent import Agent                        # noqa: E402
from ptah.condenser import condense                 # noqa: E402
from ptah.conversation import Conversation          # noqa: E402
from ptah.events import ActionEvent, UserMessage    # noqa: E402
from ptah.llm import LLM, LLMConfig, ScriptedLLM    # noqa: E402
from ptah.security import ConfirmationPolicy, RiskAnalyzer  # noqa: E402
from ptah.skills import load_skills, select_skills  # noqa: E402
from ptah.tools import ToolRegistry, TerminalTool, FileEditorTool  # noqa
from ptah.workspace import LocalWorkspace, PathEscape  # noqa: E402


def jaction(tool, **args):
    return json.dumps({"action": {"tool": tool, "args": args}})


def harness(tmp, replies, policy="confirm-risky", max_iters=12):
    ws = LocalWorkspace(tmp)
    conv = Conversation.new(root=os.path.join(tmp, "_state"),
                            workspace_root=ws.root)
    registry = ToolRegistry([TerminalTool(), FileEditorTool()])
    agent = Agent(llm=ScriptedLLM(replies), registry=registry,
                  policy=ConfirmationPolicy(policy),
                  max_iterations=max_iters)
    return conv, ws, agent


# ------------------------------------------------------------------ checks
def _registry_port(name):
    """The port realms/registry.json declares for `name` (single
    source of membership); historical floor when the manifest is
    absent or unreadable."""
    here = os.path.dirname(os.path.abspath(__file__))
    reg = os.path.join(os.path.dirname(here), "realms",
                       "registry.json")
    try:
        with open(reg, encoding="utf-8") as fh:
            for r in json.load(fh).get("realms", []):
                if r.get("name") == name and r.get("port"):
                    return int(r["port"])
    except (OSError, ValueError):
        pass
    return 43903


def check_fleet_identity():
    expected = _registry_port("ptah")
    if content.SERVER_PORT != expected:
        return f"port drifted: {content.SERVER_PORT} " \
               f"!= registry {expected}"
    if content.VERSION.count(".") != 2:
        return f"version not semver: {content.VERSION}"
    try:
        from zeus import content as zc
        if content.SERVER_PORT == zc.SERVER_PORT:
            return "port collides with zeus"
    except ImportError:
        pass                          # standalone checkout is allowed
    return True


def check_security_matrix():
    ra = RiskAnalyzer()
    cases = [
        ("terminal", {"command": "rm -rf /"}, "DENIED"),
        ("terminal", {"command": "mkfs.ext4 /dev/sda"}, "DENIED"),
        ("terminal", {"command": "reg delete HKLM\\X"}, "DENIED"),
        ("terminal", {"command": "rm -rf build/"}, "DESTRUCTIVE"),
        ("terminal", {"command": "git push --force"}, "DESTRUCTIVE"),
        ("terminal", {"command": "pip install x"}, "ELEVATED"),
        ("terminal", {"command": "curl example.com"}, "ELEVATED"),
        ("file_editor", {"op": "create", "path": "a", "content": "b"},
         "SAFE"),
    ]
    for tool, args, want in cases:
        got = ra.classify(tool, args).risk
        if got != want:
            return f"{tool} {args} -> {got}, want {want}"
    policy = ConfirmationPolicy("confirm-risky")
    v = ra.classify("terminal", {"command": "rm -rf build/"})
    if not policy.apply(v):
        return "destructive not gated under default policy"
    return True


def check_workspace_escapes():
    with tempfile.TemporaryDirectory(prefix="ptah-gate-ws-") as tmp:
        ws = LocalWorkspace(tmp)
        attacks = ["../x", "a/../../x", "/abs", "C:\\abs", "~root"]
        for bad in attacks:
            try:
                ws.resolve(bad)
            except PathEscape:
                continue
            return f"escape accepted: {bad!r}"
        ws.write_file("d/f.txt", "ok")
        if ws.read_file("d/f.txt") != "ok":
            return "roundtrip failed"
        return True


def check_editor_contract():
    with tempfile.TemporaryDirectory(prefix="ptah-gate-ed-") as tmp:
        ctx = type("Ctx", (), {})()
        ws = LocalWorkspace(tmp)
        from ptah.tools import ToolContext
        ctx = ToolContext.build(ws)
        ed = FileEditorTool()
        o1 = ed.run({"op": "create", "path": "f.txt", "content": "aa\n"},
                    ctx)
        if not o1.ok:
            return f"create failed: {o1.error}"
        o2 = ed.run({"op": "create", "path": "f.txt", "content": "bb"},
                    ctx)
        if o2.ok:
            return "silent overwrite allowed"
        o3 = ed.run({"op": "str_replace", "path": "f.txt", "old": "a",
                     "new": "z"}, ctx)
        if o3.ok:
            return "ambiguous replace allowed"
        o4 = ed.run({"op": "str_replace", "path": "f.txt", "old": "aa",
                     "new": "zz"}, ctx)
        if not o4.ok or ws.read_file("f.txt") != "zz\n":
            return f"unique replace broken: {o4.error}"
        return True


def check_terminal_scoped_and_timed():
    with tempfile.TemporaryDirectory(prefix="ptah-gate-term-") as tmp:
        from ptah.tools import ToolContext
        ctx = ToolContext.build(LocalWorkspace(tmp))
        term = TerminalTool()
        obs = term.run({"command": "echo ptah_gate_ok"}, ctx)
        if obs.exit_code != 0 or "ptah_gate_ok" not in obs.output.lower():
            return f"echo failed: {obs.render()}"
        bad = term.run({"command": "echo x", "cwd": "../.."}, ctx)
        if bad.exit_code == 0:
            return "cwd escape accepted"
        sleeper = ("ping -n 30 127.0.0.1 >nul" if os.name == "nt"
                   else "sleep 30")
        t0 = time.time()
        to = term.run({"command": sleeper, "timeout_s": 1}, ctx)
        elapsed = time.time() - t0
        if to.exit_code != 124 or elapsed > 15:
            return f"timeout broken: code={to.exit_code} took {elapsed:.1f}s"
        return True


def check_skills_builtin():
    skills = load_skills(content.BUILTIN_SKILLS_DIR)
    names = {s.name for s in skills}
    if "Olympos-conventions" not in names or "ptah-workflow" not in names:
        return f"builtin cards missing: {sorted(names)}"
    hit = select_skills(skills, "please verify the gate")[0]
    if hit.name != "Olympos-conventions":
        return "trigger mismatch"
    return True


def check_condenser():
    evs = [UserMessage(text="mission")]
    for i in range(40):
        evs.append(ActionEvent(tool="terminal",
                               args={"command": f"do {i}"}))
    kept, dropped = condense(evs, budget_tokens=60)
    if not dropped or kept[0].text != "mission":
        return "head/mission lost"
    again = [e.to_dict() for e in condense(evs, budget_tokens=60)[0]]
    if again != [e.to_dict() for e in kept]:
        return "non-deterministic"
    return True


class _Stub(BaseHTTPRequestHandler):
    stats = {"hits": 0}

    def log_message(self, *a):
        pass

    def do_POST(self):                     # noqa: N802
        self.stats["hits"] += 1
        n = int(self.headers.get("content-length", 0))
        self.rfile.read(n)
        ok = self.stats["hits"] >= 2       # fail exactly once
        payload = {
            "model": "stub",
            "choices": [{"message": {"content":
                                     '{"answer": "retry worked"}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
        blob = json.dumps(payload).encode()
        self.send_response(200 if ok else 500)
        self.send_header("content-length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)


def check_llm_retry():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    _Stub.stats["hits"] = 0
    try:
        cfg = LLMConfig(provider="openai", model="stub", api_key="k",
                        base_url=f"http://127.0.0.1:"
                                 f"{srv.server_address[1]}/v1",
                        backoff_base_s=0.01, max_retries=3, timeout_s=5)
        reply = LLM(cfg).complete("sys", [])
        if '{"answer": "retry worked"}' != reply.text:
            return f"bad reply: {reply.text!r}"
        if _Stub.stats["hits"] < 2:
            return "no retry observed"
        return True
    finally:
        srv.shutdown()
        srv.server_close()


_ENV_KEYS = ("PTAH_BASE_URL", "PTAH_LLM_MODEL", "PTAH_LMSTUDIO_URL",
             "PTAH_LMSTUDIO_MODEL", "PTAH_LLM_PROVIDER")


class _EnvScope:
    """Force selected PTAH_* env keys inside a with-block; restore after."""

    def __init__(self, **overrides):
        self.overrides = overrides
        self.saved = {k: os.environ.get(k) for k in _ENV_KEYS}

    def __enter__(self):
        for k, v in self.overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def check_lmstudio_seam():
    """LM Studio seam: env-driven, precedence explicit > alias >
    default; config time never dials the network; scripted boot is
    unchanged with dead endpoints."""
    # 1. alias-only configuration resolves onto the standard seam
    with _EnvScope(PTAH_LMSTUDIO_URL="http://127.0.0.1:1234/v1",
                   PTAH_LMSTUDIO_MODEL="qwen2.5-7b-instruct"):
        cfg = LLMConfig.from_env()
    if cfg.provider != "openai" or cfg.base_url != "http://127.0.0.1:1234/v1":
        return f"alias url not honored: {cfg.base_url!r}"
    if cfg.model != "qwen2.5-7b-instruct":
        return f"alias model not honored: {cfg.model!r}"

    # 2. canonical keys outrank aliases
    with _EnvScope(PTAH_BASE_URL="http://127.0.0.1:9999/v1",
                   PTAH_LMSTUDIO_URL="http://127.0.0.1:1234/v1",
                   PTAH_LLM_MODEL="canon", PTAH_LMSTUDIO_MODEL="alias"):
        cfg = LLMConfig.from_env()
    if cfg.base_url != "http://127.0.0.1:9999/v1" or cfg.model != "canon":
        return f"precedence broken: {cfg.base_url!r}/{cfg.model!r}"

    # 3. clean env -> provider defaults, empty base_url
    with _EnvScope(**{k: None for k in _ENV_KEYS}):
        cfg = LLMConfig.from_env()
    if cfg.provider != "openai" or cfg.base_url != "":
        return f"default posture drifted: {cfg.provider}/{cfg.base_url!r}"

    # 4. pointing at a dead endpoint costs nothing at config/boot time
    with _EnvScope(PTAH_LMSTUDIO_URL="http://127.0.0.1:1234/v1"):
        brain = LLM(LLMConfig.from_env())
    if brain.config.base_url != "http://127.0.0.1:1234/v1":
        return "dead-endpoint config mutated"

    # 5. scripted boot unchanged with LM aliases present
    from ptah.cli import build_brain, build_parser
    with _EnvScope(PTAH_LMSTUDIO_URL="http://127.0.0.1:1234/v1",
                   PTAH_LMSTUDIO_MODEL="qwen2.5-7b-instruct"):
        args = build_parser().parse_args(["run", "--demo"])
        demo_brain = build_brain(args)
    if not isinstance(demo_brain, ScriptedLLM):
        return f"demo boot left scripted mode: {type(demo_brain).__name__}"
    return True


def check_end_to_end_solve():
    with tempfile.TemporaryDirectory(prefix="ptah-gate-e2e-") as tmp:
        conv, ws, agent = harness(tmp, [
            jaction("task_tracker", op="add", title="note"),
            jaction("file_editor", op="create", path="REPORT.md",
                    content="# done"),
            json.dumps({"answer": "report written"}),
        ])
        res = agent.run(conv, "write REPORT.md", workspace=ws)
        if res.reason != "answered" or ws.read_file("REPORT.md") != "# done":
            return f"solve broken: {res}"
        if conv.status != Conversation.FINISHED:
            return f"status wrong: {conv.status}"
        reloaded = Conversation.load(conv.dir)
        if len(reloaded.events) != len(conv.events):
            return "replay count mismatch"
        return True


def check_confirmation_cycle():
    with tempfile.TemporaryDirectory(prefix="ptah-gate-conf-") as tmp:
        conv, ws, agent = harness(tmp, [
            jaction("terminal", command="rm -rf old/"),
            jaction("file_editor", op="create", path="after.txt",
                    content="resumed"),
            json.dumps({"answer": "cleaned"}),
        ])
        paused = agent.run(conv, "clean up", workspace=ws)
        if paused.status != Conversation.WAITING_CONFIRMATION:
            return f"did not pause: {paused}"
        if ws.exists("after.txt"):
            return "executed before confirmation!"
        resumed = agent.run(conv, confirm=True, workspace=ws)
        if resumed.status != Conversation.FINISHED:
            return f"resume failed: {resumed}"
        if not ws.exists("after.txt"):
            return "confirmed action never executed"
        confirms = [e for e in conv.events
                    if e.TYPE == "confirmation_required"]
        if len(confirms) != 1:
            return f"gate did not re-arm correctly: {len(confirms)}"
        return True


def check_denial_enforcement():
    with tempfile.TemporaryDirectory(prefix="ptah-gate-deny-") as tmp:
        conv, ws, agent = harness(tmp, [
            jaction("terminal", command="shutdown /s /t 0"),
            json.dumps({"answer": "refused"}),
        ])
        res = agent.run(conv, "reboot the host", workspace=ws)
        denial = next((e for e in conv.events
                       if e.TYPE == "denied_action"), None)
        if res.reason != "answered" or denial is None:
            return f"denial flow broken: {res}"
        return True


def check_stuck_detector():
    with tempfile.TemporaryDirectory(prefix="ptah-gate-stuck-") as tmp:
        same = jaction("terminal", command="echo loop")
        conv, ws, agent = harness(tmp, [same] * 6)
        res = agent.run(conv, "loop", workspace=ws)
        actions = [e for e in conv.events if e.TYPE == "action"]
        if res.reason != "stuck" or len(actions) != \
                content.STUCK_REPEAT_LIMIT:
            return f"stuck detection off: {res}, {len(actions)} actions"
        return True


def check_server_smoke():
    from ptah.conversation import Store
    from ptah.server import ApiServer, make_handler
    with tempfile.TemporaryDirectory(prefix="ptah-gate-api-") as tmp:
        store = Store(root=os.path.join(tmp, "store"))

        def runner(conv, text, confirm):
            ws = LocalWorkspace(conv.meta.get("workspace") or ".")
            agent = Agent(llm=ScriptedLLM(
                ['{"answer": "api ok"}']),
                registry=ToolRegistry([FileEditorTool()]),
                policy=ConfirmationPolicy("auto"))
            return agent.run(conv, text, confirm=confirm, workspace=ws)

        httpd = ApiServer(("127.0.0.1", 0),
                          make_handler(store, runner, token="gate-token"))
        port = httpd.server_address[1]
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        try:
            def call(method, path, body=None, auth=True):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}{path}",
                    method=method,
                    data=json.dumps(body).encode() if body else None,
                    headers={"content-type": "application/json",
                             "authorization": "Bearer gate-token"}
                    if auth else {})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read().decode())

            status, health = call("GET", "/healthz", auth=False)
            if status != 200 or health["status"] != "ok":
                return f"healthz broken: {health}"
            status, body = call("GET", "/api/v1/conversations")
            if status != 200:
                return f"auth rejected valid token: {status}"
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/v1/conversations",
                method="GET")
            try:
                urllib.request.urlopen(req, timeout=5)
                return "missing token accepted"
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    return f"expected 401, got {exc.code}"
            _, meta = call("POST", "/api/v1/conversations",
                           {"workspace": "."})
            cid = meta["id"]
            _, run = call("POST",
                          f"/api/v1/conversations/{cid}/messages",
                          {"text": "ping"})
            if run.get("reason") != "answered":
                return f"sync run broken: {run}"
            return True
        finally:
            httpd.shutdown()
            httpd.server_close()


def check_cli_demo():
    import subprocess
    with tempfile.TemporaryDirectory(prefix="ptah-gate-cli-") as tmp:
        proc = subprocess.run(
            [sys.executable, "-m", "ptah", "run", "--demo",
             "--workspace", tmp],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            tail = (proc.stdout + proc.stderr).strip()[-300:]
            return f"demo exit={proc.returncode}: {tail}"
        marker = os.path.join(tmp, "PTAH_DEMO.txt")
        if not os.path.isfile(marker):
            return "demo produced no artifact"
        return True


def check_unittest_suite():
    """Run the unit suite; retry once - under battery load a single
    dropped server frame can error one network test, and the fleet's
    sentinel convention is remediated retry, not instant red."""
    loader = unittest.TestLoader()
    for attempt in (1, 2):
        suite = loader.discover(os.path.join(HERE, "tests"),
                                top_level_dir=ROOT)
        buffer = io.StringIO()
        runner = unittest.TextTestRunner(verbosity=0, stream=buffer)
        result = runner.run(suite)
        if result.wasSuccessful():
            return True
        if attempt == 1:
            time.sleep(1.0)               # let sockets/threads settle
            continue
        detail = []
        for test, tb in result.errors + result.failures:
            detail.append(f"{test} -> {tb.strip().splitlines()[-1]}")
        return (f"{len(result.failures)} failures, "
                f"{len(result.errors)} errors in unit suite: "
                f"{'; '.join(detail)[:400]}")


CHECKS = [
    ("fleet identity + owned ports", lambda: check_fleet_identity()),
    ("security classification matrix", lambda: check_security_matrix()),
    ("workspace escape defense", lambda: check_workspace_escapes()),
    ("file editor safety contract", lambda: check_editor_contract()),
    ("terminal scope + tree kill timeout",
     lambda: check_terminal_scoped_and_timed()),
    ("builtin knowledge cards", lambda: check_skills_builtin()),
    ("condenser budget + determinism", lambda: check_condenser()),
    ("llm transient retry transport", lambda: check_llm_retry()),
    ("lm studio env seam offline-safe", lambda: check_lmstudio_seam()),
    ("end-to-end scripted solve", lambda: check_end_to_end_solve()),
    ("confirmation pause/resume cycle",
     lambda: check_confirmation_cycle()),
    ("hard-deny enforcement", lambda: check_denial_enforcement()),
    ("stuck detector", lambda: check_stuck_detector()),
    ("REST server smoke (auth + sync run)",
     lambda: check_server_smoke()),
    ("CLI offline demo", lambda: check_cli_demo()),
    ("unit test suite green", lambda: check_unittest_suite()),
]


def main():
    passed = 0
    failures = []
    for name, fn in CHECKS:
        try:
            result = fn()
        except Exception as exc:      # noqa: BLE001 - gates report, not crash
            result = f"raised {type(exc).__name__}: {exc}"
        if result is True:
            passed += 1
            print("[ok]   %s" % name)
        else:
            failures.append(name)
            print("[FAIL] %s -> %s" % (name, result))
    total = len(CHECKS)
    print("\n%d/%d checks passed" % (passed, total))
    if failures:
        print("failing: %s" % ", ".join(failures))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
