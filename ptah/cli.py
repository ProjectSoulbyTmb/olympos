"""PTAH CLI - drive the agent kernel from a terminal.

  python -m ptah run "fix the failing test in foo.py"
  python -m ptah run --demo                      # offline scripted demo
  python -m ptah serve [--port 43903] [--token T]
  python -m ptah skills list
  python -m ptah selfcheck                       # gate + hygiene + ledger
  python -m ptah version

Configuration via environment:
  PTAH_LLM_PROVIDER  openai | anthropic          (default openai)
  PTAH_LLM_MODEL     provider model id
  PTAH_API_KEY       provider credential (falls back to OPENAI/ANTHROPIC)
  PTAH_BASE_URL      custom OpenAI-compatible endpoint (Ollama, vLLM...)
"""

import argparse
import json
import os
import sys
import threading
import time

from ptah import content


# --------------------------------------------------------------- assembly
def build_brain(args):
    """Create the LLM from CLI args / environment; --demo goes offline."""
    if getattr(args, "demo", False):
        from ptah.llm import ScriptedLLM
        from ptah.demo import demo_script
        return ScriptedLLM(demo_script())
    from ptah.llm import LLMConfig, LLM
    cfg = LLMConfig.from_env()
    if getattr(args, "provider", None):
        cfg.provider = args.provider
    if getattr(args, "model", None):
        cfg.model = args.model
    if getattr(args, "base_url", None):
        cfg.base_url = args.base_url
    key_env = getattr(args, "api_key_env", None)
    if key_env:
        cfg.api_key = os.environ.get(key_env, "")
    return LLM(cfg)


def build_agent(llm, workspace_root, policy_name=None, max_iters=None,
                extra_skill_dirs=()):
    from ptah.agent import Agent
    from ptah.security import ConfirmationPolicy
    from ptah.skills import load_skills
    from ptah.tools import default_registry
    registry = default_registry()
    skills = load_skills(content.BUILTIN_SKILLS_DIR,
                         os.path.join(workspace_root, ".ptah", "skills"),
                         *extra_skill_dirs)
    # MCP servers (OpenHands-style dynamic tool integration)
    mcp_cfg = os.path.join(workspace_root, ".ptah", "mcp.json")
    if os.path.isfile(mcp_cfg):
        try:
            from ptah import mcp as mcp_mod
            mcp_mod.register_into(registry, mcp_cfg)
        except Exception:
            pass                                  # MCP never blocks startup
    agent = Agent(llm=llm, registry=registry,
                  policy=ConfirmationPolicy(policy_name or
                                           content.DEFAULT_POLICY),
                 skills=list(skills.values()) if isinstance(skills, dict)
                 else list(skills),
                 max_iterations=max_iters,
                 repo_root=_repo_root(),
                 hooks_config=_load_hooks(workspace_root))
    return agent


def _load_hooks(workspace_root):
    from ptah.hooks import load_hook_config
    return load_hook_config(os.path.join(workspace_root, ".ptah",
                                         "hooks.json"))


def _repo_root():
    here = os.path.dirname(content.data_dir())
    return here if os.path.isdir(os.path.join(here, "zeus")) else ""


def _runner_factory(args):
    """Server runner: fresh Agent + LocalWorkspace per conversation."""
    def runner(conversation, text, confirm):
        from ptah.agent import Agent as _A
        from ptah.workspace import LocalWorkspace
        ws = LocalWorkspace(conversation.meta.get("workspace") or ".")
        llm = build_brain(args)
        agent = build_agent(llm, ws.root,
                            policy_name=getattr(args, "policy", None))
        return agent.run(conversation, text, confirm=confirm, workspace=ws)
    return runner


# ------------------------------------------------------------------ cmds
def cmd_run(args):
    from ptah.agent import Agent
    from ptah.conversation import Conversation
    from ptah.events import FinishedEvent, AgentMessage, DeniedActionEvent, \
        ConfirmationRequiredEvent, ActionEvent, ObservationEvent
    from ptah.workspace import LocalWorkspace

    if not args.task and not args.demo:
        print("error: provide a task (or use --demo)")
        return 2
    task = args.task or "run the offline demo"

    ws = LocalWorkspace(os.path.abspath(args.workspace))
    conv = Conversation.new(root=os.path.join(ws.root, ".ptah", "conversations")
                            if args.state_in_workspace else None,
                            workspace_root=ws.root)
    llm = build_brain(args)
    agent = build_agent(llm, ws.root, policy_name=args.policy,
                        max_iters=args.max_iters)

    def render(e):
        t = e.TYPE
        if t == "action":
            return f"  >> {e.tool} {json.dumps(e.args)[:160]}"
        if t == "observation":
            body = (e.output or e.error or "").strip()
            first = body.splitlines()[0][:160] if body else ""
            mark = "ok" if not e.error else f"exit={e.exit_code}"
            return f"  << ({mark}) {first}"
        if t == "agent_message":
            return f"PTAH: {e.text}"
        if t == "denied_action":
            return f"  XX denied: {e.reason}"
        if t == "confirmation_required":
            return ("  ?? confirmation required "
                    f"({getattr(e, 'risk', '')}): rerun with --confirm")
        if t == "finished":
            return f"[finished: {e.reason}]"
        return None

    before = len(conv.events)
    result = agent.run(conv, task, confirm=args.confirm, workspace=ws)
    for e in conv.events[before:]:
        line = render(e)
        if line and not (args.quiet and not line.startswith(("PTAH:",
                                                             "[finished"))):
            print(line)
    return 0 if result.reason == "answered" else 1


def cmd_serve(args):
    from ptah.conversation import Store
    from ptah.server import serve
    store = Store(root=args.store_dir or None)
    print(f"ptah/{content.VERSION} serving on "
          f"{args.host}:{args.port} (ctrl-c to stop)")
    serve(store, _runner_factory(args), host=args.host, port=args.port,
          token=args.token)


def cmd_skills(args):
    from ptah.skills import load_skills
    dirs = [content.BUILTIN_SKILLS_DIR]
    if args.dir:
        dirs.insert(0, args.dir)
    skills = load_skills(*dirs)
    items = skills.values() if isinstance(skills, dict) else skills
    rows = sorted(items, key=lambda s: s.name)
    if args.json:
        print(json.dumps([{"name": s.name, "triggers": s.triggers,
                           "source": s.source} for s in rows], indent=2))
        return 0
    print(f"{len(rows)} skill(s):")
    for s in rows:
        trig = ", ".join(s.triggers) if s.triggers else "(always off)"
        print(f"  {s.name:<28} triggers: {trig}")
    return 0


def cmd_selfcheck(args):
    """Full automation hygiene: verify gate, store pruning, ledger."""
    import subprocess
    root = _repo_root() or os.getcwd()
    gate = os.path.join(root, "ptah", "verify_ptah.py") \
        if os.path.isdir(root) and os.path.isdir(os.path.join(root, "ptah")) \
        else os.path.join(os.path.dirname(content.data_dir()),
                          "verify_ptah.py")
    t0 = time.time()
    ok = False
    tail = ""
    try:
        proc = subprocess.run([sys.executable, "-u", gate],
                              cwd=root, capture_output=True, text=True,
                              timeout=600)
        ok = proc.returncode == 0
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-400:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        tail = str(exc)
    pruned = 0
    try:
        from ptah.conversation import Store
        pruned = Store().prune(keep_days=args.keep_days)
    except Exception as exc:                       # noqa: BLE001 - reported
        tail += f" | prune error: {exc}"
    secs = round(time.time() - t0, 1)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "ok": ok, "secs": secs, "pruned_conversations": pruned,
             "tail": tail}
    ledger_dir = content.data_dir()
    try:
        os.makedirs(ledger_dir, exist_ok=True)
        with open(os.path.join(ledger_dir, "selfcheck.jsonl"), "a",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    if args.json:
        print(json.dumps(entry, indent=2))
    else:
        verdict = "PASS" if ok else "FAIL"
        print(f"ptah selfcheck: {verdict} ({secs}s, pruned {pruned})")
        print(tail)
    return 0 if ok else 1


def cmd_metrics(args):
    """Token/cost rollup for one conversation (or the latest)."""
    import json as _json
    from ptah.conversation import Store
    store = Store()
    cid = args.conversation
    if not cid:
        metas = store.list()
        if not metas:
            print("no conversations")
            return 1
        cid = metas[0]["id"]
    conv = store.get(cid)
    if conv is None:
        print(f"no such conversation: {cid}")
        return 1
    tokens_in = tokens_out = 0
    actions = answers = 0
    for event in conv.events:
        if event.TYPE == "agent_thought":
            usage = getattr(event, "usage", None) or {}
            tokens_in += usage.get("input", 0)
            tokens_out += usage.get("output", 0)
        elif event.TYPE == "action":
            actions += 1
        elif event.TYPE == "agent_message":
            answers += 1
    print(_json.dumps({
        "conversation": conv.id, "status": conv.status,
        "events": len(conv.events), "llm_calls": sum(
            1 for e in conv.events if e.TYPE == "agent_thought"),
        "tokens_in": tokens_in, "tokens_out": tokens_out,
        "actions": actions, "answers": answers}, indent=2))
    return 0


def cmd_version(_args):
    print(f"ptah {content.VERSION}")
    return 0


# ------------------------------------------------------------------ main
def build_parser():
    ap = argparse.ArgumentParser(prog="ptah", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="one-shot task run")
    p_run.add_argument("task", nargs="?", default="",
                       help="mission text (optional with --demo)")
    p_run.add_argument("--workspace", default=".")
    p_run.add_argument("--demo", action="store_true",
                       help="offline scripted brain (no API needed)")
    p_run.add_argument("--provider", choices=["openai", "anthropic"])
    p_run.add_argument("--model")
    p_run.add_argument("--base-url")
    p_run.add_argument("--api-key-env",
                       help="env var holding the provider key")
    p_run.add_argument("--policy", choices=["auto", "confirm-risky",
                                            "confirm-all"],
                       default=content.DEFAULT_POLICY)
    p_run.add_argument("--confirm", action="store_true",
                       help="approve one pending privileged action")
    p_run.add_argument("--max-iters", type=int,
                       default=content.DEFAULT_MAX_ITERATIONS)
    p_run.add_argument("--quiet", action="store_true")
    p_run.add_argument("--state-in-workspace", action="store_true",
                       help="keep conversation log inside the workspace")
    p_run.set_defaults(fn=cmd_run)

    p_srv = sub.add_parser("serve", help="local REST control plane")
    p_srv.add_argument("--host", default=content.SERVER_HOST)
    p_srv.add_argument("--port", type=int, default=content.SERVER_PORT)
    p_srv.add_argument("--token", help="require bearer token on /api/*")
    p_srv.add_argument("--store-dir", help="override conversation store dir")
    p_srv.add_argument("--demo", action="store_true")
    p_srv.add_argument("--provider"); p_srv.add_argument("--model")
    p_srv.add_argument("--base-url"); p_srv.add_argument("--api-key-env")
    p_srv.add_argument("--policy", default=content.DEFAULT_POLICY)
    p_srv.set_defaults(fn=cmd_serve)

    p_sk = sub.add_parser("skills", help="list knowledge cards")
    p_sk.add_argument("action", nargs="?", default="list",
                      choices=["list"])
    p_sk.add_argument("--dir", help="extra skills directory")
    p_sk.add_argument("--json", action="store_true")
    p_sk.set_defaults(fn=cmd_skills, action_default="list")

    p_sc = sub.add_parser("selfcheck", help="verify gate + hygiene + ledger")
    p_sc.add_argument("--json", action="store_true")
    p_sc.add_argument("--keep-days", type=int, default=14)
    p_sc.set_defaults(fn=cmd_selfcheck)

    p_m = sub.add_parser("metrics", help="token/usage rollup for a conversation")
    p_m.add_argument("conversation", nargs="?", default="",
                     help="conversation id (default: latest)")
    p_m.set_defaults(fn=cmd_metrics)

    p_v = sub.add_parser("version", help="print version")
    p_v.set_defaults(fn=cmd_version)
    return ap


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "action_default"):
        if not getattr(args, "action", None):
            args.action = args.action_default
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
