"""Verify suite for ingest/video_audit.py - fully offline, zero network.

Builds a throwaway library tree with hand-crafted container headers
(mp4 ftyp, webm EBML), a zero-byte file, garbage bytes, a truncated
tail, content-clone twins and name-twin copies. Exits non-zero on any
failure.
"""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "ingest"))

import video_audit as va  # noqa: E402


MP4_HEAD = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
WEBM_HEAD = b"\x1aE\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x00"
GARBAGE = b"NOTAVIDEOHEADER!!"


def mp4_body(size):
    return MP4_HEAD + os.urandom(4096) * (size // 4096)


class VideoAuditTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="va_")
        self.addCleanup(self._cleanup)
        self.report = os.path.join(self.root, "_video_audit.json")

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name, data):
        p = os.path.join(self.root, name)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def _run(self, argv=None):
        args = ["--root", self.root, "--report", self.report]
        rc = va.main((args + argv) if argv else args)
        with open(self.report, encoding="utf-8") as fh:
            return rc, json.load(fh)

    def test_classification_integrity_and_dupes(self):
        data = mp4_body(300 * 1024)
        good = self._write("EPORNER.COM - [aaa] Test PMV (1080).mp4", data)
        twin = self._write("EPORNER.COM - [aaa] Test PMV (1080) (1).mp4",
                           data)
        goth = self._write("goth babe tease (720).webm",
                           WEBM_HEAD + b"\x00" * 100)
        feet = self._write("foot worship joi (480).mp4",
                           mp4_body(600 * 1024))
        zero = self._write("feet soles zero.mp4", b"")
        bad = self._write("gothic trash (1080).mp4", GARBAGE + b"x" * 64)
        trunc = self._write("pmv edging cut (2160).mp4",
                            MP4_HEAD + b"\x00" * 200000)
        other = self._write("random scene (1080).mp4", mp4_body(50 * 1024))

        rc, rep = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(rep["videos_scanned"], 8)
        self.assertEqual(rep["matched"], 7)
        self.assertEqual(rep["by_category"]["pmv"], 3)
        self.assertEqual(rep["by_category"]["goth"], 2)
        self.assertEqual(rep["by_category"]["feet"], 2)

        by_name = {os.path.basename(r["path"]): r for r in rep["files"]}
        g = by_name[os.path.basename(goth)]
        self.assertTrue(g["magic_ok"])
        self.assertTrue(g["hd"])
        f = by_name[os.path.basename(feet)]
        self.assertTrue(f["magic_ok"])
        self.assertFalse(f["hd"])
        z = by_name[os.path.basename(zero)]
        self.assertIn("zero-byte", z["problems"])
        b = by_name[os.path.basename(bad)]
        self.assertIn("bad-magic", b["problems"])
        t = by_name[os.path.basename(trunc)]
        self.assertIn("truncated-tail", t["problems"])

        kinds = {d["kind"] for d in rep["duplicates"]}
        self.assertIn("content", kinds)
        content = next(d for d in rep["duplicates"]
                       if d["kind"] == "content")
        content_files = ({os.path.basename(p) for p in content["dupes"]} |
                         {os.path.basename(content["keep"])})
        self.assertEqual(content_files,
                         {os.path.basename(good), os.path.basename(twin)})
        self.assertNotIn(os.path.basename(other),
                         [p for d in rep["duplicates"]
                          for p in d["dupes"]])
        dup_names = {os.path.basename(p)
                     for d in rep["duplicates"] for p in d["dupes"]}
        self.assertEqual(dup_names,
                         {os.path.basename(good), os.path.basename(twin)} -
                         {os.path.basename(content["keep"])})

    def test_all_flag_audits_everything(self):
        self._write("unmatched solo (720).mp4", mp4_body(20 * 1024))
        rc, rep = self._run(["--all"])
        self.assertEqual(rc, 0)
        self.assertEqual(rep["videos_scanned"], 1)
        self.assertEqual(rep["matched"], 1)

    def test_fix_quarantines_dupes_and_broken_keeps_original(self):
        data = mp4_body(600 * 1024)
        good = self._write("pmv keeper (1080).mp4", data)
        twin = self._write("pmv keeper (1080) (1).mp4", data)
        bad = self._write("goth broken (720).mp4", b"garbage!!" + b"x" * 600 * 1024)
        rc, _pre = self._run(["--fix"])
        self.assertEqual(rc, 0)
        qdir = os.path.join(self.root, va.QUARANTINE_NAME)
        quarantined = {os.path.basename(p)
                       for p in os.listdir(qdir)}
        self.assertIn(os.path.basename(twin), quarantined)
        self.assertIn(os.path.basename(bad), quarantined)
        self.assertNotIn(os.path.basename(good), quarantined)
        self.assertTrue(os.path.exists(good))
        self.assertFalse(os.path.exists(twin))
        with open(self.report, encoding="utf-8") as fh:
            rep = json.load(fh)
        self.assertEqual(rep["problem_files"], [])
        self.assertEqual(rep["duplicates"], [])
        self.assertEqual(rep["videos_scanned"], 1)

    def test_huge_files_use_sampled_digest(self):
        data = mp4_body(64 * 1024)
        self._write("pmv big one (1080).mp4", data)
        self._write("pmv big two (1080).mp4", data)
        with unittest.mock.patch.object(va, "FULL_HASH_MAX", 1024):
            va.main(["--root", self.root, "--report", self.report])
        with open(self.report, encoding="utf-8") as fh:
            rep = json.load(fh)
        kinds = {d["kind"] for d in rep["duplicates"]}
        self.assertEqual(kinds, {"content-sampled"})

    def test_bad_root_exits_two(self):
        rc = va.main(["--root", os.path.join(self.root, "nope")])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
