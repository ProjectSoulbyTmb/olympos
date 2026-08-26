"""export - deterministic FFmpeg composition of timelines.

Pure compile_* functions build argv lists (unit-testable offline);
render() executes them with bounded output. The canvas app renders
stills itself - this module owns everything that becomes mp4/gif/webm.
"""
import os
import shutil
import subprocess


def find_ffmpeg(repo_root=None):
    """RILEY_STUDIO_FFMPEG wins, then riley-studio/bin, then a sibling
    kinema/bin install, then PATH."""
    env = os.environ.get("RILEY_STUDIO_FFMPEG")
    if env and os.path.isfile(env):
        return env
    root = repo_root or os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))
    for cand in (os.path.join(root, "bin", "ffmpeg.exe"),
                 os.path.join(os.path.dirname(root),
                              "kinema", "bin", "ffmpeg.exe")):
        if os.path.isfile(cand):
            return cand
    return shutil.which("ffmpeg")


def _even(n):
    n = int(n)
    return n - (n % 2)


def compile_slideshow(images, out_path, per_image=2.5, crossfade=0.5,
                      size="1920x1080", fps=30):
    """xfade-chained slideshow -> mp4 (h264, yuv420p, faststart)."""
    if not images:
        raise ValueError("slideshow needs at least one image")
    w, h = size.split("x")
    inputs = []
    for img in images:
        inputs += ["-loop", "1", "-t", "%.2f" % float(per_image),
                   "-i", img]
    if len(images) == 1:
        return ["-y"] + inputs + [
            "-vf", "scale=w=%s:h=%s:force_original_aspect_ratio=decrease,"
                   "pad=%s:%s:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%d"
                   % (w, h, w, h, int(fps)),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", out_path]
    filt = []
    for i in range(len(images)):
        filt.append(
            "[%d:v]scale=w=%s:h=%s:force_original_aspect_ratio="
            "decrease,pad=%s:%s:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%d[v%d]"
            % (i, w, h, w, h, int(fps), i))
    prev = "[v0]"
    offset = float(per_image) - float(crossfade)
    for i in range(1, len(images)):
        out = "[vx%d]" % i
        filt.append("%s[v%d]xfade=transition=fade:duration=%.2f:"
                    "offset=%.2f%s"
                    % (prev, i, float(crossfade),
                       max(0.01, offset * i), out))
        prev = out
    total = float(per_image) * len(images) - \
        float(crossfade) * (len(images) - 1)
    return ["-y"] + inputs + [
        "-filter_complex", ";".join(filt),
        "-map", prev, "-t", "%.2f" % max(0.5, total),
        "-r", str(int(fps)), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", out_path]


def compile_gif(in_video, out_path, fps=12, width=480):
    """Palette-optimized gif from any input video."""
    return ["-y", "-i", in_video, "-vf",
            "fps=%d,scale=%d:-1:flags=lanczos,split[s0][s1];"
            "[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer"
            % (int(fps), _even(width)),
            out_path]


def compile_text_card(text, out_path, seconds=3.0, size="1920x1080",
                      color="white", bg="black"):
    """Timed title card rendered purely by ffmpeg."""
    safe = str(text).replace(":", "\\:").replace("'", "\\'")
    return ["-y", "-f", "lavfi", "-i",
            "color=c=%s:s=%s:d=%.2f" % (bg, size, float(seconds)),
            "-vf", "drawtext=text='%s':fontcolor=%s:fontsize=h/8:"
                   "x=(w-text_w)/2:y=(h-text_h)/2" % (safe, color),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", out_path]


STEP_COMPILERS = {
    "slideshow": lambda p: compile_slideshow(
        p["images"], p["output"], float(p.get("per_image", 2.5)),
        float(p.get("crossfade", 0.5)), p.get("size", "1920x1080"),
        int(p.get("fps", 30))),
    "gif": lambda p: compile_gif(p["input"], p["output"],
                                 int(p.get("fps", 12)),
                                 int(p.get("width", 480))),
    "text": lambda p: compile_text_card(
        p["text"], p["output"], float(p.get("seconds", 3.0)),
        p.get("size", "1920x1080"), p.get("color", "white"),
        p.get("bg", "black")),
}


def validate_spec(spec):
    """{steps:[{type,...}]} envelope check -> normalized steps."""
    if not isinstance(spec, dict) or \
            not isinstance(spec.get("steps"), list) or \
            not spec["steps"]:
        raise ValueError("spec must be {steps:[...]} with >=1 step")
    for i, s in enumerate(spec["steps"]):
        if not isinstance(s, dict) or s.get("type") not in STEP_COMPILERS:
            raise ValueError("step %d: unknown type" % i)
        if s["type"] == "slideshow":
            if not s.get("images"):
                raise ValueError("step %d: slideshow needs images" % i)
            if not str(s.get("output", "")).endswith(".mp4"):
                raise ValueError("step %d: slideshow output must be .mp4"
                                 % i)
        elif s["type"] == "gif" and not (
                s.get("input") and
                str(s.get("output", "")).endswith(".gif")):
            raise ValueError("step %d: gif needs input + .gif output" % i)
        elif s["type"] == "text" and not (
                s.get("text") and
                str(s.get("output", "")).endswith(".mp4")):
            raise ValueError("step %d: text card needs text + .mp4" % i)
    return spec["steps"]


def _resolve(p, workdir):
    """Absolute paths pass through; bare names live inside workdir."""
    if os.path.isabs(p) or os.path.isfile(p):
        return p
    return os.path.join(workdir, p)


def render(spec, workdir, repo_root=None, timeout=1800):
    """Execute validated steps sequentially; later steps may reference
    earlier outputs by bare filename inside workdir. Returns paths."""
    steps = validate_spec(spec)
    ff = find_ffmpeg(repo_root)
    if not ff:
        raise RuntimeError("ffmpeg not found - run setup_studio.ps1")
    os.makedirs(workdir, exist_ok=True)
    made = []
    for i, step in enumerate(steps):
        step = dict(step)
        if "images" in step:
            step["images"] = [_resolve(v, workdir)
                              for v in step["images"]]
        if "input" in step:
            step["input"] = _resolve(step["input"], workdir)
        out = step["output"]
        dest = out if os.path.isabs(out) else os.path.join(workdir, out)
        argv = STEP_COMPILERS[step["type"]](dict(step, output=dest))
        proc = subprocess.run([ff] + argv, capture_output=True,
                              text=True, timeout=timeout)
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-10:]
            raise RuntimeError("ffmpeg step %d failed: %s"
                               % (i, " | ".join(tail)))
        made.append(dest)
    return made
