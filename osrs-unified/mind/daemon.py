import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mind import builder, engineer, healer, knowledge_engine, metrics
from mind import moderator, network, releaser, scheduler  # noqa: E402
from mind.sentinel import Sentinel  # noqa: E402
from mind.state import MindState  # noqa: E402


def root_arg(argv):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--root", default=None)
    args, _ = ap.parse_known_args(argv)
    root = args.root or os.environ.get("OSRS_ROOT")
    if not root:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.abspath(root)


def cmd_status(root, state):
    findings = moderator.patrol(root)
    version = releaser.read_version(root)
    dirty = releaser.git_dirty(root)
    tags = releaser._git(root, "tag", "--list").stdout.split()
    status = {
        "version": version,
        "latest_tag": sorted(tags)[-1] if tags else None,
        "working_tree_dirty": dirty,
        "findings": [f.as_dict() for f in findings],
        "critical": sum(1 for f in findings if f.severity == "critical"),
        "auto_fixed": sum(1 for f in findings if f.action == "auto-fixed"),
        "recent_events": state.recent(15),
    }
    state.write_status(status)
    print(f"MIND status for {os.path.basename(root)}")
    print(f"  version      : {version} "
          f"(tag: {status['latest_tag']}, dirty: {dirty})")
    print(f"  findings     : {len(findings)} "
          f"(critical={status['critical']}, auto-fixed={status['auto_fixed']})")
    for f in findings:
        print(f"    {f}")
    return 2 if status["critical"] else 0


def cmd_patrol(root, state, loop=0, llm=False, base_url=None, model=None,
               skip_tests=False):
    while True:
        t0 = time.time()
        state.log("moderator", "patrol-start")
        findings = moderator.patrol(root)
        fixed = sum(1 for f in findings if f.action == "auto-fixed")
        critical = [f for f in findings if f.severity == "critical"]
        state.log("moderator", "patrol-done",
                  f"{len(findings)} findings, {fixed} auto-fixed")
        test_result = {"ok": True, "ran": 0}
        if not critical and not skip_tests:
            state.log("engineer", "tests-start")
            test_result = engineer.run_tests(root)
            state.log("engineer", "tests-done",
                      f"ok={test_result['ok']} ran={test_result['ran']} "
                      f"({test_result['duration_s']}s)")
            if not test_result["ok"]:
                advice = engineer.diagnose(test_result)
                for a in advice:
                    state.log("engineer", "diagnosis",
                              f"[{a['kind']}] {a['fix']}")
                healed = engineer.auto_heal(root, state)
                for h in healed:
                    state.log("engineer", "healed", h)
                if llm and all(a["kind"] != "auto-fixable" for a in advice):
                    result = engineer.llm_diagnose(root, test_result,
                                                   base_url, model)
                    state.log("engineer", "llm-proposal",
                              result.get("saved", result.get("error", "")))
        state.write_status({
            "last_patrol": time.time(),
            "patrol_seconds": round(time.time() - t0, 1),
            "findings": [f.as_dict() for f in findings],
            "tests_ok": test_result["ok"],
            "tests_ran": test_result.get("ran", 0),
            "healthy": not critical and test_result["ok"],
        })
        try:
            _relay(root).publish("mind.status", {
                "findings": len(findings),
                "critical": len(critical),
                "tests_ok": test_result["ok"]})
        except Exception:
            pass
        if loop <= 0:
            return 0 if (test_result["ok"] and not critical) else 1
        time.sleep(loop * 60)


def cmd_update_data(root, state):
    tool = os.path.join(root, "tools", "update_knowledge.py")
    state.log("engineer", "data-refresh-start")
    proc = subprocess.run([sys.executable, tool], cwd=root,
                          capture_output=True, text=True,
                          errors="replace", timeout=600,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    ok = proc.returncode == 0
    state.log("engineer", "data-refresh-done", f"ok={ok}")
    if not ok:
        state.log("engineer", "data-refresh-error",
                  (proc.stderr or "")[-500:])
    return 0 if ok else 1


def cmd_release(root, state, level="patch", dry_run=False, no_build=False):
    plan = releaser.release(root, level=level, dry_run=dry_run,
                            do_build=not no_build,
                            log=lambda m: state.log("releaser", "build", m))
    print(json.dumps({k: v for k, v in plan.items() if k != "changelog"},
                     indent=1))
    if dry_run:
        print("\nproposed changelog:")
        for b in plan.get("changelog", []):
            print(f"  {b}")
        return 0
    if plan.get("error"):
        state.log("releaser", "release-failed", plan["error"])
        return 1
    state.log("releaser", "released",
              f"{plan['current']} -> {plan['target']}"
              + (f" zip={plan['zip']}" if plan.get("zip") else ""))
    return 0


def cmd_install_tasks(root, state):
    py = sys.executable
    daemon = os.path.join(root, "mind", "daemon.py")
    tasks = [
        ("OSRS Mind Patrol",
         [py, "-m", "mind.daemon", "--root", root, "patrol"], "HOURLY"),
        ("OSRS Knowledge Refresh",
         [py, os.path.join(root, "tools", "update_knowledge.py")], "HOURLY"),
    ]
    results = []
    for name, cmd_parts, sched in tasks:
        tr = " ".join(f'"{p}"' if " " in p else p for p in cmd_parts)
        r = subprocess.run(["schtasks", "/Create", "/F", "/TN", name,
                            "/TR", tr, "/SC", sched],
                           capture_output=True, text=True)
        ok = r.returncode == 0
        results.append((name, ok, (r.stderr or "").strip()))
        state.log("moderator", "install-task", f"{name}: ok={ok}")
    for name, ok, err in results:
        print(f"  {'OK ' if ok else 'ERR'} {name}"
              + (f" - {err}" if err else ""))
    failed = [r for r in results if not r[1]]
    if any("Access is denied" in e.lower() for _, _, e in failed):
        print("\nrun this shell as Administrator to register tasks")
    return 0 if all(ok for _, ok, _ in results) else 1


def _relay(root):
    from mind.bus import EventBus
    return EventBus(root)


def cmd_relay_status(root, state):
    bus = _relay(root)
    pending = bus.pending()
    print(f"relay spool: {len(pending)} pending, "
          f"{len(bus.recent(100))} archived recently")
    for evt in pending:
        print(f"  queued [{evt['from']}] {evt['type']} {evt['id']}")
    for evt in bus.recent(8):
        print(f"  {evt['status']:<6} [{evt['from']}] {evt['type']} "
              f"-> {str(evt.get('result', {}))[:90]}")
    return 0


def cmd_relay_publish(root, state, type_, payload_json=None):
    import json as _json
    payload = {}
    if payload_json:
        try:
            payload = _json.loads(payload_json)
        except _json.JSONDecodeError as e:
            print(f"bad json: {e}")
            return 2
    eid = _relay(root).publish(type_, payload,
                               source="mind"
                               if type_.startswith("mind.") else "thoth")
    print(f"published {eid}")
    return 0


def cmd_relay_pump(root, state, timeout=1800, execute=False):
    import subprocess as sp
    bus = _relay(root)
    jobs = bus.pending(type_="mind.job.improve_strategy")
    diag_jobs = bus.pending(type_="mind.job.diagnose")
    print(f"pump: {len(jobs)} strategy job(s), {len(diag_jobs)} "
          f"diagnostic job(s), execute={execute}")
    for evt in jobs + diag_jobs:
        if not execute:
            continue
        p = evt.get("payload", {})
        try:
            bus.take(evt["id"])
        except FileNotFoundError:
            continue
        if evt["type"] == "mind.job.improve_strategy":
            task = p.get("task", "wc_xp")
            cmd = [sys.executable, os.path.join(root, "bench.py"),
                   "--task", task,
                   "--rounds", str(int(p.get("rounds", 4))),
                   "--ticks", str(int(p.get("ticks", 2000))),
                   "--base-url", p.get("base_url",
                                       os.environ.get(
                                           "LLM_BASE_URL",
                                           "http://localhost:11434/v1"))]
            if p.get("model"):
                cmd += ["--model", p["model"]]
            state.log("relay", "job-start", f"{evt['id']} task={task}")
            try:
                proc = sp.run(cmd, cwd=root, capture_output=True,
                              text=True, errors="replace", timeout=timeout,
                              creationflags=subprocess.CREATE_NO_WINDOW)
                best_file = os.path.join(root, "runs",
                                         f"{task}_best.json")
                best = None
                if os.path.exists(best_file):
                    import json as _json
                    with open(best_file, encoding="utf-8") as f:
                        best = (_json.load(f) or {}).get("score")
                ok = proc.returncode == 0 and best is not None
                bus.complete(evt["id"], {"ok": ok,
                                         "returncode": proc.returncode,
                                         "task": task, "best_score": best},
                             ok=ok)
                state.log("relay", "job-done",
                          f"{evt['id']} ok={ok} best={best}")
            except sp.TimeoutExpired:
                bus.fail(evt["id"], f"timed out after {timeout}s")
                state.log("relay", "job-timeout", evt["id"])
        else:
            tr = engineer.run_tests(root)
            result = engineer.llm_diagnose(root, tr)
            bus.complete(evt["id"], {"tests_ok": tr["ok"],
                                     **{k: v for k, v in result.items()
                                        if k != "answer"}},
                         ok=bool(result.get("saved")))
    return 0


def cmd_venus(root, state, execute=False):
    from mind import venus_link
    summary = venus_link.drain(root, state, execute=execute)
    mode = "executed" if execute else "preview"
    print(f"venus link ({mode}): {summary['pending']} pending, "
          f"{summary['executed']} executed")
    for r in summary["results"]:
        print(f"  {r['id']} {r['action']} ok={r['ok']}")
    return 0


def cmd_heal(root, state, dry_run=False, verify=False):
    from mind import healer
    result = healer.heal(root, dry_run=dry_run, verify=verify,
                         log=lambda m: state.log("healer", "verify", m))
    print(f"healer: {result['count']} action(s)"
          f"{' (dry-run)' if dry_run else ''}")
    for a in result["actions"]:
        print(f"  - {a}")
    if result["verified"] is not None:
        print(f"verification: {result['verified']}")
    return 0


def cmd_build(root, state, exe=True):
    from mind import builder
    results = builder.build_all(root, exe=exe,
                                log=lambda m: state.log("builder", "build",
                                                        m[:200]))
    ok = all(v.get("ok") for v in results.values())
    parts = ", ".join(f"{k}={v.get('ok')}" for k, v in results.items())
    print(f"build: {'OK' if ok else 'FAILED'} ({parts})")
    return 0 if ok else 1


def cmd_net(root, state, loop=0, timeout=5.0):
    while True:
        report = network.sweep(root, state, bus=_relay(root),
                               timeout=timeout)
        suggestions = network.heal_suggestions(report)
        for s in suggestions:
            state.log("network", "suggestion", s)
        print(f"network sweep: healthy={report['healthy']} "
              f"degraded={report['degraded']} down={report['down']}")
        for e in report["endpoints"]:
            lat = f"{e['latency_ms']}ms" if e.get("latency_ms") is not None \
                else "-"
            print(f"  {e['name']:<16} {e['status']:<9} {lat:>8}  "
                  f"{e.get('role', '')}")
        if not loop:
            return 0 if report["down"] == 0 and \
                report["healthy"] > 0 else 1
        time.sleep(loop * 60)


def cmd_revise(root, state, fetch=True):
    status = knowledge_engine.revision_status(root, fetch=fetch)
    print(f"revision parity: xp_ok={status['xp_parity_ok']} "
          f"fetched={status['fetched']} "
          f"latest='{status['latest_update_title']}'")
    for f in status["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    return 2 if any(f["severity"] == "critical"
                    for f in status["findings"]) else 0


def cmd_metrics(root, state):
    entry = metrics.snapshot(root)
    s = metrics.summary(root)
    print(f"metrics: sample #{s.get('samples', '?')} "
          f"version={entry.get('version')} findings={entry['findings']}")
    for task, trend in s.get("task_trends", {}).items():
        print(f"  {task}: {trend['first']} -> {trend['last']} "
              f"(delta {trend['delta']:+})")
    return 0


def cmd_schedule(root, state, args_line):
    sub = args_line[0] if args_line else "list"
    if sub == "list":
        for job in scheduler.list_jobs(state):
            last = job.get("last_run")
            age = f"{(time.time() - last) / 60:.0f}m ago" if last else "never"
            print(f"  {job['name']:<22} every {job['every_minutes']}m  "
                  f"last={age}")
        return 0
    if sub == "add" and len(args_line) >= 3:
        scheduler.add_job(state, args_line[1], int(args_line[2]))
        print(f"added {args_line[1]} every {args_line[2]}m")
        return 0
    if sub == "remove" and len(args_line) >= 2:
        scheduler.remove_job(state, args_line[1])
        print(f"removed {args_line[1]}")
        return 0
    if sub == "tick":
        due = scheduler.tick(state)
        print("due now: " + (", ".join(due) or "nothing"))
        for name in due:
            if name == "patrol":
                cmd_patrol(root, state, loop=0)
            elif name == "knowledge-refresh":
                cmd_update_data(root, state)
            elif name == "network-check":
                cmd_net(root, state)
            elif name == "metrics-snapshot":
                cmd_metrics(root, state)
        return 0
    print("usage: schedule list|add <name> <minutes>|remove <name>|tick")
    return 2


def cmd_autonomic(root, state, dry_run=False, no_release=False):
    plan = []
    steps = {}

    findings = moderator.patrol(root)
    critical = sum(1 for f in findings if f.severity == "critical")
    fixed = sum(1 for f in findings if f.action == "auto-fixed")
    steps["moderator"] = {"findings": len(findings), "critical": critical,
                          "auto_fixed": fixed}
    plan.append(f"moderator: {len(findings)} findings ({critical} critical)")

    heal = healer.heal(root, dry_run=dry_run)
    steps["healer"] = heal
    plan.append(f"healer: {heal['count']} repair(s)")

    rev = knowledge_engine.revision_status(root)
    steps["revision"] = {"parity_ok": rev["xp_parity_ok"],
                         "new_upstream": any(
                             f["area"] == "revision" for f in rev["findings"])}
    plan.append(f"revision parity ok={rev['xp_parity_ok']}")

    tr = engineer.run_tests(root)
    steps["tests"] = {"ok": tr["ok"], "ran": tr["ran"]}
    plan.append(f"tests: ok={tr['ok']} ran={tr['ran']}")
    if not tr["ok"]:
        advice = engineer.diagnose(tr)
        steps["diagnosis"] = advice
        plan.append(f"diagnosis: {advice}")

    alerts = Sentinel(root, state).sweep()
    steps["sentinel_alerts"] = alerts
    plan.append(f"sentinel alerts: {len(alerts)}")

    net = network.sweep(root, state, bus=_relay(root))
    steps["network"] = {"healthy": net["healthy"],
                        "degraded": net["degraded"],
                        "down": net["down"],
                        "offline_mode": net["healthy"] == 0}
    plan.append(f"network: {net['healthy']} healthy, "
                f"{net['degraded']} degraded, {net['down']} down")
    if net["healthy"] == 0:
        plan.append("network: offline mode - deferring release/build")
        no_release = True

    dirty = releaser.git_dirty(root)
    green = tr["ok"] and critical == 0 and not dry_run
    if dirty and green and not no_release:
        level = "minor" if any(f["area"] == "parity"
                               for f in rev["findings"]) else "patch"
        plan.append(f"release: pending changes + green -> would bump "
                    f"{level}" + (" (skipped: dry-run)" if dry_run else ""))
        if not dry_run:
            rel = releaser.release(root, level=level, do_build=True,
                                   log=lambda m: state.log(
                                       "releaser", "build", m[:200]))
            steps["release"] = {k: v for k, v in rel.items()
                                if k != "changelog"}
    elif dirty:
        plan.append(f"release: skipped ({'dry-run' if dry_run else
                     'red tests/critical findings'})")

    try:
        _relay(root).publish("mind.status", {
            "autonomic": True, "steps": steps})
    except Exception:
        pass

    print("AUTONOMIC PLAN / RESULTS")
    for line in plan:
        print(f"  - {line}")
    return 0 if (tr["ok"] and critical == 0) else 1


def _net_policy(root):
    from mind.net.policy import NetPolicy
    return NetPolicy(root)


def cmd_net_serve(root, state, port=5731, host="127.0.0.1"):
    from mind.net.channel import MindChannelServer
    server = MindChannelServer(root, host=host, port=port,
                               policy=_net_policy(root))
    actual = server.start()
    state.log("net", "channel-listening", f"{host}:{actual}")
    print(f"MIND channel listening on {host}:{actual} "
          f"(Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("channel stopped")
    return 0


def cmd_net_send(root, state, host, port, type_, payload_json=None):
    import json as _json
    payload = {}
    if payload_json:
        try:
            payload = _json.loads(payload_json)
        except _json.JSONDecodeError as e:
            print(f"bad json: {e}")
            return 2
    from mind.net.channel import ChannelClient
    client = ChannelClient(host, port)
    try:
        evt = client.send(type_, payload)
        print(f"sent {evt['id']}")
        return 0
    finally:
        client.close()


def cmd_net_gym(root, state, port=43594, host="127.0.0.1"):
    from mind.net.gym import GymServer
    server = GymServer(host=host, port=port, policy=_net_policy(root))
    actual = server.start()
    state.log("net", "gym-listening", f"{host}:{actual}")
    print(f"PvP gym serving {host}:{actual} (wire: RelayPlugin-compatible)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("gym stopped")
    return 0


def cmd_net_policy(root, state, args_line):
    policy = _net_policy(root)
    sub = args_line[0] if args_line else "show"
    if sub == "show":
        print(json.dumps(policy.config, indent=1))
        return 0
    if sub == "allow" and len(args_line) >= 2:
        host = args_line[1]
        port = int(args_line[2]) if len(args_line) > 2 \
            and args_line[2] != "*" else "*"
        if len(args_line) > 3 and args_line[3] == "listen":
            policy.allow_listener(host, port)
        else:
            policy.allow_outbound(host, port)
        print(f"allowed {host}:{port}")
        return 0
    if sub == "deny" and len(args_line) >= 2:
        policy.deny_outbound(args_line[1])
        print(f"denied outbound {args_line[1]}")
        return 0
    print("usage: net policy show|allow <host> [port|*] [listen]|"
          "deny <host>")
    return 2


def cmd_net_sources(root, state, name="all"):
    from mind.net import sources
    policy = _net_policy(root)
    if name == "all":
        results = sources.pull_all(root, policy,
                                   log=lambda m: state.log("net", "pull", m))
    else:
        results = {name: sources.pull(root, policy, name,
                                      log=lambda m: state.log(
                                          "net", "pull", m))}
    ok = all(r.get("ok") for r in results.values())
    for src, r in results.items():
        status = "OK" if r.get("ok") else f"ERR {r.get('error')}"
        print(f"  {status:<40} {src}")
    rev = sources.revision_from_runelite(root)
    if rev:
        print(f"current OSRS revision via runelite: {rev}")
    return 0 if ok else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = root_arg(argv)
    state = MindState(root)
    rest = argv
    for flag in ("--root",):
        if flag in rest:
            i = rest.index(flag)
            del rest[i:i + 2]
    cmd = rest[0] if rest else "status"
    rest = rest[1:]

    ap = argparse.ArgumentParser(prog="osrs mind")
    ap.add_argument("--loop", type=int, default=0, metavar="MINUTES",
                    help="keep patrolling every N minutes")
    ap.add_argument("--llm", action="store_true",
                    help="consult local LLM for unexplained failures")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--level", choices=["patch", "minor", "major"],
                    default="patch")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    a, extra = ap.parse_known_args(rest)

    if cmd == "status":
        return cmd_status(root, state)
    if cmd == "patrol":
        return cmd_patrol(root, state, loop=a.loop, llm=a.llm,
                          base_url=a.base_url, model=a.model,
                          skip_tests=a.skip_tests or bool(extra))
    if cmd == "update-data":
        return cmd_update_data(root, state)
    if cmd == "release":
        return cmd_release(root, state, level=a.level, dry_run=a.dry_run,
                           no_build=a.no_build)
    if cmd == "install-tasks":
        return cmd_install_tasks(root, state)
    if cmd == "heal":
        return cmd_heal(root, state, dry_run=a.dry_run,
                        verify=extra and "verify" in extra)
    if cmd == "build":
        return cmd_build(root, state, exe=not a.no_build)
    if cmd == "revise":
        return cmd_revise(root, state, fetch=not extra or "offline"
                          not in extra)
    if cmd == "metrics":
        return cmd_metrics(root, state)
    if cmd == "net":
        ap3 = argparse.ArgumentParser(prog="osrs mind net")
        ap3.add_argument("--loop", type=int, default=0, metavar="MINUTES")
        ap3.add_argument("--timeout", type=float, default=5.0)
        a3, _ = ap3.parse_known_args(rest)
        return cmd_net(root, state, loop=a3.loop, timeout=a3.timeout)
    if cmd == "schedule":
        return cmd_schedule(root, state, rest)
    if cmd == "autonomic":
        return cmd_autonomic(root, state, dry_run=a.dry_run,
                             no_release=a.no_build)
    if cmd == "net":
        sub = rest[0] if rest else "policy"
        rest = rest[1:]
        if sub == "serve":
            return cmd_net_serve(root, state)
        if sub == "gym":
            return cmd_net_gym(root, state)
        if sub == "send" and len(rest) >= 3:
            return cmd_net_send(root, state, rest[0], int(rest[1]),
                                rest[2], rest[3] if len(rest) > 3 else None)
        if sub == "policy":
            return cmd_net_policy(root, state, rest)
        if sub == "sources":
            return cmd_net_sources(root, state,
                                   rest[0] if rest else "all")
        print("usage: net serve|gym|send <host> <port> <type> [json]|"
              "policy ...|sources [name|all]")
        return 2
    if cmd == "venus":
        ap4 = argparse.ArgumentParser(prog="osrs mind venus")
        ap4.add_argument("--execute", action="store_true",
                         help="drain and run queued venus requests")
        a4, _ = ap4.parse_known_args(rest)
        return cmd_venus(root, state, execute=a4.execute)
    if cmd == "relay":
        sub = rest[0] if rest else "status"
        rest = rest[1:]
        if sub == "status":
            return cmd_relay_status(root, state)
        if sub == "pump":
            ap2 = argparse.ArgumentParser()
            ap2.add_argument("--execute", action="store_true")
            ap2.add_argument("--timeout", type=int, default=1800)
            a2, _ = ap2.parse_known_args(rest)
            return cmd_relay_pump(root, state, timeout=a2.timeout,
                                  execute=a2.execute)
        if sub == "publish":
            t = rest[0] if rest else "mind.status"
            payload = rest[1] if len(rest) > 1 else None
            return cmd_relay_publish(root, state, t, payload)
        print(f"unknown relay subcommand '{sub}' - use status|pump|publish")
        return 2
    print(f"unknown command '{cmd}' - use status|patrol|update-data|"
          "release|install-tasks|heal|build|revise|metrics|schedule|"
          "autonomic|relay|net")
    return 2


if __name__ == "__main__":
    sys.exit(main())
