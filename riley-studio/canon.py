#!/usr/bin/env python3
"""canon - generate Riley Studio's self-canon: a curated body of fully
synthetic reference artwork whose fingerprints teach HAVEN.

    python riley-studio\\canon.py [--base http://127.0.0.1:8288]
                                  [--out haven\\canon] [--only FAMILY]

Provenance law: every piece is generated locally by the quantized
engine; each folder carries metadata.json (prompt, seed, model, engine
version) so the sisters learn from verifiable synthetic origins only.
"""
import argparse
import datetime
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

CANON = [
    {"family": "gothic-victorian",
     "prompt": "victorian gothic cathedral interior, candlelight, "
               "wrought iron arches, ravens on stone gargoyles, fog, "
               "moody chiaroscuro, ornate details, cinematic",
     "negative": "blurry, lowres, watermark, text, oversaturated",
     "width": 512, "height": 768, "seed": 1101},
    {"family": "neon-noir",
     "prompt": "rain-soaked neon city alley at night, reflections on "
               "wet asphalt, magenta and cyan signage, steam vents, "
               "cinematic wide shot, blade runner mood",
     "negative": "daylight, blurry, text, watermark, flat lighting",
     "width": 768, "height": 512, "seed": 1102},
    {"family": "cosmic-sacred",
     "prompt": "colossal nebula seen through a shattered cathedral "
               "dome, stars, gold dust, deep space purples and blues, "
               "sense of reverence, epic scale",
     "negative": "blurry, lowres, text, watermark, cartoon",
     "width": 768, "height": 512, "seed": 1103},
    {"family": "misty-wilds",
     "prompt": "ancient misty forest at dawn, god rays through pines, "
               "moss covered stones, deer silhouette, soft greens and "
               "gold, tranquil, painterly",
     "negative": "urban, people, text, watermark, harsh contrast",
     "width": 768, "height": 512, "seed": 1104},
    {"family": "desert-monolith",
     "prompt": "lone black monolith in vast orange desert at dusk, "
               "long shadows, sand haze, tiny human figure for scale, "
               "minimalist composition, sci fi realism",
     "negative": "city, trees, text, watermark, cluttered",
     "width": 768, "height": 512, "seed": 1105},
    {"family": "cyber-alchemy",
     "prompt": "alchemist laboratory fused with circuitry, glass "
               "vessels glowing teal, brass and copper machinery, "
               "sparks, dark workshop, intricate, dramatic rim light",
     "negative": "bright daylight, blurry, text, watermark, simple",
     "width": 512, "height": 768, "seed": 1106},
    {"family": "storm-lighthouse",
     "prompt": "lighthouse battered by enormous ocean storm waves at "
               "night, beam cutting through rain, dark teal sea, "
               "dramatic skies, painterly realism",
     "negative": "calm sea, sunny, text, watermark, low detail",
     "width": 768, "height": 512, "seed": 1107},
    {"family": "ember-library",
     "prompt": "endless autumn library interior, towering shelves, "
               "floating dust motes in amber window light, leather "
               "and mahogany tones, cozy melancholy, detailed",
     "negative": "modern, empty, text, watermark, cold light",
     "width": 512, "height": 768, "seed": 1108},
    {"family": "arctic-aurora",
     "prompt": "aurora borealis over frozen ruins, ice crystals "
               "reflecting green and violet curtains, starfield, "
               "silence and grandeur, ultra detailed",
     "negative": "daylight, desert, text, watermark, muddy colors",
     "width": 768, "height": 512, "seed": 1109},
    {"family": "botanical-mandala",
     "prompt": "intricate botanical mandala of blooming flowers and "
               "vines, symmetrical, gold linework on deep indigo, "
               "sacred geometry, macro detail",
     "negative": "asymmetrical, photo, text, watermark, plain",
     "width": 512, "height": 512, "seed": 1110},
    {"family": "brutalist-fog",
     "prompt": "monumental brutalist concrete structures in dense "
               "fog, geometric shadows, lone figure walking, cold "
               "grey palette with single red coat accent, film still",
     "negative": "warm colors, nature, text, watermark, busy",
     "width": 768, "height": 512, "seed": 1111},
    {"family": "carnival-nocturne",
     "prompt": "abandoned carnival at midnight, glowing carousel, "
               "string lights, ferris wheel silhouette, mysterious "
               "festive melancholy, rich blacks and warm bulbs",
     "negative": "crowds, daytime, text, watermark, dull",
     "width": 768, "height": 512, "seed": 1112},
]


def _get(base, path, timeout=5):
    req = urllib.request.Request(base + path)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_engine(base, timeout_s=600):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = _get(base + "/api/status")
        if st and st.get("ok"):
            comfy_up = (st.get("comfy") or {}).get("up")
            return True, comfy_up
        time.sleep(2)
    return False, False


def wait_comfy_models_ready(base):
    """ComfyUI up is enough; model availability surfaces as job error."""
    return True


def submit(base, kind, params, timeout=30):
    body = json.dumps(dict(params, kind=kind)).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/generate", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if not out.get("ok"):
        raise RuntimeError(out.get("error", "submit refused"))
    return out["job"]


def await_job(base, jid, timeout_s=1800):
    deadline = time.time() + timeout_s
    t0 = time.time()
    while time.time() < deadline:
        j = _get(base + "/api/job/" + jid)
        if j and j.get("ok"):
            rec = j["job"]
            st = rec.get("status")
            if st == "done":
                return rec
            if st in ("error", "cancelled"):
                raise RuntimeError(rec.get("error") or st)
            elapsed = int(time.time() - t0)
            print("   ... %s (%ds)" % (st, elapsed), flush=True)
        time.sleep(4)
    raise TimeoutError("job %s exceeded %.0fs" % (jid, timeout_s))


def main(argv=None):
    ap = argparse.ArgumentParser(description="generate the self-canon")
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    ap.add_argument("--base", default="http://127.0.0.1:8288")
    ap.add_argument("--out", default=os.path.join(repo, "haven",
                                                  "canon"))
    ap.add_argument("--only")
    ap.add_argument("--engine-root", default=repo)
    args = ap.parse_args(argv)

    ok, comfy_up = wait_engine(args.base, timeout_s=30)
    if not ok:
        # boot our own engine against the default ai-home
        proc = subprocess_safe_launch(args.engine_root)
        print("engine launched (pid %s); waiting..." % proc)
        ok, comfy_up = wait_engine(args.base, timeout_s=120)
    if not ok:
        raise SystemExit("riley-studio engine unreachable at %s"
                         % args.base)
    if not comfy_up:
        raise SystemExit("ComfyUI backend is down - start it first:\n"
                         "  D:\\riley-studio-ai\\venv\\Scripts\\python.exe"
                         " D:\\riley-studio-ai\\ComfyUI\\main.py "
                         "--port 8188 --lowvram")

    mv = _get(args.base + "/api/models") or {}
    sd15_complete = (mv.get("models", {}).get("sd15", {})
                     .get("complete"))
    if not sd15_complete:
        raise SystemExit("sd15 not pulled yet - POST /api/models/pull "
                         '{"key":"sd15"} first')

    items = [c for c in CANON
             if not args.only or c["family"] == args.only]
    manifest = {
        "kind": "riley-studio-self-canon",
        "version": 1,
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "model_key": "sd15",
        "pieces": [],
    }
    for c in items:
        print("[canon] %s (seed %d)" % (c["family"], c["seed"]),
              flush=True)
        jid = submit(args.base, "txt2img", {
            "model": "sd15",
            "prompt": c["prompt"],
            "negative": c["negative"],
            "width": c["width"], "height": c["height"],
            "steps": 22, "cfg": 7.5, "seed": c["seed"],
        })
        rec = await_job(args.base, jid)
        src = rec["files"][0]
        fam_dir = os.path.join(args.out, c["family"])
        os.makedirs(fam_dir, exist_ok=True)
        dest = os.path.join(fam_dir, "image.png")
        shutil.copyfile(src, dest)
        meta = dict(c)
        meta.update({
            "job_id": jid,
            "source_file": os.path.basename(src),
            "model": "sd15",
            "steps": 22, "cfg": 7.5,
            "provenance": "fully synthetic - generated locally by "
                          "riley-studio engine (sd15 quantized tier)",
            "created": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
        })
        with open(os.path.join(fam_dir, "metadata.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        manifest["pieces"].append({"family": c["family"],
                                   "dir": c["family"],
                                   "seed": c["seed"]})
        print("[canon]   -> %s" % dest, flush=True)

    with open(os.path.join(args.out, "canon-manifest.json"), "w",
              encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print("[canon] complete: %d pieces under %s"
          % (len(manifest["pieces"]), args.out))
    return 0


def subprocess_safe_launch(engine_root):
    import subprocess
    return subprocess.Popen(
        [sys.executable, os.path.join(engine_root, "server.py")],
        cwd=engine_root,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    sys.exit(main())
