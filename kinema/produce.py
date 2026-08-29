"""produce - the mp4 render engine.

Executes validated job specs by building ffmpeg command lines. Every
step is bounded by timeouts, logged into a JSON report, and writes its
outputs inside the job workdir. Encoder selection prefers libx264 and
falls back to mpeg4 so any FFmpeg build works.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffmpeg_tools import ffmpeg_path, probe, run  # noqa: E402
from jobs import POSITIONS, validate  # noqa: E402


def pick_encoder():
    exe = ffmpeg_path()
    if not exe:
        return None
    _rc, out, _ = run([exe, "-hide_banner", "-encoders"], timeout=30)
    if "h264_nvenc" in out:
        return "h264_nvenc"
    if "libx264" in out:
        return "libx264"
    if " mpeg4 " in out or " mpeg4\n" in out:
        return "mpeg4"
    return None


def _enc_args(encoder=None):
    encoder = encoder or pick_encoder() or "mpeg4"
    args = ["-c:v", encoder, "-pix_fmt", "yuv420p"]
    if encoder == "libx264":
        args += ["-preset", "veryfast", "-crf", "20",
                 "-movflags", "+faststart"]
    elif encoder == "h264_nvenc":
        args += ["-preset", "p5", "-cq", "20",
                 "-movflags", "+faststart"]
    else:
        args += ["-q:v", "5"]
    return args


def default_font():
    for cand in (r"C:\Windows\Fonts\arial.ttf",
                 r"C:\Windows\Fonts\segoeui.ttf",
                 r"C:\Windows\Fonts\tahoma.ttf"):
        if os.path.isfile(cand):
            return cand
    return None


def render(job_or_path, base_dir=None, log=None):
    """Render a job dict or a path to a job JSON file. Returns report."""
    if isinstance(job_or_path, (str, bytes, os.PathLike)):
        with open(os.fspath(job_or_path), encoding="utf-8") as fh:
            job = json.load(fh)
    else:
        job = job_or_path
    produced = {str(s.get(key))
                for s in (job.get("steps") or []) if isinstance(s, dict)
                for key in ("output", "out_dir") if s.get(key)}
    cleaned, errors = validate(job, base_dir=base_dir,
                               produced=produced)
    if errors:
        return {"ok": False, "errors": errors}
    workdir = os.path.abspath(cleaned["workdir"])
    os.makedirs(workdir, exist_ok=True)
    report = {"job": cleaned["name"], "ok": True, "steps": [],
              "workdir": workdir, "outputs": []}
    for i, step in enumerate(cleaned["steps"]):
        t0 = time.time()
        entry = {"index": i, "type": step["type"]}
        try:
            handler = STEPS[step["type"]]
            outputs = handler(_resolve_step(step, workdir, base_dir),
                              workdir)
            entry.update(ok=True, outputs=outputs,
                         seconds=round(time.time() - t0, 3))
            report["outputs"].extend(outputs)
            if log:
                log("step %d (%s) ok -> %s"
                    % (i, step["type"], ", ".join(
                        os.path.basename(o) for o in outputs)))
        except Exception as exc:  # noqa: BLE001 - record then stop
            entry.update(ok=False, error=str(exc)[:500],
                         seconds=round(time.time() - t0, 3))
            report["ok"] = False
            report["steps"].append(entry)
            break
        report["steps"].append(entry)
    report_path = os.path.join(
        workdir, "%s.report.json" % cleaned["name"].replace(" ", "_"))
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    report["report_file"] = report_path
    return report


def _out(workdir, name):
    p = os.path.join(workdir, name)
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return p


def _src(step, key="input"):
    return os.path.abspath(step[key])


def _resolve_step(step, workdir, base_dir):
    """Bind step inputs: prefer as-given/base_dir; fall back to the
    job workdir so later steps can chain earlier outputs by name."""
    def pick(value):
        p = os.fspath(value)
        if os.path.isabs(p):
            return p
        candidate = os.path.join(base_dir, p) if base_dir else p
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
        return os.path.join(workdir, p)

    resolved = dict(step)
    for key in ("input", "image", "audio"):
        if key in resolved:
            resolved[key] = pick(resolved[key])
    for key in ("images", "inputs"):
        if key in resolved:
            resolved[key] = [pick(x) for x in resolved[key]]
    return resolved


# ------------------------------------------------------------ step bodies

def _slideshow(step, workdir):
    """Images -> mp4. Hard cuts (concat) or dissolves (xfade chain),
    letterboxed to a fixed canvas, optional music bed."""
    exe = ffmpeg_path()
    images = [os.path.abspath(p) for p in step["images"]]
    per = max(float(step.get("per_image", 3.0)), 0.3)
    cf = float(step.get("crossfade", 0.0)) if len(images) > 1 else 0.0
    cf = min(max(cf, 0.0), per * 0.8)
    fps = str(int(step.get("fps", 30)))
    raw_size = str(step.get("size") or "1280x720").lower().split("x")
    try:
        sw, sh = int(raw_size[0]), int(raw_size[1])
    except (IndexError, ValueError):
        sw, sh = 1280, 720
    out = _out(workdir, step["output"])

    inputs = []
    for img in images:
        inputs += ["-loop", "1", "-t", "%.3f" % per, "-framerate", fps,
                   "-i", img]
    audio_index = len(images)
    if step.get("audio"):
        inputs += ["-i", os.path.abspath(step["audio"])]

    def scaled(i):
        return ("[%d:v]scale=w=%d:h=%d:force_original_aspect_ratio="
                "decrease,pad=w=%d:h=%d:x=(ow-iw)/2:y=(oh-ih)/2,"
                "setsar=1,fps=%s[s%d]" % (i, sw, sh, sw, sh, fps, i))

    chains = [scaled(i) for i in range(len(images))]
    if cf <= 0:
        if len(images) > 1:
            labels = "".join("[s%d]" % i for i in range(len(images)))
            chains.append("%sconcat=n=%d:v=1:a=0[v]"
                          % (labels, len(images)))
        else:
            chains.append("[s0]null[v]")
    else:
        offset = per - cf
        prev = "s0"
        for k in range(1, len(images)):
            nxt = "xf%d" % k
            chains.append("[%s][s%d]xfade=transition=fade:"
                          "duration=%.3f:offset=%.3f[%s]"
                          % (prev, k, cf, offset, nxt))
            prev = nxt
            offset += per - cf
        chains.append("[%s]format=yuv420p[v]" % prev)
    graph = ";".join(chains)

    args = [exe, "-hide_banner", "-loglevel", "error", "-y"] + inputs
    args += ["-filter_complex", graph, "-map", "[v]"]
    if step.get("audio"):
        args += ["-map", "%d:a" % audio_index, "-c:a", "aac",
                 "-shortest"]
    args += _enc_args() + [out]
    rc, _, err = run(args, timeout=1800)
    if rc != 0:
        raise RuntimeError("slideshow failed: %s" % err[:400])
    return [out]


def _concat(step, workdir):
    exe = ffmpeg_path()
    clips = [os.path.abspath(p) for p in step["inputs"]]
    lst = os.path.join(workdir, "_concat_%d.txt" % int(time.time() * 1000))
    with open(lst, "w", encoding="utf-8") as fh:
        for c in clips:
            safe = os.path.abspath(c).replace("\\", "/").replace("'", "'\\''")
            fh.write("file '%s'\n" % safe)
    out = _out(workdir, step["output"])
    args = [exe, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", lst,
            "-c:a", "copy"] + _enc_args() + [out]
    rc, _, err = run(args, timeout=3600)
    os.remove(lst)
    if rc != 0:
        raise RuntimeError("concat failed: %s" % err[:400])
    return [out]


def _trim(step, workdir):
    exe = ffmpeg_path()
    start = max(float(step.get("start", 0.0)), 0.0)
    end = step.get("end")
    out = _out(workdir, step["output"])
    args = [exe, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", "%.3f" % start]
    if end is not None:
        args += ["-to", "%.3f" % float(end)]
    args += ["-i", _src(step)]
    if step.get("reencode"):
        args += _enc_args()
    else:
        args += ["-c", "copy"]
    args.append(out)
    rc, _, err = run(args, timeout=1800)
    if rc != 0:
        raise RuntimeError("trim failed: %s" % err[:400])
    return [out]


def _scale(step, workdir):
    exe = ffmpeg_path()
    w = int(step.get("width", -2))
    h = int(step.get("height", -2))
    out = _out(workdir, step["output"])
    args = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i",
            _src(step), "-vf", "scale=%d:%d" % (w, h), "-c:a", "copy"] \
        + _enc_args() + [out]
    rc, _, err = run(args, timeout=1800)
    if rc != 0:
        raise RuntimeError("scale failed: %s" % err[:400])
    return [out]


def _crop(step, workdir):
    exe = ffmpeg_path()
    out = _out(workdir, step["output"])
    vf = "crop=%d:%d:%d:%d" % (int(step["width"]), int(step["height"]),
                               int(step.get("x", 0)),
                               int(step.get("y", 0)))
    args = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i",
            _src(step), "-vf", vf, "-c:a", "copy"] + _enc_args() + [out]
    rc, _, err = run(args, timeout=1800)
    if rc != 0:
        raise RuntimeError("crop failed: %s" % err[:400])
    return [out]


def _fade(step, workdir):
    exe = ffmpeg_path()
    src = _src(step)
    dur = max(probe(src).get("duration", 1.0), 0.1)
    fi = float(step.get("fade_in", 1.0))
    fo = float(step.get("fade_out", 1.0))
    vf = "fade=t=in:st=0:d=%.3f,fade=t=out:st=%.3f:d=%.3f" % (
        fi, max(dur - fo, 0.0), fo)
    out = _out(workdir, step["output"])
    args = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
            "-vf", vf, "-c:a", "copy"] + _enc_args() + [out]
    rc, _, err = run(args, timeout=1800)
    if rc != 0:
        raise RuntimeError("fade failed: %s" % err[:400])
    return [out]


def _watermark(step, workdir):
    exe = ffmpeg_path()
    pos = POSITIONS.get(str(step.get("position", "br")),
                        POSITIONS["br"]).format(
                            m=int(step.get("margin", 24)))
    opacity = min(max(float(step.get("opacity", 0.6)), 0.05), 1.0)
    graph = ("[1:v]format=rgba,colorchannelmixer=aa=%.2f[wm];"
             "[0:v][wm]overlay=%s" % (opacity, pos))
    out = _out(workdir, step["output"])
    args = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i",
            _src(step), "-i", os.path.abspath(step["image"]),
            "-filter_complex", graph, "-c:a", "copy"] + _enc_args() + [out]
    rc, _, err = run(args, timeout=1800)
    if rc != 0:
        raise RuntimeError("watermark failed: %s" % err[:400])
    return [out]


def _text(step, workdir):
    exe = ffmpeg_path()
    font = step.get("fontfile") or default_font()
    if not font:
        raise RuntimeError("no font file found for drawtext")
    size = int(step.get("fontsize", 48))
    color = str(step.get("color", "white"))
    y_expr = {"top": str(size // 2),
              "center": "(h-text_h)/2",
              "bottom": "h-text_h-%d" % (size // 2)
              }.get(str(step.get("position", "bottom")),
                    "h-text_h-%d" % (size // 2))
    enable = ""
    if step.get("start") is not None or step.get("end") is not None:
        s = float(step.get("start", 0.0))
        e = float(step.get("end", 1 << 20))
        enable = ":enable='between(t,%.3f,%.3f)'" % (s, e)
    font_arg = os.path.abspath(font).replace("\\", "/").replace(":", "\\:")
    text_arg = str(step["text"]).replace("\\", "\\\\").replace(":", "\\:")\
        .replace("'", "\\\\'")
    vf = ("drawtext=fontfile='%s':text='%s':fontsize=%d:fontcolor=%s:"
          "x=(w-text_w)/2:y=%s%s"
          % (font_arg, text_arg, size, color, y_expr, enable))
    out = _out(workdir, step["output"])
    args = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i",
            _src(step), "-vf", vf, "-c:a", "copy"] + _enc_args() + [out]
    rc, _, err = run(args, timeout=1800)
    if rc != 0:
        raise RuntimeError("text failed: %s" % err[:400])
    return [out]


def _speed(step, workdir):
    exe = ffmpeg_path()
    factor = min(max(float(step["factor"]), 0.25), 4.0)
    src = _src(step)
    info = probe(src)
    out = _out(workdir, step["output"])
    args = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
            "-vf", "setpts=PTS/%.4f" % factor]
    if info.get("has_audio"):
        f = factor
        tempos = []
        while f > 2.0:
            tempos.append(2.0)
            f /= 2.0
        while f < 0.5:
            tempos.append(0.5)
            f *= 2.0
        tempos.append(f)
        args += ["-af", ",".join("atempo=%.4f" % t for t in tempos)]
    args += _enc_args() + [out]
    rc, _, err = run(args, timeout=1800)
    if rc != 0:
        raise RuntimeError("speed failed: %s" % err[:400])
    return [out]


def _gif(step, workdir):
    exe = ffmpeg_path()
    fps = int(step.get("fps", 12))
    width = int(step.get("width", 480))
    src = _src(step)
    out = _out(workdir, step["output"])
    base_vf = "fps=%d,scale=%d:-1:flags=lanczos" % (fps, width)
    palette = os.path.join(workdir, "_palette.png")
    rc, _, err = run([exe, "-hide_banner", "-loglevel", "error", "-y",
                      "-t", "60", "-i", src, "-vf",
                      base_vf + ",palettegen=stats_mode=diff", palette],
                     timeout=600)
    if rc != 0:
        raise RuntimeError("gif palette failed: %s" % err[:300])
    rc, _, err = run([exe, "-hide_banner", "-loglevel", "error", "-y",
                      "-t", "60", "-i", src, "-i", palette,
                      "-lavfi", "%s[x];[x][1:v]paletteuse=dither=bayer"
                      % base_vf, out], timeout=600)
    if rc != 0:
        raise RuntimeError("gif encode failed: %s" % err[:300])
    return [out]


def _extract_frames(step, workdir):
    from analysis import extract_frames
    out_dir = _out(workdir, step["out_dir"])
    frames = extract_frames(_src(step), out_dir,
                            count=int(step.get("count", 10)))
    fmt = str(step.get("format", "")).lower().lstrip(".")
    if fmt and fmt != "ppm":
        exe = ffmpeg_path()
        converted = []
        for fp in frames:
            dst = os.path.splitext(fp)[0] + "." + fmt
            rc, _, _err = run([exe, "-hide_banner", "-loglevel", "error",
                               "-y", "-i", fp, dst], timeout=120)
            if rc == 0:
                converted.append(dst)
        frames = converted
    return frames


STEPS = {
    "slideshow": _slideshow,
    "concat": _concat,
    "trim": _trim,
    "scale": _scale,
    "crop": _crop,
    "fade": _fade,
    "watermark": _watermark,
    "text": _text,
    "speed": _speed,
    "gif": _gif,
    "extract_frames": _extract_frames,
}
