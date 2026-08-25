"""Verify suite for ingest/media_scanner.py - fully offline, zero network.

Builds a throwaway tree with hand-crafted image/video headers (jpeg,
png, gif, mp4 ftyp), a bad-magic png, a content-clone pair, a feet-tagged
file and a quarantined folder that must stay invisible. Exits non-zero
on any failure.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "ingest"))

import media_scanner as ms  # noqa: E402

JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
PNG_BAD = b"\x00\x00\x00\x00IHDR" + b"\x00" * 8
GIF = b"GIF89a" + b"\x00" * 6
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
BIG = JPG + os.urandom(4096) * 150


class MediaScannerTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ms-verify-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _w(self, rel, data):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def _idx_path(self):
        return os.path.join(self.root, "_media_index.json")

    def test_scan_tags_magic_hd_and_rollups(self):
        self._w("a.jpg", BIG[:200 * 1024])
        self._w("feet soles set (1080).jpg", JPG)
        self._w("broken.png", PNG_BAD)
        self._w("clip.gif", GIF)
        self._w("goth set/PMV night (2160).mp4", MP4 + b"x" * 1000)
        idx = ms.scan(self.root, save_index=False)
        self.assertEqual(idx["indexed"], 5)
        self.assertTrue(all(r["magic_ok"] is None
                            for r in idx["files"]))
        by_name = {os.path.basename(r["path"]): r for r in idx["files"]}
        feet = by_name["feet soles set (1080).jpg"]
        self.assertIn("feet", feet["tags"])
        self.assertTrue(feet["hd"])
        self.assertEqual(feet["res"], 1080)
        pmv = by_name["PMV night (2160).mp4"]
        self.assertEqual(pmv["kind"], "video")
        self.assertIn("pmv", pmv["tags"])
        self.assertEqual(idx["by_ext"][".jpg"], 2)
        self.assertEqual(idx["folders"]["goth set"]["files"], 1)

    def test_sniff_validates_and_caches(self):
        self._w("ok.mp4", MP4 + b"x")
        self._w("bad.png", PNG_BAD)
        idx = ms.scan(self.root, sniff=True, save_index=True)
        by_name = {os.path.basename(r["path"]): r for r in idx["files"]}
        self.assertTrue(by_name["ok.mp4"]["magic_ok"])
        self.assertFalse(by_name["bad.png"]["magic_ok"])

        def _no_open(path, ext):
            raise AssertionError("sniff_one called on unchanged file")

        with unittest.mock.patch.object(ms, "sniff_one", _no_open):
            idx2 = ms.scan(self.root, sniff=True, save_index=False)
        by2 = {os.path.basename(r["path"]): r for r in idx2["files"]}
        self.assertTrue(by2["ok.mp4"]["magic_ok"])
        self.assertFalse(by2["bad.png"]["magic_ok"])

    def test_find_and_tag_filters(self):
        self._w("pmv ride (720).mp4", MP4 + b"a")
        self._w("tattoo babe (1080).jpg", JPG)
        hit = ms.scan(self.root, find_rx=re.compile("pmv"),
                      save_index=False)
        self.assertEqual(hit["matched"], 1)
        tagged = ms.scan(self.root, tag_filter={"tattoo"},
                         save_index=False)
        self.assertEqual(tagged["matched"], 1)
        none = ms.scan(self.root, tag_filter={"latex"}, save_index=False)
        self.assertEqual(none["matched"], 0)

    def test_dedupe_finds_content_clones(self):
        self._w("clone original.jpg", BIG)
        self._w("clone original (1).jpg", BIG)
        self._w("unique.jpg", JPG)
        idx = ms.scan(self.root, dedupe=True, save_index=False)
        self.assertEqual(len(idx["duplicates"]), 1)
        grp = idx["duplicates"][0]
        members = {os.path.basename(grp["keep"])} | \
            {os.path.basename(p) for p in grp["dupes"]}
        self.assertEqual(members,
                         {"clone original.jpg", "clone original (1).jpg"})
        self.assertEqual(os.path.basename(grp["keep"]),
                         "clone original.jpg")

    def test_quarantine_folder_is_invisible(self):
        self._w("visible.jpg", JPG)
        hidden = self._w(os.path.join("_audit_quarantine",
                                      "hidden.mp4"), MP4)
        self.assertTrue(os.path.exists(hidden))
        idx = ms.scan(self.root, save_index=False)
        paths = [r["path"] for r in idx["files"]]
        self.assertEqual(len(paths), 1)
        self.assertNotIn(hidden, paths)

    def test_index_json_written(self):
        self._w("x.gif", GIF)
        ms.scan(self.root, save_index=True)
        with open(self._idx_path(), encoding="utf-8") as fh:
            idx = json.load(fh)
        self.assertEqual(idx["indexed"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
