"""Verify suite for tools/media_ingest.py - fully offline.

Parsers are exercised against fixture HTML shaped like the real pages
(captured patterns: dbnaked og:image + i-cdn derivation, tube flvN mp4,
pornpics cdni, babesource media/galleries). Fetcher is a stub; no socket
is ever opened. Exits non-zero on any failure.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "ingest"))

import media_ingest as mi  # noqa: E402


GALLERY_HTML = """
<html><head><title>Corseted Fetish Goth Babe Razor Candi @ dbNaked</title>
<meta property="og:url" content="https://dbnaked.com/pictures/content/bdsm/sites/razorcandi/92328_Corseted_Fetish_Goth_Babe_Razo" />
<meta property="og:image" content="//i-cdn.dbnaked.com/bdsm/razorcandi/92328_Corseted_Fetish_Goth_Babe_Razo/15.jpg" />
</head><body>
<img src="//i.dbnaked.com/scene/92328/h205/1.jpg">
<img src="//i.dbnaked.com/scene/92328/w300/2.jpg">
<img src="//i.dbnaked.com/scene/92328/t300x400/3.jpg">
<img src="//i.dbnaked.com/scene/92328/h205/4.jpg">
<a href="/pictures/content/bdsm/sites/razorcandi">channel</a>
</body></html>
"""

SCENE_HTML = """
<html><head><title>The Maids - "Bound Gang Bangs" scene #8879 @dbNaked</title></head>
<body>
<script>var sources = {"file":"https:\\/\\/flv3.dbnaked.com\\/flvtub\\/yCGKIMoexdc2_ZL8puYA\\/1080\\/flv\\/content\\/bdsm\\/sites\\/boundgangbangs\\/8879_The_Maids\\/video.mp4","label":"720p HD"};</script>
<span>HD</span><span>duration 32 min</span>
</body></html>
"""

CAT_PAGE_1 = """
<a href="/categories/pictures/bdsm/Gothic/most-popular/2">2</a>
<a href="/pictures/content/bdsm/sites/gothicsluts/177302_pink-haired-babe">g1</a>
<a href="/pictures/content/bdsm/sites/barelyevil/139221_tara-toxic-punk">g2</a>
<a href="/pictures/content/bdsm/sites/shemalex/555_ts_solo">bad</a>
"""
CAT_PAGE_2 = """
<a href="/categories/pictures/bdsm/Gothic/most-popular/1">1</a>
<a href="/tube/content/bdsm/sites/x/1_vid">wrong-kind</a>
<a href="/pictures/content/bdsm/sites/razorcandi/90001_wicked_fetish_babe">g3</a>
"""

PP_SEARCH = """
<a href="https://www.pornpics.com/galleries/hot-goth-girl-a/"><img src="//cdni.pornpics.com/460/12/55/12345678/001_100_ab12.jpg"></a>
<a href="https://www.pornpics.com/galleries/dark-lory-b/"></a>
"""

PP_GALLERY = """
<title>Kira Jameson In Dark | PornPics.com</title>
<li class='thumbwook'><a class='rel-link' href='https://cdni.pornpics.com/1280/12/55/48649324/001_100_aa.jpg'></a>
<img src='https://cdni.pornpics.com/460/12/55/48649324/001_100_aa.jpg'></li>
<a class="rel-link" href="https://cdni.pornpics.com/1280/12/55/48649324/002_100_bb.jpg"></a>
<img src="https://static.pornpics.com/logo.png">
"""

BS_SEARCH = """
<a href="https://babesource.com/galleries/tattooed-babe-x-full-set.html">a</a>
<a href="https://babesource.com/galleries/inked-y-hd-full-set.html">b</a>
"""

BS_GALLERY = """
<title>Tattooed Babe X Full Set</title>
<img src="https://media.babesource.com/galleries/a1b2c3/thumbs/1.jpg">
<img src="https://babesource.com/media/galleries/a1b2c3d4e5f6/1.jpg">
<img src="https://babesource.com/media/galleries/a1b2c3d4e5f6/2.jpg">
"""


class FakeFetcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, binary=False, extra=None, retries=3):
        self.calls.append(url)
        body = self.mapping[url]
        return body.encode() if binary else body

    def head_size(self, url):
        return 0


class TestUnits(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(mi.sanitize("a b/c*d?"), "a b_c_d")
        self.assertEqual(mi.sanitize("  ..x  "), "x")
        self.assertEqual(len(mi.sanitize("y" * 200)), 80)

    def test_female_filter(self):
        self.assertFalse(mi.passes_female_filter("shemale solo"))
        self.assertFalse(mi.passes_female_filter("gay twinks clip"))
        self.assertTrue(mi.passes_female_filter("gothic babe feet"))

    def test_abs_url_amp(self):
        self.assertEqual(mi.abs_url("https://h/a", "/b?x=1&amp;y=2"),
                         "https://h/b?x=1")


class TestDbNaked(unittest.TestCase):
    def setUp(self):
        base = "https://dbnaked.com"
        gal_url = (base + "/pictures/content/bdsm/sites/razorcandi/"
                   "92328_Corseted_Fetish_Goth_Babe_Razo")
        self.gal_url = gal_url
        scene_url = base + "/tube/content/bdsm/sites/boundgangbangs/8879_The_Maids"
        self.fx = FakeFetcher({
            gal_url: GALLERY_HTML,
            scene_url: SCENE_HTML,
            base + "/categories/pictures/bdsm/Gothic": CAT_PAGE_1,
            base + "/categories/pictures/bdsm/Gothic/most-popular/2":
                CAT_PAGE_2,
            base + "/bdsm/categories?media=tube":
                '<a href="/categories/pictures/bdsm/Gothic">pics-leak</a>'
                '<a href="/categories/tube/bdsm/Foot_Fetish">tube-ok</a>',
        })
        self.dn = mi.DbNaked(self.fx)

    def test_parse_gallery_derives_cdn_urls(self):
        imgs, meta = self.dn.parse_gallery(self.gal_url)
        self.assertEqual(len(imgs), 4)
        for i, u in enumerate(imgs, 1):
            self.assertEqual(u, f"https://i-cdn.dbnaked.com/bdsm/razorcandi/"
                                f"92328_Corseted_Fetish_Goth_Babe_Razo/{i}.jpg")
        self.assertIn("goth", meta["title"].lower())

    def test_parse_scene_mp4_and_hd(self):
        vids, meta = self.dn.parse_scene(
            "https://dbnaked.com/tube/content/bdsm/sites/"
            "boundgangbangs/8879_The_Maids")
        self.assertEqual(len(vids), 1)
        self.assertIn("flv3.dbnaked.com/flvtub/", vids[0])
        self.assertTrue(vids[0].endswith(".mp4"))
        self.assertTrue(meta["hd"])

    def test_category_walk_two_pages_filtered(self):
        items = self.dn.category_items("/categories/pictures/bdsm/Gothic",
                                       "pictures")
        self.assertEqual(items, [
            "https://dbnaked.com/pictures/content/bdsm/sites/"
            "barelyevil/139221_tara-toxic-punk",
            "https://dbnaked.com/pictures/content/bdsm/sites/"
            "gothicsluts/177302_pink-haired-babe",
            "https://dbnaked.com/pictures/content/bdsm/sites/"
            "razorcandi/90001_wicked_fetish_babe",
        ])

    def test_discover_filters_wrong_media_prefix(self):
        cats = self.dn.discover_categories(realms=("bdsm",),
                                           media=("tube",))
        for c in cats:
            self.assertTrue(c.startswith("/categories/tube/"))


class TestPornPics(unittest.TestCase):
    def test_query_and_gallery(self):
        fx = FakeFetcher({
            "https://www.pornpics.com/?q=goth": PP_SEARCH,
            "https://www.pornpics.com/galleries/hot-goth-girl-a/": PP_GALLERY,
        })
        pp = mi.PornPics(fx)
        gals = pp.query_galleries("goth")
        self.assertEqual(gals, ["https://www.pornpics.com/galleries/"
                                "hot-goth-girl-a/",
                                "https://www.pornpics.com/galleries/"
                                "dark-lory-b/"])
        imgs, meta = pp.parse_gallery(gals[0])
        self.assertEqual(len(imgs), 2)
        self.assertTrue(all("cdni.pornpics.com" in u for u in imgs))
        self.assertIn("kira", meta["title"].lower())


class TestBabeSource(unittest.TestCase):
    def test_search_and_gallery(self):
        fx = FakeFetcher({
            "https://babesource.com/?s=tattoo": BS_SEARCH,
            "https://babesource.com/galleries/inked-y-hd-full-set.html":
                BS_GALLERY,
        })
        bs = mi.BabeSource(fx)
        gals = bs.search_galleries("tattoo")
        self.assertEqual(len(gals), 2)
        imgs, meta = bs.parse_gallery(gals[1])
        self.assertEqual(imgs, [
            "https://babesource.com/media/galleries/a1b2c3d4e5f6/1.jpg",
            "https://babesource.com/media/galleries/a1b2c3d4e5f6/2.jpg"])


IF_SEARCH = """
<a href="/gallery.php?gid=14268981">g1</a>
<a href="/gallery.php?gid=14235788">g2</a>
"""

IF_GALLERY = """
<title>Nerdy Cambodian girl displays Huge Boobs - Porn Pics</title>
<a href="/photo/789760527/?pgid=&amp;gid=14268981&amp;page=0">p1</a>
<a href="/photo/277847563/?pgid=&amp;gid=14268981&amp;page=0">p2</a>
"""

IF_PHOTO = """
<script>
arr = ["https:\\/\\/cdnc.imagefap.com\\/images\\/full\\/122\\/789\\/789760527.jpg?secure=AAA,1787621254",
"https:\\/\\/cdnc.imagefap.com\\/images\\/full\\/119\\/277\\/277847563.jpg?secure=BBB,1787621254"];
</script>
"""


class TestImageFap(unittest.TestCase):
    def test_search_and_gallery(self):
        fx = FakeFetcher({
            "https://www.imagefap.com/gallery.php?type=1&userid=&gen=0"
            "&search=goth%20feet&page=0&perpage=10": IF_SEARCH,
            "https://www.imagefap.com/gallery.php?type=1&userid=&gen=0"
            "&search=goth%20feet&page=1&perpage=10": "",
            "https://www.imagefap.com/gallery.php?gid=14268981": IF_GALLERY,
            "https://www.imagefap.com/photo/789760527/": IF_PHOTO,
        })
        im = mi.ImageFap(fx)
        gals = im.search_galleries("goth feet", pages=2)
        self.assertEqual(gals, ["https://www.imagefap.com/"
                                "gallery.php?gid=14268981",
                                "https://www.imagefap.com/"
                                "gallery.php?gid=14235788"])
        files, meta = im.parse_gallery(gals[0])
        self.assertEqual(len(files), 2)
        self.assertTrue(all("images/full/" in u for u in files))
        self.assertIn("nerdy", meta["title"].lower())


class TestEnumerateFiltering(unittest.TestCase):
    def test_walk_listing_drops_blacklisted_items(self):
        base = "https://dbnaked.com"
        fx = FakeFetcher({
            base + "/categories/pictures/bdsm/X":
                '<a href="/pictures/content/bdsm/sites/s/1_ok">a</a>'
                '<a href="/pictures/content/bdsm/sites/t/2_shemale_set">b</a>',
        })
        dn = mi.DbNaked(fx)
        items = dn.walk_listing(base + "/categories/pictures/bdsm/X",
                                r'href="(/pictures/content/[^"#]+)"')
        self.assertEqual(items, [base + "/pictures/content/bdsm/sites/s/1_ok"])


class TestResumeLayout(unittest.TestCase):
    def test_existing_file_is_skipped(self):
        tmp = tempfile.mkdtemp(prefix="mi-verify-")
        try:
            folder = os.path.join(tmp, "src", "gal")
            os.makedirs(folder)
            target = os.path.join(folder, "g_001.jpg")
            with open(target, "wb") as fh:
                fh.write(b"x" * 10)
            exists = os.path.exists(target) and \
                os.path.getsize(target) > 0
            self.assertTrue(exists)
            empty_target = os.path.join(folder, "g_002.jpg")
            open(empty_target, "wb").close()
            self.assertFalse(os.path.getsize(empty_target) > 0)
        finally:
            shutil.rmtree(tmp)

    def test_catalog_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix="mi-verify-")
        try:
            p = os.path.join(tmp, "_source.json")
            mi.save_json(p, {"items": [{"url": "u"}]})
            self.assertEqual(mi.load_json(p, None)["items"][0]["url"], "u")
            self.assertEqual(mi.load_json(os.path.join(tmp, "nope"), 7), 7)
        finally:
            shutil.rmtree(tmp)


class TestCloneSource(unittest.TestCase):
    def test_clone_registers_new_source(self):
        tmp = tempfile.mkdtemp(prefix="mi-clone-")
        try:
            sdir = os.path.join(tmp, "dbnaked-riley-reid-tube")
            os.makedirs(sdir)
            mi.save_json(os.path.join(sdir, "_source.json"),
                         {"name": "dbnaked-riley-reid-tube",
                          "spec": {"name": "dbnaked-riley-reid-tube",
                                   "adapter": "dbnaked_model",
                                   "path": "/models/general/R/riley-reid",
                                   "kind": "tube"},
                          "items": [{"url": "u", "slug": "s"}]})
            catalog = os.path.join(tmp, "_ingest_catalog.json")
            mi.save_json(catalog, {"v": "1.0", "sources": {
                "dbnaked-riley-reid-tube": {"dir": sdir, "items": 1,
                                            "materialized": 0}}})
            ns = argparse.Namespace(
                out=tmp, catalog=catalog,
                clone_source="dbnaked-riley-reid-tube",
                as_name="dbnaked-other-model-tube",
                set_path="/models/general/O/Other-Model")
            rc = mi.cmd_clone(ns)
            self.assertEqual(rc, 0)
            clone = mi.load_json(os.path.join(
                tmp, "dbnaked-other-model-tube", "_source.json"), None)
            self.assertIsNotNone(clone)
            self.assertEqual(clone["spec"]["path"],
                             "/models/general/O/Other-Model")
            self.assertEqual(clone["spec"]["kind"], "tube")
            self.assertEqual(clone["items"], [])
            master = mi.load_json(catalog, None)
            self.assertIn("dbnaked-other-model-tube", master["sources"])
            self.assertEqual(master["sources"][
                "dbnaked-other-model-tube"]["items"], 0)
        finally:
            shutil.rmtree(tmp)

    def test_clone_unknown_source_fails_clean(self):
        tmp = tempfile.mkdtemp(prefix="mi-clone-")
        try:
            ns = argparse.Namespace(
                out=tmp, catalog=os.path.join(tmp, "cat.json"),
                clone_source="missing-source",
                as_name="x", set_path=None)
            self.assertEqual(mi.cmd_clone(ns), 1)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    print(f"media_ingest verify ({mi.__file__})")
    unittest.main(verbosity=2)

