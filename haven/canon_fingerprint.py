#!/usr/bin/env python3
"""canon_fingerprint - distill the self-canon into HAVEN style cards.

    python haven\\canon_fingerprint.py [--canon haven\\canon]

Decodes every canon piece via ffmpeg rawvideo (zero new deps),
extracts palette + tonal fingerprints, aggregates per family, and
writes fingerprint.json - a live source the HAVEN builder reads to
teach the sisters the house aesthetic. Fully synthetic provenance.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def find_ffmpeg():
    env = os.environ.get("RILEY_STUDIO_FFMPEG")
    cands = [env,
             os.path.join(os.path.dirname(HERE), "riley-studio", "bin",
                          "ffmpeg.exe"),
             os.path.join(os.path.dirname(HERE), "kinema", "bin",
                          "ffmpeg.exe")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    import shutil
    return shutil.which("ffmpeg")


def decode_pixels(ff, path, w=48, h=48):
    out = subprocess.run(
        [ff, "-v", "quiet", "-i", path, "-vf", "scale=%d:%d" % (w, h),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=60, check=True)
    raw = out.stdout
    px = []
    for i in range(0, len(raw) - 2, 3):
        px.append((raw[i], raw[i + 1], raw[i + 2]))
    return px


def stats(px):
    n = len(px)
    luma = [(0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            for r, g, b in px]
    sat = []
    warm = 0.0
    for r, g, b in px:
        mx, mn = max(r, g, b), min(r, g, b)
        sat.append((mx - mn) / mx if mx else 0)
        warm += (r - b)
    mean = lambda v: sum(v) / len(v)
    var = mean([(x - mean(luma)) ** 2 for x in luma])
    return {
        "brightness": round(mean(luma), 3),
        "contrast": round(var ** 0.5, 3),
        "saturation": round(mean(sat), 3),
        "warmth": round(warm / n / 255.0, 3),   # >0 warm, <0 cool
    }


def top_colors(px, k=4):
    buckets = {}
    for r, g, b in px:
        key = (r >> 5, g >> 5, b >> 5)          # 8x8x8 coarse bins
        acc = buckets.setdefault(key, [0, 0, 0, 0])
        acc[0] += 1; acc[1] += r; acc[2] += g; acc[3] += b
    ranked = sorted(buckets.items(), key=lambda kv: -kv[1][0])[:k]
    total = sum(v[0] for _, v in ranked) or 1
    out = []
    for _, (cnt, r, g, b) in ranked:
        hexs = "#%02x%02x%02x" % (round(r / cnt), round(g / cnt),
                                  round(b / cnt))
        out.append({"hex": hexs, "share": round(cnt / total, 3)})
    return out


def fingerprint_piece(ff, img_path):
    px = decode_pixels(ff, img_path)
    s = stats(px)
    s["palette"] = top_colors(px)
    return s


def main(argv=None):
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--canon", default=os.path.join(HERE, "canon"))
    args = ap.parse_args(argv)

    ff = find_ffmpeg()
    if not ff:
        raise SystemExit("ffmpeg not found - run setup_studio.ps1")

    manifest_path = os.path.join(args.canon, "canon-manifest.json")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    families = {}
    for piece in manifest["pieces"]:
        fam = piece["family"]
        d = os.path.join(args.canon, fam)
        meta_p = os.path.join(d, "metadata.json")
        img_p = os.path.join(d, "image.png")
        if not (os.path.isfile(meta_p) and os.path.isfile(img_p)):
            continue
        with open(meta_p, encoding="utf-8") as fh:
            meta = json.load(fh)
        fp = fingerprint_piece(ff, img_p)
        fp.update({"seed": meta["seed"], "prompt": meta["prompt"],
                   "width": meta["width"], "height": meta["height"]})
        families.setdefault(fam, []).append(fp)

    result = {
        "kind": "riley-studio-self-canon-fingerprint",
        "version": 1,
        "provenance": "fully synthetic - every piece generated locally "
                      "by the riley-studio engine from fixed seeds; no "
                      "external imagery involved",
        "model_key": manifest.get("model_key", "sd15"),
        "generated_at": manifest.get("generated_at"),
        "families": families,
    }
    out_path = os.path.join(args.canon, "fingerprint.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    for fam, pieces in sorted(families.items()):
        p = pieces[0]
        pal = " ".join(c["hex"] for c in p["palette"])
        print("%-18s luma=%.2f sat=%.2f warm=%+.2f | %s"
              % (fam, p["brightness"], p["saturation"], p["warmth"],
                 pal))
    print("fingerprint: %s (%d families)" % (out_path, len(families)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
