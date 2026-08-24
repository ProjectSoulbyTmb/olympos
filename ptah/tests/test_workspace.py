import os
import tempfile
import unittest

from ptah.workspace import LocalWorkspace, PathEscape, SizeLimit


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ptah-ws-")
        self.ws = LocalWorkspace(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_read_roundtrip(self):
        self.ws.write_file("docs/note.txt", "hello ptah")
        self.assertEqual(self.ws.read_file("docs/note.txt"), "hello ptah")

    def test_escape_attempts_blocked(self):
        for bad in ("../outside.txt", "a/../../x", "/etc/passwd",
                    "C:\\Windows\\evil.txt", "c:/windows/evil",
                    "\\\\.\\device", "~/.ssh/id_rsa"):
            with self.subTest(bad=bad):
                with self.assertRaises(PathEscape):
                    self.ws.resolve(bad)

    def test_dotdot_inside_name_allowed(self):
        # a file literally named "a..b.txt" is fine; only path segments
        # equal to ".." climb.
        self.ws.write_file("a..b.txt", "ok")
        self.assertTrue(self.ws.exists("a..b.txt"))

    def test_create_refuses_overwrite_via_tool_contract(self):
        self.ws.write_file("f.txt", "one")
        with self.assertRaises(FileExistsError):
            self.ws.write_file("f.txt", "two", overwrite=False)

    def test_missing_read_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.ws.read_file("ghost.txt")

    def test_list_dir_sorted(self):
        self.ws.write_file("b.txt", "2")
        self.ws.write_file("a.txt", "1")
        names = [e["name"] for e in self.ws.list_dir()]
        self.assertEqual(names, ["a.txt", "b.txt"])

    def test_walk_files_stable_and_skips_caches(self):
        os.makedirs(os.path.join(self.tmp.name, "__pycache__"),
                    exist_ok=True)
        self.ws.write_file("z.py", "x = 1")
        rels = list(self.ws.walk_files())
        self.assertEqual(rels, ["z.py"])

    def test_size_cap_enforced_on_write(self):
        big = "x" * (3 * 1024 * 1024)
        with self.assertRaises(SizeLimit):
            self.ws.write_file("big.bin", big)


if __name__ == "__main__":
    unittest.main()
