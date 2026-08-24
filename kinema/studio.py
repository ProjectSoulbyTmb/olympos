"""studio - the kinema command line + interactive menu.

  python -m kinema doctor
  python -m kinema analyze --root D:\\my-footage
  python -m kinema sample --input clip.mp4 --count 8 --out frames/
  python -m kinema produce --job job.json
  python -m kinema produce --demo          # end-to-end offline demo
  python -m kinema catalog --profile
  python -m kinema watch --once | watch --loop
  python -m kinema ai status | ai template out.json | ai run wf.json

Bare `python -m kinema` opens the interactive studio menu.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kinema import DATA_DIR, VERSION  # noqa: E402

import ffmpeg_tools as ft  # noqa: E402


def _log(msg):
    print("[kinema] %s" % msg)


# ---------------------------------------------------------------- commands

def cmd_doctor(_args):
    print("kinema v%s - private offline video studio" % VERSION)
    exe = ft.ffmpeg_path()
    print("ffmpeg   : %s (%s)" % (exe or "NOT FOUND",
                                  ft.version() or "-"))
    if not ft.available():
        print("           install with: powershell -File "
              "kinema\\setup_kinema_stack.ps1")
    import produce
    enc = None
    try:
        enc = produce.pick_encoder()
    except Exception:  # noqa: BLE001
        pass
    print("encoder  : %s" % (enc or "n/a"))
    import ai_bridge
    stats = None
    try:
        stats = ai_bridge.status()
    except Exception:  # noqa: BLE001
        pass
    print("ai tier  : %s" % (
        "ComfyUI up (%s)" % (stats.get("system", {})
                             .get("comfyui_version", "?"))
        if stats else "offline (optional; see setup_kinema_stack.ps1 -Ai)"))
    import watcher
    cfg = watcher.load_config()
    print("watch    : %d root(s) configured in %s"
          % (len(cfg.get("roots") or []), watcher.config_path()))
    cat = os.path.join(DATA_DIR, "catalog.json")
    n = 0
    if os.path.isfile(cat):
        with open(cat, encoding="utf-8") as fh:
            n = len(json.load(fh).get("entries", {}))
    print("catalog  : %s (%d videos learned)" % ("present" if n else
                                                 "empty", n))
    return 0


def cmd_analyze(args):
    from analysis import analyze_folder
    result = analyze_folder(args.root, catalog_path=args.catalog,
                            force=args.force, log=_log)
    print(json.dumps(result["style_profile"], indent=1))
    return 0


def cmd_sample(args):
    from analysis import extract_frames
    frames = extract_frames(args.input, args.out, count=args.count)
    if args.format and args.format.lower() not in ("ppm", ""):
        exe = ft.ffmpeg_path()
        converted = []
        for fp in frames:
            dst = os.path.splitext(fp)[0] + "." + args.format.lower()
            rc, _, _ = ft.run([exe, "-y", "-loglevel", "error",
                               "-i", fp, dst], timeout=120)
            if rc == 0:
                converted.append(dst)
        for fp in frames:
            try:
                os.remove(fp)
            except OSError:
                pass
        frames = converted
    for fp in frames:
        print(fp)
    return 0


DEMO_JOB_NAME = "demo_reel"


def cmd_produce(args):
    if not ft.available():
        print("ffmpeg not found - run setup_kinema_stack.ps1 first",
              file=sys.stderr)
        return 2
    if args.demo:
        job = build_demo_job(os.getcwd())
        _log("running built-in demo job (synthetic frames -> mp4 -> "
             "gif -> title card)")
    elif args.job:
        with open(args.job, encoding="utf-8") as fh:
            job = json.load(fh)
    else:
        print("nothing to do: pass --job FILE or --demo", file=sys.stderr)
        return 2
    import produce
    report = produce.render(job, base_dir=os.getcwd(), log=_log)
    print(json.dumps(report, indent=1)[:2000])
    return 0 if report.get("ok") else 1


def cmd_catalog(args):
    from analysis import Catalog
    path = args.catalog or os.path.join(DATA_DIR, "catalog.json")
    cat = Catalog(path)
    profile = cat.style_profile()
    print("catalog: %s (%d entries)" % (path, len(cat.entries)))
    print(json.dumps(profile or {}, indent=1))
    if args.list:
        for key, entry in sorted(cat.entries.items()):
            meta = entry.get("meta", {})
            print("- %s | %dx%d | %.1fs | %d scenes"
                  % (entry.get("name"), meta.get("width", 0),
                     meta.get("height", 0), meta.get("duration", 0.0),
                     entry.get("scene_count", 0)))
    return 0


def cmd_watch(args):
    import watcher
    if args.loop:
        watcher.watch(args.interval)
        return 0
    print(json.dumps(watcher.run_once(), indent=1)[:1500])
    return 0


def cmd_watch_config(args):
    import watcher
    cfg = watcher.load_config()
    if args.add_root:
        cfg.setdefault("roots", [])
        root = os.path.abspath(args.add_root)
        if root not in cfg["roots"]:
            cfg["roots"].append(root)
        watcher.save_config(cfg)
        _log("watch root added: %s" % root)
    print(json.dumps(cfg, indent=1))
    return 0


def cmd_ai(args):
    import ai_bridge
    if args.ai_cmd == "status":
        print(json.dumps(ai_bridge.status() or {"online": False},
                         indent=1))
        return 0
    if args.ai_cmd == "template":
        path = ai_bridge.write_template(args.path or
                                        os.path.join(DATA_DIR,
                                                     "ai_workflow.json"))
        print("wrote %s" % path)
        return 0
    if args.ai_cmd == "run":
        with open(args.path, encoding="utf-8") as fh:
            workflow = json.load(fh)
        result = ai_bridge.generate(workflow, args.out or DATA_DIR)
        print(json.dumps(result, indent=1))
        return 0
    return 2


def build_demo_job(base_dir):
    """Synthetic end-to-end demo: pure-python frames -> pngs -> mp4."""
    import imaging
    work = os.path.join(base_dir, "data", "kinema", "demo")
    imgs_dir = os.path.join(work, "frames")
    os.makedirs(imgs_dir, exist_ok=True)
    images = []
    palettes = [(220, 40, 40), (40, 180, 90), (50, 90, 230),
                (240, 200, 40)]
    for i, (r, g, b) in enumerate(palettes):
        w = h = 96
        px = bytearray(w * h * 3)
        for y in range(h):
            shade = y * 255 // h
            for x in range(w):
                o = (y * w + x) * 3
                px[o] = min(255, r * (x * 255 // w) // 255 + shade // 4)
                px[o + 1] = g * shade // 255
                px[o + 2] = b * shade // 255
        ppm = os.path.join(imgs_dir, "c%d.ppm" % i)
        imaging.write_ppm(ppm, w, h, bytes(px))
        png = os.path.join(imgs_dir, "c%d.png" % i)
        exe = ft.ffmpeg_path()
        rc, _, err = ft.run([exe, "-hide_banner", "-loglevel", "error",
                             "-y", "-i", ppm, png], timeout=60)
        if rc != 0:
            raise RuntimeError("png conversion failed: %s" % err[:200])
        os.remove(ppm)
        images.append(png)
    font = None
    from produce import default_font
    font = default_font()
    steps = [
        {"type": "slideshow", "images": [os.path.relpath(p, base_dir)
                                         for p in images],
         "per_image": 1.5, "crossfade": 0.5, "size": "640x360",
         "fps": 24, "output": "reel.mp4"},
        {"type": "fade", "input": "reel.mp4", "output": "reel_faded.mp4",
         "fade_in": 0.5, "fade_out": 0.8},
    ]
    if font:
        steps.append({"type": "text", "input": "reel_faded.mp4",
                      "output": "reel_titled.mp4",
                      "text": "KINEMA demo reel", "fontsize": 36,
                      "position": "bottom"})
    steps.append({"type": "gif", "input":
                  "reel_titled.mp4" if font else "reel_faded.mp4",
                  "output": "reel.gif", "fps": 10, "width": 320})
    return {"name": DEMO_JOB_NAME, "workdir":
            os.path.relpath(work, base_dir), "steps": steps}


# ------------------------------------------------------------------ menu

MENU = """
KINEMA - Riley's private offline video studio (v{version})

 1) doctor            environment check
 2) analyze folder    feed a folder into the learning catalog
 3) sample video      pull preview frames from one file
 4) produce demo      synthetic end-to-end mp4/gif render
 5) produce job       render a job-spec JSON
 6) catalog           show what has been learned (+profile)
 7) watch config      add/list watched roots
 8) watch once        sweep watched roots now
 9) ai tier           local ComfyUI status/template/run
 0) quit
"""


def menu():
    while True:
        print(MENU.format(version=VERSION))
        choice = input("select> ").strip()
        try:
            if choice == "0":
                return 0
            if choice == "1":
                cmd_doctor(None)
            elif choice == "2":
                root = input("folder to learn from> ").strip('" ')
                if root:
                    cmd_analyze(argparse.Namespace(
                        root=root, catalog=None, force=False))
            elif choice == "3":
                vid = input("video path> ").strip('" ')
                out = input("out dir [data/kinema/samples]> ").strip() \
                    or os.path.join(DATA_DIR, "samples")
                if vid:
                    cmd_sample(argparse.Namespace(input=vid, count=8,
                                                  out=out, format="png"))
            elif choice == "4":
                cmd_produce(argparse.Namespace(demo=True, job=None))
            elif choice == "5":
                job = input("job json path> ").strip('" ')
                if job:
                    cmd_produce(argparse.Namespace(demo=False, job=job))
            elif choice == "6":
                show = input("list entries? [y/N]> ").lower() == "y"
                cmd_catalog(argparse.Namespace(catalog=None, list=show))
            elif choice == "7":
                root = input("add watch root (blank to just list)> ")\
                    .strip('" ')
                cmd_watch_config(argparse.Namespace(add_root=root
                                                    or None))
            elif choice == "8":
                cmd_watch(argparse.Namespace(loop=False, interval=None))
            elif choice == "9":
                sub = input("[status/template/run]> ").strip() \
                    or "status"
                path = None
                if sub in ("template", "run"):
                    path = input("file path> ").strip('" ') or None
                cmd_ai(argparse.Namespace(ai_cmd=sub, path=path,
                                          out=None))
        except KeyboardInterrupt:
            return 130
        except Exception as exc:  # noqa: BLE001 - menu never dies
            print("! %s" % exc)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kinema",
                                 description="offline video studio")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)

    p = sub.add_parser("analyze")
    p.add_argument("--root", required=True)
    p.add_argument("--catalog", default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("sample")
    p.add_argument("--input", required=True)
    p.add_argument("--count", type=int, default=8)
    p.add_argument("--out", default=os.path.join(DATA_DIR, "samples"))
    p.add_argument("--format", default="png")
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("produce")
    p.add_argument("--job", default=None)
    p.add_argument("--demo", action="store_true")
    p.set_defaults(func=cmd_produce)

    p = sub.add_parser("catalog")
    p.add_argument("--catalog", default=None)
    p.add_argument("--list", action="store_true")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("watch")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval", type=int, default=None)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("watch-config")
    p.add_argument("--add-root", default=None)
    p.set_defaults(func=cmd_watch_config)

    p = sub.add_parser("ai")
    p.add_argument("ai_cmd", choices=["status", "template", "run"])
    p.add_argument("--path", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_ai)

    args = ap.parse_args(argv)
    if hasattr(args, "func"):
        return args.func(args) or 0
    return menu()


if __name__ == "__main__":
    raise SystemExit(main())
