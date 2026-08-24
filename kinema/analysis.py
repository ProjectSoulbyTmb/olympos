"""analysis - enhanced video understanding + the folder-fed catalog.

For every video in an operator-designated root:
  - ffprobe metadata (duration, resolution, fps, codecs, bitrate)
  - N evenly-spaced frames decoded to PPM and fingerprinted
    (perceptual hashes + color histograms)
  - scene-cut detection, motion scoring, duplicate detection
    (frame-hash + size similarity)

Results merge into a resumable JSON catalog (data/kinema/catalog.json
by default). Unchanged files (size+mtime) are never re-analyzed. The
catalog's aggregate "style profile" (shot cadence, resolution mix,
motion levels) is what downstream creation presets learn from.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffmpeg_tools import probe, run, ffmpeg_path  # noqa: E402
from imaging import (detect_scenes, frame_stats_from_ppm,  # noqa: E402
                     motion_score)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kinema import VIDEO_EXTS  # noqa: E402

FRAMES_PER_VIDEO = 12


def sha256_head(path, nbytes=1 << 16):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read(nbytes))
    return h.hexdigest()


def extract_frames(video, out_dir, count=FRAMES_PER_VIDEO):
    """Uniformly spaced PPM frames (timestamp sampling across the
    whole timeline). Returns the list of written frame paths."""
    exe = ffmpeg_path()
    if not exe:
        raise RuntimeError("ffmpeg not found")
    os.makedirs(out_dir, exist_ok=True)
    return _extract_by_time(exe, video, out_dir, count)


def _extract_by_time(exe, video, out_dir, count):
    info = probe(video)
    dur = max(info.get("duration", 0.0), 0.04)
    step = dur / (count + 1)
    paths = []
    for i in range(1, count + 1):
        ts = round(i * step, 3)
        out = os.path.join(out_dir, "f%04d.ppm" % i)
        rc, _, _ = run([
            exe, "-hide_banner", "-loglevel", "error",
            "-ss", str(ts), "-i", str(video), "-frames:v", "1",
            "-y", out], timeout=120)
        if rc == 0 and os.path.isfile(out):
            paths.append(out)
    return paths


def analyze_video(video, tmp_dir=None, count=FRAMES_PER_VIDEO):
    """Full fingerprint of one video -> dict for the catalog."""
    import tempfile
    tmp = tmp_dir or tempfile.mkdtemp(prefix="kinema_")
    os.makedirs(tmp, exist_ok=True)
    info = probe(video)
    stat = os.stat(video)
    frames_dir = os.path.join(tmp, "frames")
    frame_paths = extract_frames(video, frames_dir, count=count)
    stats, stamps = [], []
    step = info["duration"] / max(count, 1)
    for idx, fp in enumerate(frame_paths):
        try:
            stats.append(frame_stats_from_ppm(fp))
            stamps.append(round((idx + 0.5) * step, 3))
        except (ValueError, OSError):
            continue
    scenes = detect_scenes(stats, stamps) if stats else []
    entry = {
        "path": os.path.abspath(video),
        "name": os.path.basename(video),
        "size_bytes": stat.st_size,
        "mtime": int(stat.st_mtime),
        "sha256_head": sha256_head(video),
        "meta": info,
        "frames_sampled": len(stats),
        "scene_count": len(scenes),
        "scenes": scenes[:64],
        "avg_shot_seconds": (
            round(sum(b - a for a, b in scenes) / len(scenes), 3)
            if scenes else info["duration"]),
        "motion": motion_score(stats),
        "hashes": [s.dhash for s in stats[:32]],
    }
    if not tmp_dir:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return entry


class Catalog:
    """Resumable learning index backed by a single JSON file."""

    def __init__(self, path):
        self.path = path
        self.entries = {}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                blob = json.load(fh)
            self.entries = blob.get("entries", {})

    def save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)),
                    exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.snapshot(), fh, indent=1)

    def snapshot(self):
        return {"version": 1, "entries": self.entries}

    def key_for(self, path):
        try:
            st = os.stat(path)
            size, mtime = st.st_size, int(st.st_mtime)
        except OSError:
            size, mtime = 0, 0
        return "%s|%d|%d" % (os.path.abspath(path).lower(), size, mtime)

    def has_current(self, path):
        return self.key_for(path) in self.entries

    def put(self, path, entry):
        self.entries[self.key_for(path)] = entry

    # ------------------------------------------------ style profile

    def style_profile(self, root=None):
        """Aggregate taste-of-the-folder statistics for creation presets."""
        rows = list(self.entries.values())
        if root:
            low = os.path.abspath(root).lower()
            rows = [r for r in rows if r["path"].lower().startswith(low)]
        if not rows:
            return {}
        res_mix, shots, motions, durs = {}, [], [], []
        for r in rows:
            m = r.get("meta", {})
            tag = ("%dx%d" % (m.get("width", 0), m.get("height", 0)))
            bucket = "hd" if m.get("height", 0) >= 720 else "sd"
            res_mix[bucket] = res_mix.get(bucket, 0) + 1
            shots.append(r.get("avg_shot_seconds") or m.get("duration", 0))
            motions.append(r.get("motion", 0.0))
            durs.append(m.get("duration", 0.0))
        n = len(rows)
        return {
            "videos": n,
            "resolution_mix": res_mix,
            "median_shot_seconds": sorted(shots)[n // 2] if shots else 0,
            "mean_motion": round(sum(motions) / n, 4) if motions else 0,
            "total_minutes": round(sum(durs) / 60.0, 2),
            "audio_share": round(
                sum(1 for r in rows if r.get("meta", {}).get("has_audio"))
                / float(n), 3),
        }


def find_videos(root):
    hits = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                hits.append(os.path.join(dirpath, name))
    return hits


def analyze_folder(root, catalog_path=None, force=False, log=None):
    """Walk root, analyze new/changed videos into the catalog."""
    catalog_path = catalog_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "kinema", "catalog.json")
    cat = Catalog(catalog_path)
    videos = find_videos(root)
    done = errors = 0
    for vid in videos:
        try:
            if not force and cat.has_current(vid):
                continue
            entry = analyze_video(vid)
            cat.put(vid, entry)
            done += 1
            if log:
                log("analyzed %s (%d scenes)" %
                    (entry["name"], entry["scene_count"]))
        except Exception as exc:  # noqa: BLE001 - keep walking
            errors += 1
            if log:
                log("ERROR %s: %s" % (vid, exc))
    cat.save()
    return {
        "root": os.path.abspath(root),
        "videos_found": len(videos),
        "newly_analyzed": done,
        "errors": errors,
        "style_profile": cat.style_profile(root),
        "catalog": catalog_path,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="analyze a video folder")
    ap.add_argument("--root", required=True)
    ap.add_argument("--catalog", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    print(json.dumps(analyze_folder(
        args.root, args.catalog, args.force,
        log=lambda m: print("[kinema]", m)), indent=1))
