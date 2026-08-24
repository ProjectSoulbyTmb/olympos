"""Verify suite for ingest/web_search.py - fully offline, zero network.

Engine parsers are exercised against fixture HTML shaped like the real
search pages (pornpics query, imagefap paging, babesource search,
dbnaked category/model probes, eporner video links). Fetcher is a stub;
no socket is ever opened. Exits non-zero on any failure.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "ingest"))

import web_search as ws  # noqa: E402


PP_SEARCH = """
<a href="https://www.pornpics.com/galleries/goth-girl-poses/"></a>
<a href="https://www.pornpics.com/galleries/dark-ink-babe/"></a>
"""

IF_PAGE0 = """
<a href="/gallery.php?gid=111">g1</a>
<a href="/gallery.php?gid=222">g2</a>
"""

BS_SEARCH = """
<a href="https://babesource.com/galleries/alt-angel-full.html"></a>
"""

EP_SEARCH = """
<a href="/video-Ab12Cd/awesome-goth-feet-compilation-hd/">v1</a>
<a href="/video-Xy34Zw/pmv-night-drive-1080/">v2</a>
<script>var a=["/video-IGNORED/x"];</script>
"""

DN_CAT = """
<a href="/pictures/content/bdsm/sites/gothicsluts/177302_pink-haired-babe">a</a>
"""


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, binary=False, extra=None, retries=3):
        try:
            return self.pages[url]
        except KeyError:
            raise RuntimeError(f"fetch failed after {retries}: {url}")

    def head_size(self, url):
        return 0


def all_pages():
    return {
        "https://www.pornpics.com/?q=goth": PP_SEARCH,
        "https://www.pornpics.com/?q=goth%20feet": PP_SEARCH,
        "https://www.imagefap.com/gallery.php?type=1&userid=&gen=0"
        "&search=goth%20feet&page=0&perpage=10": IF_PAGE0,
        "https://www.imagefap.com/gallery.php?type=1&userid=&gen=0"
        "&search=goth%20feet&page=1&perpage=10": "",
        "https://babesource.com/?s=goth": BS_SEARCH,
        "https://babesource.com/?s=goth%20feet": BS_SEARCH,
        "https://www.eporner.com/search/goth+feet/": EP_SEARCH,
        "https://dbnaked.com/categories/pictures/bdsm/goth": DN_CAT,
    }


class TestEporner(unittest.TestCase):
    def test_video_link_extraction(self):
        ep = ws.Eporner(FakeFetcher(all_pages()))
        hits = ep.search_videos("goth feet")
        self.assertEqual(len(hits), 2)
        self.assertTrue(hits[0].startswith("https://www.eporner.com/video-"))
        self.assertIn("/pmv-night-drive-1080/", hits[1])

    def test_pictures_kind_skips_eporner(self):
        items, errors = ws.run_eporner(None, "goth", "pictures", 25)
        self.assertEqual((items, errors), ([], []))


class TestDbNakedProbe(unittest.TestCase):
    def test_probe_hit(self):
        dn = ws.DbNakedProbe(FakeFetcher(all_pages()))
        items = dn.probe("/categories/pictures/bdsm/goth")
        self.assertEqual(items, ["https://dbnaked.com/pictures/content/"
                                 "bdsm/sites/gothicsluts/"
                                 "177302_pink-haired-babe"])

    def test_candidates_shape(self):
        cands = ws.DbNakedProbe(None).candidates("Riley Reid")
        paths = [p for _l, p, _m in cands]
        self.assertIn("/models/general/R/riley-reid", paths)
        self.assertIn("/categories/pictures/general/riley_reid", paths)

    def test_runner_records_misses_and_hits(self):
        fx = FakeFetcher(all_pages())
        items, errors = ws.run_dbnaked(fx, "goth", "any", 25)
        self.assertEqual(len(items), 1)
        self.assertTrue(any("model-pics" in e for e in errors))


class TestSweep(unittest.TestCase):
    def test_all_engines_merge_rank_dedupe(self):
        rep = ws.sweep("goth feet", list(ws.ENGINES), cap=25,
                       fetcher=FakeFetcher(all_pages()))
        self.assertEqual(rep["engines"]["eporner"]["count"], 2)
        self.assertEqual(rep["engines"]["pornpics"]["count"], 2)
        self.assertEqual(rep["engines"]["babesource"]["count"], 1)
        self.assertGreaterEqual(rep["engines"]["imagefap"]["count"], 2)
        scores = [s["score"] for s in rep["top"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        urls = [s["url"] for s in rep["top"]]
        self.assertEqual(len(urls), len(set(urls)))
        best = rep["top"][0]
        self.assertIn("goth-feet-compilation", best["url"])
        self.assertGreater(best["score"], 20)
        worst = next(s for s in rep["top"]
                     if "pmv-night-drive" in s["url"])
        self.assertLess(worst["score"], best["score"])

    def test_dead_engine_fails_soft(self):
        rep = ws.sweep("goth", ["pornpics", "eporner"], cap=10,
                       fetcher=FakeFetcher({}))
        for name in ("pornpics", "eporner"):
            self.assertEqual(rep["engines"][name]["count"], 0)
            self.assertTrue(rep["engines"][name]["errors"])
        self.assertEqual(rep["total"], 0)

    def test_main_writes_report(self):
        tmp = tempfile.mkdtemp(prefix="ws-verify-")
        try:
            with unittest.mock.patch.object(
                    ws.mi, "Fetcher",
                    lambda delay_scale=1.0: FakeFetcher(all_pages())):
                rc = ws.main(["goth feet", "--engine", "all",
                              "--out", tmp])
            self.assertEqual(rc, 0)
            path = os.path.join(tmp, "_riley_find.json")
            with open(path, encoding="utf-8") as fh:
                rep = json.load(fh)
            self.assertEqual(rep["query"], "goth feet")
            self.assertIn("top", rep)
        finally:
            shutil.rmtree(tmp)

    def test_unknown_engine_exits_two(self):
        rc = ws.main(["x", "--engine", "nope"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
