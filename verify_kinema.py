"""Verify suite for kinema/ - fully offline, zero network.

Pure-python tests (PPM math, hashing, scene cuts, job validation,
catalog learning) always run. FFmpeg-bound tests (real encodes,
probing, watcher sweeps) run only when ffmpeg/ffprobe are present -
install via kinema/setup_kinema_stack.ps1 to unlock them.

Exits non-zero on any failure.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "kinema"))
sys.path.insert(0, ROOT)

import ffmpeg_tools as ft          # noqa: E402
import imaging                     # noqa: E402
import jobs                        # noqa: E402
from analysis import Catalog       # noqa: E402

HAVE_FFMPEG = ft.available()

# --------------------------------------------------------- synthetic art


def flat_ppm(path, w=32, h=32, rgb=(120, 40, 200)):
    px = bytes(rgb) * (w * h)
    imaging.write_ppm(path, w, h, px)


def gradient_ppm(path, w=64, h=64):
    px = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            o = (y * w + x) * 3
            px[o], px[o + 1], px[o + 2] = x * 4 % 256, y * 4 % 256, 128
    imaging.write_ppm(path, w, h, bytes(px))


def stats_sequence(cuts_at=(), frames=10):
    """Textured FrameStats list with hard visual cuts at given indices.

    Frames carry a diagonal texture whose base color jumps at each
    cut, so both gradient hashes and histograms register the change
    while intra-scene frames stay identical."""
    tmp = tempfile.mkdtemp(prefix="kin_seq_")
    try:
        seq = []
        base = [40, 200, 60]
        w = h = 32
        for i in range(frames):
            if i in cuts_at:
                base = [(base[0] + 140) % 256, (base[1] + 90) % 256,
                        (base[2] + 170) % 256]
            px = bytearray(w * h * 3)
            for y in range(h):
                for x in range(w):
                    o = (y * w + x) * 3
                    px[o] = (base[0] + x * 6 + y * 2) % 256
                    px[o + 1] = (base[1] + y * 5) % 256
                    px[o + 2] = (base[2] + x * 3) % 256
            p = os.path.join(tmp, "f.ppm")
            imaging.write_ppm(p, w, h, bytes(px))
            seq.append(imaging.frame_stats_from_ppm(p))
        return seq
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class ImagingTests(unittest.TestCase):
    def test_ppm_roundtrip(self):
        d = tempfile.mkdtemp(prefix="kin_ppm_")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "a.ppm")
        gradient_ppm(p)
        w, h, px = imaging.read_ppm(p)
        self.assertEqual((w, h), (64, 64))
        self.assertEqual(len(px), w * h * 3)

    def test_hashes_deterministic_and_discriminating(self):
        d = tempfile.mkdtemp(prefix="kin_hash_")
        self.addCleanup(shutil.rmtree, d, True)
        a, b = os.path.join(d, "a.ppm"), os.path.join(d, "b.ppm")
        gradient_ppm(a)
        # mirrored ramp flips every horizontal comparison -> dHash moves
        w = h = 64
        px = bytearray(w * h * 3)
        for y in range(h):
            for x in range(w):
                o = (y * w + x) * 3
                px[o], px[o + 1], px[o + 2] = \
                    255 - x * 4 % 256, y * 4 % 256, 128
        imaging.write_ppm(b, w, h, bytes(px))
        sa = imaging.frame_stats_from_ppm(a)
        sb = imaging.frame_stats_from_ppm(b)
        same = imaging.frame_stats_from_ppm(a)
        self.assertEqual(sa.dhash, same.dhash)
        self.assertGreater(imaging.hamming(sa.dhash, sb.dhash), 8)
        self.assertGreaterEqual(sb.hist_hist_dist(sa), 0.5)

    def test_scene_detection_finds_the_cut(self):
        seq = stats_sequence(cuts_at=(5,), frames=10)
        stamps = [float(i) for i in range(len(seq))]
        scenes = imaging.detect_scenes(seq, stamps, hist_thresh=0.30,
                                       dhash_thresh=0.15)
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[1][0], 5.0)
        # motion across a cut is far higher than within a still shot
        cut_motion = seq[5].diff(seq[4])[0]
        still_motion = seq[1].diff(seq[0])[0]
        self.assertGreater(cut_motion, still_motion * 3 + 0.01)


class JobValidationTests(unittest.TestCase):
    def _valid(self):
        return {"name": "t", "workdir": "out", "steps": [
            {"type": "trim", "input": __file__, "output": "o.mp4",
             "start": 1.0}]}

    def test_valid_job_passes(self):
        cleaned, errors = jobs.validate(self._valid())
        self.assertEqual(errors, [])
        self.assertEqual(cleaned["steps"][0]["type"], "trim")

    def test_unknown_type_missing_keys_bogus_files(self):
        bad = {"name": "", "steps": [
            {"type": "explode"},                                  # unknown
            {"type": "scale", "input": "nope.mp4",
             "output": "x.mp4"},                                  # ghost file
            {"type": "gif", "input": __file__, "output": "g.gif",
             "wat": 1},                                           # stray field
            {"type": "crop", "input": __file__,
             "output": "c.mp4"},                                  # missing width/height
        ]}
        _cleaned, errors = jobs.validate(bad)
        joined = "\n".join(errors)
        for needle in ("missing 'name'", "unknown type", "missing "
                       "'width'", "'input' not found", "unknown field"):
            self.assertIn(needle, joined)


class CatalogTests(unittest.TestCase):
    def test_learning_roundtrip_and_profile(self):
        d = tempfile.mkdtemp(prefix="kin_cat_")
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "catalog.json")
        cat = Catalog(path)
        entry = {"path": r"c:\v\a.mp4", "name": "a.mp4",
                 "meta": {"duration": 12.0, "width": 1920,
                          "height": 1080, "has_audio": True},
                 "scene_count": 3, "avg_shot_seconds": 4.0,
                 "motion": 0.05}
        cat.put(r"c:\v\a.mp4", entry)
        self.assertTrue(cat.has_current(r"c:\v\a.mp4"))
        cat.save()
        reloaded = Catalog(path)
        profile = reloaded.style_profile()
        self.assertEqual(profile["videos"], 1)
        self.assertEqual(profile["resolution_mix"]["hd"], 1)
        self.assertEqual(profile["median_shot_seconds"], 4.0)
        self.assertEqual(profile["audio_share"], 1.0)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class PipelineTests(unittest.TestCase):
    """Real encode/probe round trips against the bundled binary."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kin_pipe_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        # keep relative writes (data/kinema/...) inside the sandbox
        self._old_cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, self._old_cwd)
        self.images = []
        palette = [(190, 60, 50), (50, 170, 80), (60, 90, 210),
                   (230, 200, 60)]
        for i, rgb in enumerate(palette):
            p = os.path.join(self.dir, "img%d.ppm" % i)
            gradient_ppm(p) if i % 2 else flat_ppm(p, rgb=rgb)
            self.images.append(p)

    def _encode_source(self, seconds=2, fps=10):
        """Small synthetic mp4 from numbered PPM frames."""
        frames_dir = os.path.join(self.dir, "src")
        os.makedirs(frames_dir, exist_ok=True)
        n = int(seconds * fps)
        for i in range(n):
            p = os.path.join(frames_dir, "f%03d.ppm" % i)
            v = i * 255 // max(n - 1, 1)
            flat_ppm(p, rgb=(v, 255 - v, 128))
        out = os.path.join(self.dir, "source.mp4")
        rc, _, err = ft.run([
            ft.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", str(fps), "-i",
            os.path.join(frames_dir, "f%03d.ppm"),
            "-frames:v", str(n)] +
            ["-c:v", "mpeg4", "-q:v", "6", "-pix_fmt", "yuv420p", out],
            timeout=120)
        self.assertEqual(rc, 0, err[:300])
        return out

    def test_probe_normalize(self):
        src = self._encode_source()
        info = ft.probe(src)
        self.assertAlmostEqual(info["duration"], 2.0, delta=0.35)
        self.assertTrue(info["width"] >= 16 and info["height"] >= 16)
        self.assertFalse(info["has_audio"])

    def test_slideshow_trim_text_gif_chain(self):
        import produce
        job = {
            "name": "verify chain", "workdir": self.dir,
            "steps": [
                {"type": "slideshow", "images": self.images,
                 "per_image": 1.0, "crossfade": 0.25, "size": "320x180",
                 "fps": 24, "output": "reel.mp4"},
                {"type": "trim", "input": "reel.mp4", "start": 0.2,
                 "end": 1.6, "reencode": True, "output": "cut.mp4"},
                {"type": "text", "input": "cut.mp4",
                 "output": "titled.mp4", "text": "verify: ok",
                 "fontsize": 28},
                {"type": "speed", "input": "titled.mp4",
                 "output": "fast.mp4", "factor": 2.0},
                {"type": "gif", "input": "fast.mp4", "output": "r.gif",
                 "fps": 8, "width": 160},
                {"type": "extract_frames", "input": "cut.mp4",
                 "out_dir": "snaps", "count": 3},
            ]}
        report = produce.render(job)
        self.assertTrue(report["ok"],
                        json.dumps(report.get("steps"))[:800])
        kinds = {s["type"] for s in report["steps"]}
        self.assertEqual(kinds, {"slideshow", "trim", "text", "speed",
                                 "gif", "extract_frames"})
        reel = ft.probe(os.path.join(self.dir, "reel.mp4"))
        # 4 x 1.0s images with three 0.25s dissolves -> ~3.25s
        self.assertAlmostEqual(reel["duration"], 3.25, delta=0.45)
        cut = ft.probe(os.path.join(self.dir, "cut.mp4"))
        self.assertAlmostEqual(cut["duration"], 1.4, delta=0.35)
        fast = ft.probe(os.path.join(self.dir, "fast.mp4"))
        self.assertAlmostEqual(fast["duration"], 0.7, delta=0.3)
        snaps = os.listdir(os.path.join(self.dir, "snaps"))
        self.assertGreaterEqual(len(snaps), 3)

    def test_concat_watermark_fade_scale_crop(self):
        import produce
        wm = os.path.join(self.dir, "wm.ppm")
        flat_ppm(wm, w=24, h=24, rgb=(255, 255, 255))
        a = self._encode_source(seconds=1)
        b = self._encode_source(seconds=1)
        job = {"name": "chain2", "workdir": self.dir, "steps": [
            {"type": "concat", "inputs": [a, b],
             "output": "joined.mp4"},
            {"type": "watermark", "input": "joined.mp4",
             "image": wm, "position": "tr", "opacity": 0.8,
             "output": "wm.mp4"},
            {"type": "fade", "input": "wm.mp4", "output": "faded.mp4",
             "fade_in": 0.3, "fade_out": 0.3},
            {"type": "scale", "input": "faded.mp4", "height": 160,
             "output": "small.mp4"},
            {"type": "crop", "input": "small.mp4", "width": 128,
             "height": 96, "x": 16, "y": 32, "output": "crop.mp4"},
        ]}
        report = produce.render(job)
        self.assertTrue(report["ok"],
                        json.dumps(report.get("steps"))[:800])
        joined = ft.probe(os.path.join(self.dir, "joined.mp4"))
        self.assertAlmostEqual(joined["duration"], 2.0, delta=0.4)
        crop = ft.probe(os.path.join(self.dir, "crop.mp4"))
        self.assertEqual((crop["width"], crop["height"]), (128, 96))

    def test_analyze_folder_learns_catalog(self):
        import analysis
        src = self._encode_source(seconds=1)
        root = os.path.join(self.dir, "library")
        os.makedirs(root)
        shutil.copy(src, os.path.join(root, "clip one.mp4"))
        catalog = os.path.join(self.dir, "cat.json")
        res = analysis.analyze_folder(root, catalog_path=catalog)
        self.assertEqual(res["newly_analyzed"], 1)
        self.assertEqual(res["errors"], 0)
        # second sweep is a no-op (resumable catalog)
        again = analysis.analyze_folder(root, catalog_path=catalog)
        self.assertEqual(again["newly_analyzed"], 0)
        cat = Catalog(catalog)
        entries = list(cat.entries.values())
        self.assertGreaterEqual(entries[0]["frames_sampled"], 4)
        self.assertGreater(entries[0]["scene_count"], 0)

    def test_watcher_sweep(self):
        import watcher
        root = os.path.join(self.dir, "watched")
        os.makedirs(root)
        shutil.copy(self._encode_source(seconds=1),
                    os.path.join(root, "new drop.mp4"))
        cfg = {"roots": [root],
               "catalog": os.path.join(self.dir, "wc.json"),
               "samples": os.path.join(self.dir, "samples"),
               "interval": 5}
        summary = watcher.run_once(cfg)
        self.assertEqual(summary["roots_scanned"], 1)
        self.assertEqual(summary["results"][0]["newly_analyzed"], 1)
        events = os.path.join("data", "kinema", "events.jsonl")
        self.assertTrue(os.path.isfile(events))


class AiBridgeTests(unittest.TestCase):
    def test_template_structure(self):
        import ai_bridge
        wf = ai_bridge.image2video_template()
        self.assertIsInstance(wf, dict)
        for node in wf.values():
            self.assertIn("class_type", node)
            self.assertIn("inputs", node)
        classes = {n["class_type"] for n in wf.values()}
        self.assertIn("VideoCombine", classes)

    def test_loopback_guard_refuses_remote_hosts(self):
        import ai_bridge
        old = os.environ.pop("KINEMA_ALLOW_REMOTE_HOST", None)
        try:
            with self.assertRaises(RuntimeError):
                ai_bridge.status("http://203.0.113.9:8188")
        finally:
            if old is not None:
                os.environ["KINEMA_ALLOW_REMOTE_HOST"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
