"""ffmpeg_tools - locate and drive FFmpeg/FFprobe; stdlib only.

Search order:
  1. KINEMA_FFMPEG / KINEMA_FFPROBE env vars (explicit override)
  2. kinema/bin/ next to this package (portable drop-in location;
     scripts/setup_kinema_stack.ps1 installs here)
  3. PATH
  4. common Windows install locations

Every command is bounded by a hard timeout and captures output, so a
wedged encoder never hangs the studio.
"""
import json
import os
import shutil
import subprocess

DEFAULT_TIMEOUT = 600


def _candidates(tool):
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(here, "bin", tool + ".exe"),
        os.path.join(here, "bin", tool),
        os.environ.get("KINEMA_" + tool.upper()),
        shutil.which(tool),
        rf"C:\ffmpeg\bin\{tool}.exe",
        rf"C:\Program Files\ffmpeg\bin\{tool}.exe",
        os.path.expanduser(rf"~\ffmpeg\bin\{tool}.exe"),
        os.path.expandvars(
            rf"%LOCALAPPDATA%\kinema\ffmpeg\bin\{tool}.exe"),
    ]


def find_tool(tool, refresh=False):
    cache = getattr(find_tool, "_cache", {})
    if not refresh and tool in cache:
        return cache[tool]
    path = None
    for cand in _candidates(tool):
        if cand and os.path.isfile(cand):
            path = cand
            break
    find_tool._cache = dict(cache, **{tool: path})
    return path


def ffmpeg_path(refresh=False):
    return find_tool("ffmpeg", refresh=refresh)


def ffprobe_path(refresh=False):
    return find_tool("ffprobe", refresh=refresh)


def available():
    return bool(ffmpeg_path() and ffprobe_path())


def run(args, timeout=DEFAULT_TIMEOUT):
    """Run a tool command list; returns (rc, stdout, stderr)."""
    proc = subprocess.run(
        [str(a) for a in args], capture_output=True, timeout=timeout,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


def version():
    exe = ffmpeg_path()
    if not exe:
        return None
    rc, out, _ = run([exe, "-version"], timeout=30)
    return out.splitlines()[0] if rc == 0 and out else None


def probe(path, timeout=120):
    """Full ffprobe JSON plus a normalized summary dict."""
    exe = ffprobe_path()
    if not exe:
        raise RuntimeError("ffprobe not found")
    rc, out, err = run([
        exe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path)], timeout=timeout)
    if rc != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {err[:300]}")
    data = json.loads(out or "{}")
    return summarize(data)


def summarize(data):
    """Normalize raw ffprobe JSON into the fields the studio uses."""
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    vstream = next((s for s in streams
                    if s.get("codec_type") == "video"), None)
    astreams = [s for s in streams if s.get("codec_type") == "audio"]

    def _num(x, default=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    fps = 0.0
    if vstream:
        num, _, den = (vstream.get("r_frame_rate") or "0/1").partition("/")
        try:
            fps = float(num) / float(den or 1)
        except ZeroDivisionError:
            fps = 0.0
    return {
        "duration": round(_num(fmt.get("duration")), 3),
        "size_bytes": int(_num(fmt.get("size"))),
        "bitrate": int(_num(fmt.get("bit_rate"))),
        "container": (fmt.get("format_name") or "").split(",")[0],
        "width": int((vstream or {}).get("width", 0)),
        "height": int((vstream or {}).get("height", 0)),
        "fps": round(fps, 3),
        "vcodec": (vstream or {}).get("codec_name"),
        "pix_fmt": (vstream or {}).get("pix_fmt"),
        "has_audio": bool(astreams),
        "acodec": (astreams[0].get("codec_name") if astreams else None),
        "streams": len(streams),
    }
