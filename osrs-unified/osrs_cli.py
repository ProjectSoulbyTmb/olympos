"""Unified command-line interface for osrs-unified.

Subcommands pass through to each sub-project's own argparse parser, so all
flags from bench.py / train.py / evaluate.py / tools/update_knowledge.py
work unchanged:

    osrs bench   --task wc_xp --code-file strategies\\example_bot.py
    osrs train   --name v3 --iters 200 --episodes 40
    osrs eval    runs\\v2\\ckpt_latest.pt
    osrs knowledge            (refresh GE prices + wiki KB)
    osrs mind status          (moderator/engineer report)
    osrs mind patrol --loop 60
    osrs mind release --level minor
    osrs version

Environment:
    OSRS_ROOT   override the root used for wiki/, knowledge/ and runs/
                artifacts (useful when installed into site-packages).
"""
import argparse
import os
import runpy
import sys


def _run_module_main(module_name, argv, prog):
    mod = __import__(module_name)
    sys.argv = [prog] + list(argv)
    mod.main()


def cmd_bench(argv):
    _run_module_main("bench", argv, "osrs bench")


def cmd_train(argv):
    _run_module_main("train", argv, "osrs train")


def cmd_eval(argv):
    _run_module_main("evaluate", argv, "osrs eval")


def cmd_knowledge(argv):
    import bench
    script = os.path.join(os.path.dirname(os.path.abspath(bench.__file__)),
                          "tools", "update_knowledge.py")
    if not os.path.exists(script):
        script = os.path.join("tools", "update_knowledge.py")
    sys.argv = ["osrs knowledge"] + list(argv)
    runpy.run_path(script, run_name="__main__")


def cmd_mind(argv):
    from mind import daemon
    rc = daemon.main(list(argv))
    return rc if isinstance(rc, int) else 0


def cmd_version(_argv):
    from importlib.metadata import PackageNotFoundError, version
    try:
        v = version("osrs-unified")
    except PackageNotFoundError:
        v = "1.0.0+dev"
    print(f"osrs-unified {v}")
    return 0


COMMANDS = {
    "bench": ("run the skilling-agent benchmark (manual or LLM mode)", cmd_bench),
    "train": ("train the PvP PPO agent (self-play)", cmd_train),
    "eval": ("evaluate PvP checkpoints W/D/L", cmd_eval),
    "knowledge": ("refresh OSRS ground-truth data (GE prices + wiki)",
                  cmd_knowledge),
    "mind": ("autonomous moderator/engineer: status|patrol|update-data|"
             "release|install-tasks", cmd_mind),
    "version": ("print package version", cmd_version),
}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="osrs",
        description="osrs-unified: skilling LLM agent + PvP RL, one CLI")
    sub = ap.add_subparsers(dest="command", metavar="command")
    for name, (help_text, _fn) in COMMANDS.items():
        sub.add_parser(name, help=help_text)
    args, rest = ap.parse_known_args(argv)

    if args.command is None:
        ap.print_help()
        return 0
    fn = COMMANDS[args.command][1]
    rc = fn(rest if args.command != "version" else [])
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
