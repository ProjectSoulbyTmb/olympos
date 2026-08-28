"""PTAH CLI - drive the agent kernel from a terminal.

  python -m ptah run "fix the failing test in foo.py"
  python -m ptah run --demo                      # offline scripted demo
  python -m ptah serve [--port 43903] [--token T] [--metrics-path FILE]
  python -m ptah skills list
  python -m ptah benchmark --runs 3 --json
  python -m ptah deploy-check --host 127.0.0.1
  python -m ptah selfcheck                       # gate + hygiene + ledger
  python -m ptah version

Configuration via environment:
  PTAH_LLM_PROVIDER  openai | anthropic | ollama | vllm | lmstudio |
                      llama.cpp | litellm | openai-compatible
  PTAH_LLM_MODEL     provider model id
  PTAH_API_KEY       provider credential (falls back to OPENAI/ANTHROPIC)
  PTAH_BASE_URL      custom OpenAI-compatible endpoint
  PTAH_<BACKEND>_URL / _MODEL
                     backend aliases for OLLAMA, VLLM, LMSTUDIO,
                     LLAMA_CPP and LITELLM

Local aliases are pure configuration - nothing dials a server at boot.
They share the OpenAI-compatible chat transport and do not require an API
key for loopback endpoints. They do not provide proprietary Copilot parity.
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
    primary = LLM(cfg)
    specs = list(getattr(args, "fallback_provider", None) or [])
    if not specs:
        specs = [item.strip() for item in
                 os.environ.get("PTAH_LLM_FALLBACKS", "").split(",")
                 if item.strip()]
    if not specs:
        return primary
    from ptah.backend import BackendRouter
    fallbacks = []
    for index, spec in enumerate(specs):
        provider, model, base_url = _parse_backend_spec(spec)
        fallback_cfg = _fallback_config(provider, model, base_url)
        fallbacks.append((f"fallback-{index + 1}", LLM(fallback_cfg)))
    return BackendRouter([("primary", primary)] + fallbacks)


def _parse_backend_spec(spec):
    """Parse ``provider[=model][@base_url]`` without contacting anything."""
    spec = str(spec).strip()
    base_url = ""
    if "@" in spec:
        spec, base_url = spec.split("@", 1)
    model = ""
    if "=" in spec:
        provider, model = spec.split("=", 1)
    else:
        provider = spec
    return provider.strip(), model.strip(), base_url.strip()


def _fallback_config(provider, model="", base_url=""):
    from ptah.llm import (LLMConfig, LOCAL_ENV_TAGS,
                          LOCAL_PROVIDER_DEFAULTS, normalize_provider)
    provider = normalize_provider(provider)
    tag = LOCAL_ENV_TAGS.get(provider)
    env = os.environ.get
    if tag:
        base_url = base_url or env(f"PTAH_{tag}_URL") or \
            env(f"PTAH_{tag}_BASE_URL") or env(f"PTAH_{tag}_ENDPOINT") or ""
        model = model or env(f"PTAH_{tag}_MODEL") or ""
        key = env(f"PTAH_{tag}_API_KEY") or ""
    else:
        key = env("PTAH_API_KEY") or (
            env("ANTHROPIC_API_KEY") if provider == "anthropic"
            else env("OPENAI_API_KEY")) or ""
    default_url, default_model = LOCAL_PROVIDER_DEFAULTS.get(
        provider, ("", ""))
    return LLMConfig(
        provider=provider,
        model=model or default_model,
        base_url=base_url or default_url,
        api_key=key)


def _brain_from_meta(meta):
    """Honor a conversation-level local backend override without probing."""
    provider = str((meta or {}).get("ptah_llm_provider") or "").strip()
    if not provider:
        return None
    model = str((meta or {}).get("ptah_llm_model") or "").strip()
    base_url = str((meta or {}).get("ptah_llm_base_url") or "").strip()
    from ptah.llm import LLM
    return LLM(_fallback_config(provider, model, base_url))


def _select_brain(args, conversation, shared_brain=None):
    override = _brain_from_meta(getattr(conversation, "meta", None))
    if override is not None:
        return override
    return shared_brain or build_brain(args)


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


def _runner_factory(args, shared_brain=None):
    """Server runner: fresh Agent + LocalWorkspace per conversation."""
    def runner(conversation, text, confirm):
        from ptah.agent import Agent as _A
        from ptah.workspace import LocalWorkspace
        ws = LocalWorkspace(conversation.meta.get("workspace") or ".")
        llm = _select_brain(args, conversation, shared_brain=shared_brain)
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
    from ptah.backend import as_backend_router
    from ptah.server import serve
    store = Store(root=args.store_dir or None)
    brain = build_brain(args)
    router = as_backend_router(brain, metrics_path=args.metrics_path or "")
    interval = getattr(args, "health_interval", 0.0) or 0.0
    if interval > 0:
        router.start_health_monitor(interval_s=interval)
    print(f"ptah/{content.VERSION} serving on "
          f"{args.host}:{args.port} (ctrl-c to stop)")
    try:
        serve(store, _runner_factory(
            args, shared_brain=None if args.demo else brain),
              host=args.host, port=args.port, token=args.token,
              backend_router=router,
              max_active_runs=args.max_active_runs)
    finally:
        if args.metrics_path:
            router.save_metrics(args.metrics_path)
        if interval > 0:
            router.stop_health_monitor()


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
    latencies = []
    actions = answers = 0
    for event in conv.events:
        if event.TYPE == "agent_thought":
            usage = getattr(event, "usage", None) or {}
            tokens_in += usage.get("input", 0)
            tokens_out += usage.get("output", 0)
            latency = getattr(event, "latency_s", None)
            if isinstance(latency, (int, float)):
                latencies.append(float(latency))
        elif event.TYPE == "action":
            actions += 1
        elif event.TYPE == "agent_message":
            answers += 1
    total_latency = round(sum(latencies), 3)
    print(_json.dumps({
        "conversation": conv.id, "status": conv.status,
        "events": len(conv.events), "llm_calls": sum(
            1 for e in conv.events if e.TYPE == "agent_thought"),
        "tokens_in": tokens_in, "tokens_out": tokens_out,
        "latency_s": total_latency,
        "latency_s_avg": round(total_latency / len(latencies), 3)
        if latencies else 0.0,
        "actions": actions, "answers": answers}, indent=2))
    return 0



def cmd_probe(args):
    """Probe a local OpenAI-compatible backend (local-only).
    Prints a JSON summary by default or a human-friendly one-line per key.
    """
    from ptah import llm_probe
    try:
        res = llm_probe.probe_from_env_or_args(args.base_url, args.model,
                                               timeout_s=getattr(args, 'timeout', 5.0))
        out = {
            'base_url': res.base_url,
            'endpoint': res.endpoint,
            'model_requested': res.model_requested,
            'model_reported': res.model_reported,
            'reachable': res.reachable,
            'can_stream': res.can_stream,
            'supports_tool_calls': res.supports_tool_calls,
            'latency_s': res.latency_s,
            'throughput_bytes_per_s': res.throughput_bytes_per_s,
            'response_size': res.response_size,
            'models': res.models,
            'models_error': res.models_error,
        }
        if getattr(args, 'json', False):
            print(json.dumps(out, indent=2))
        else:
            for k, v in out.items():
                print(f"{k}: {v}")
        return 0
    except llm_probe.LLMProbeError as exc:
        # emit structured JSON to stderr when --json is requested
        if getattr(args, 'json', False):
            print(json.dumps({'error': {'kind': exc.kind, 'message': exc.message}}), file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 2
def cmd_benchmark(args):
    """Run repeatable compatibility checks across configured backends."""
    from ptah import llm_probe
    specs = list(getattr(args, "backend", None) or [])
    providers = list(getattr(args, "provider", None) or [])
    if providers:
        model = getattr(args, "model", None) or ""
        base_url = getattr(args, "base_url", None) or ""
        suffix = f"={model}" if model else ""
        suffix += f"@{base_url}" if base_url else ""
        specs.extend(provider + suffix for provider in providers)
    try:
        report = llm_probe.benchmark_backends(
            specs or None,
            runs=getattr(args, "runs", 1),
            timeout_s=getattr(args, "timeout", 5.0))
    except (ValueError, llm_probe.LLMProbeError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        print("backend benchmark "
              f"({report['runs']} run(s), {report['summary']['configured']} configured)")
        for row in report["backends"]:
            label = f"{row['name']} [{row['provider']}]"
            if row["status"] in ("available", "partial"):
                latency = row["latency_s"]["avg"]
                rate = row["throughput_bytes_per_s"]["avg"]
                print(f"  {label}: {row['status']} latency={latency}s "
                      f"throughput={rate}B/s stream={row['can_stream']} "
                      f"tools={row['supports_tool_calls']}")
            else:
                error = (row.get("errors") or [{}])[-1]
                print(f"  {label}: {row['status']} "
                      f"{error.get('kind', 'error')}: {error.get('message', '')}")
    return 0


def cmd_deploy_check(args):
    """Validate binding, authentication, and external TLS expectations."""
    from ptah.deployment import validate_deployment
    token = args.token or os.environ.get("PTAH_SERVER_TOKEN", "")
    report = validate_deployment(
        host=args.host,
        token=token,
        tls_terminated=args.tls_terminated,
        require_tls=args.require_tls,
        allow_insecure=args.allow_insecure)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"deployment: {'READY' if report['ready'] else 'NOT READY'}")
        print(f"host: {report['host']} (loopback={report['is_loopback']})")
        for item in report["errors"]:
            print(f"error: {item['kind']}: {item['message']}")
        for item in report["warnings"]:
            print(f"warning: {item['kind']}: {item['message']}")
    return 0 if report["ready"] else 1


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
    p_run.add_argument(
        "--provider",
        choices=["openai", "anthropic", "ollama", "vllm", "lmstudio",
                 "lm-studio", "lm_studio", "llama.cpp", "llama-cpp",
                 "llamacpp", "llama_cpp", "litellm", "openai-compatible",
                 "openai_compatible", "local", "local-openai"])
    p_run.add_argument("--model")
    p_run.add_argument("--base-url", "--endpoint", dest="base_url")
    p_run.add_argument("--api-key-env",
                       help="env var holding the provider key")
    p_run.add_argument("--fallback-provider", action="append",
                       help="fallback provider[=model][@base_url] (repeatable)")
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
    p_srv.add_argument("--base-url", "--endpoint", dest="base_url")
    p_srv.add_argument("--api-key-env")
    p_srv.add_argument("--policy", default=content.DEFAULT_POLICY)
    p_srv.add_argument("--fallback-provider", action="append",
                       help="fallback provider[=model][@base_url] (repeatable)")
    p_srv.add_argument("--health-interval", type=float, default=0.0,
                       help="opt-in backend probe interval in seconds")
    p_srv.add_argument("--metrics-path",
                       help="persist backend metrics JSON atomically")
    p_srv.add_argument("--max-active-runs", type=int, default=32,
                       help="admission cap for concurrent runs")
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
    p_probe = sub.add_parser('probe', help='probe a local OpenAI-compatible backend')
    p_probe.add_argument('--base-url', '--endpoint', dest='base_url')
    p_probe.add_argument('--model')
    p_probe.add_argument('--timeout', type=float, default=5.0)
    p_probe.add_argument('--json', action='store_true')
    p_probe.set_defaults(fn=cmd_probe)

    p_bench = sub.add_parser("benchmark",
                             help="benchmark configured local backends")
    p_bench.add_argument("--backend", action="append",
                         help="provider[=model][@base_url] (repeatable); "
                              "defaults to PTAH provider and fallbacks")
    p_bench.add_argument("--provider", action="append",
                         help="provider alias (repeatable; use with --model/--base-url)")
    p_bench.add_argument("--model")
    p_bench.add_argument("--base-url", "--endpoint", dest="base_url")
    p_bench.add_argument("--runs", "--repeat", type=int, default=1,
                         help="probe requests per backend")
    p_bench.add_argument("--timeout", type=float, default=5.0)
    p_bench.add_argument("--json", action="store_true")
    p_bench.set_defaults(fn=cmd_benchmark)

    p_deploy = sub.add_parser("deploy-check",
                              help="validate PTAH deployment exposure")
    p_deploy.add_argument("--host", default=content.SERVER_HOST)
    p_deploy.add_argument("--token",
                          help="bearer token (or PTAH_SERVER_TOKEN)")
    p_deploy.add_argument("--tls-terminated", action="store_true",
                          help="declare TLS termination outside PTAH")
    p_deploy.add_argument("--require-tls", action="store_true",
                          help="fail unless external TLS termination is declared")
    p_deploy.add_argument("--allow-insecure", action="store_true",
                          help="explicitly allow non-local plain HTTP exposure")
    p_deploy.add_argument("--json", action="store_true")
    p_deploy.set_defaults(fn=cmd_deploy_check)

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
