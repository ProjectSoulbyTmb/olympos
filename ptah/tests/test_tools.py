import os
import tempfile
import time
import unittest

from ptah.tools import (FileEditorTool, GrepTool, MemoryTool,
                        Observation, TaskTrackerTool, TerminalTool,
                        ToolContext, ToolRegistry, VerifyGateTool)

WS = None  # set in setUpModule-style helpers below


def make_ctx(extra_state=None):
    tmp = tempfile.TemporaryDirectory(prefix="ptah-tools-")
    from ptah.workspace import LocalWorkspace
    ws = LocalWorkspace(tmp.name)
    ctx = ToolContext.build(ws)
    ctx._tmp = tmp                      # keep alive until cleanup
    if extra_state:
        ctx.state.update(extra_state)
    return ctx


class TestFileEditor(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()

    def tearDown(self):
        self.ctx._tmp.cleanup()

    def test_create_then_view(self):
        ed = FileEditorTool()
        obs = ed.run({"op": "create", "path": "a.py",
                      "content": "x = 1\n"}, self.ctx)
        self.assertTrue(obs.ok, obs.error)
        view = ed.run({"op": "view", "path": "a.py"}, self.ctx)
        self.assertIn("1: x = 1", view.output)

    def test_create_existing_refused(self):
        ed = FileEditorTool()
        ed.run({"op": "create", "path": "a.py", "content": "1"}, self.ctx)
        obs = ed.run({"op": "create", "path": "a.py", "content": "2"},
                     self.ctx)
        self.assertFalse(obs.ok)
        self.assertIn("refusing", obs.error.lower())

    def test_str_replace_unique_and_ambiguous(self):
        ed = FileEditorTool()
        ed.run({"op": "create", "path": "b.py",
                "content": "aa\nbb\naa\n"}, self.ctx)
        amb = ed.run({"op": "str_replace", "path": "b.py", "old": "aa",
                      "new": "cc"}, self.ctx)
        self.assertFalse(amb.ok)
        self.assertIn("2 times", amb.error)
        good = ed.run({"op": "str_replace", "path": "b.py",
                       "old": "bb", "new": "dd"}, self.ctx)
        self.assertTrue(good.ok, good.error)
        self.assertEqual(self.ctx.workspace.read_file("b.py"),
                         "aa\ndd\naa\n")

    def test_missing_old_string(self):
        ed = FileEditorTool()
        ed.run({"op": "create", "path": "c.txt", "content": "hi"},
               self.ctx)
        obs = ed.run({"op": "str_replace", "path": "c.txt", "old": "nope",
                      "new": "x"}, self.ctx)
        self.assertFalse(obs.ok)


class TestTerminal(unittest.TestCase):
    def setUp(self):
        self.tool = TerminalTool()
        self.ctx = make_ctx()

    def tearDown(self):
        self.ctx._tmp.cleanup()

    def test_echo(self):
        cmd = "echo ptah_alive"
        obs = self.tool.run({"command": cmd}, self.ctx)
        self.assertEqual(obs.exit_code, 0, obs.render())
        self.assertIn("ptah_alive", obs.output.lower())

    def test_timeout_kills(self):
        if os.name == "nt":
            sleeper = "ping -n 30 127.0.0.1 >nul"
        else:
            sleeper = "sleep 30"
        t0 = time.time()
        obs = self.tool.run({"command": sleeper, "timeout_s": 1}, self.ctx)
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(obs.exit_code, 124)
        self.assertIn("timed out", obs.error)

    def test_cwd_escape_blocked(self):
        obs = self.tool.run({"command": "echo hi", "cwd": "../../"},
                            self.ctx)
        self.assertNotEqual(obs.exit_code, 0)
        self.assertIn("bad cwd", obs.error)

    def test_nonzero_exit_captured(self):
        obs = self.tool.run({"command": "exit 3"}, self.ctx)
        self.assertEqual(obs.exit_code, 3)


class TestTaskTracker(unittest.TestCase):
    def test_flow(self):
        ctx = make_ctx()
        tool = TaskTrackerTool()
        tool.run({"op": "add", "title": "step one"}, ctx)
        tool.run({"op": "add", "title": "step two"}, ctx)
        upd = tool.run({"op": "update", "id": 1, "status": "doing"}, ctx)
        self.assertTrue(upd.ok)
        listing = tool.run({"op": "list"}, ctx)
        self.assertIn("[doing] step one", listing.output)
        self.assertIn("[todo] step two", listing.output)
        bad = tool.run({"op": "update", "id": 9, "status": "done"}, ctx)
        self.assertFalse(bad.ok)
        ctx._tmp.cleanup()


class TestGrep(unittest.TestCase):
    def test_finds_matches_with_line_numbers(self):
        ctx = make_ctx()
        ctx.workspace.write_file("src/app.py", "def alpha():\n    return 42\n")
        ctx.workspace.write_file("docs.md", "# alpha docs\n")
        tool = GrepTool()
        obs = tool.run({"pattern": r"return\s+42", "glob": ".py"}, ctx)
        self.assertIn("src/app.py:2:", obs.output)
        none = tool.run({"pattern": "zzz_nothing"}, ctx)
        self.assertEqual(none.output.strip(), "(no matches)")
        bad = tool.run({"pattern": "("}, ctx)
        self.assertIn("bad regex", bad.error)
        ctx._tmp.cleanup()

    def test_limit_respected(self):
        ctx = make_ctx()
        ctx.workspace.write_file("many.txt",
                                 "\n".join("needle" for _ in range(20)))
        tool = GrepTool()
        obs = tool.run({"pattern": "needle", "max_results": 5}, ctx)
        self.assertLessEqual(len(obs.output.splitlines()), 6)
        ctx._tmp.cleanup()


class TestVerifyGateTool(unittest.TestCase):
    def test_unknown_realm_rejected_fast(self):
        ctx = make_ctx()
        obs = VerifyGateTool().run({"realm": "olympus"}, ctx)
        self.assertEqual(obs.exit_code, 2)
        self.assertIn("unknown realm", obs.error)
        ctx._tmp.cleanup()

    def test_missing_script_reported(self):
        ctx = make_ctx()   # repo_root points outside the real fleet
        ctx.repo_root = ctx._tmp.name
        obs = VerifyGateTool().run({"realm": "ptah"}, ctx)
        self.assertEqual(obs.exit_code, 2)
        self.assertIn("not found", obs.error)
        ctx._tmp.cleanup()


class TestMemoryTool(unittest.TestCase):
    def test_remember_recall_roundtrip(self):
        import os
        import tempfile as tf
        mem = os.path.join(tf.mkdtemp(prefix="ptah-mem-"), "memory.jsonl")
        ctx = make_ctx()
        ctx.memory_path = mem
        tool = MemoryTool()
        self.assertTrue(tool.run(
            {"op": "remember", "text": "ports: ptah owns 43903"},
            ctx).ok)
        got = tool.run({"op": "recall", "text": "43903"}, ctx)
        self.assertIn("ptah owns 43903", got.output)
        empty = tool.run({"op": "recall", "text": "nothing-here"}, ctx)
        self.assertEqual(empty.output.strip(), "(no memories)")
        ctx._tmp.cleanup()


class TestRegistry(unittest.TestCase):
    def test_describe_all_lists_every_tool(self):
        reg = ToolRegistry([TerminalTool(), FileEditorTool(), GrepTool(),
                            TaskTrackerTool(), VerifyGateTool(),
                            MemoryTool()])
        text = reg.describe_all()
        for name in ("terminal", "file_editor", "grep", "task_tracker",
                     "verify_gate", "memory"):
            self.assertIn(name, text)

    def test_duplicate_registration_rejected(self):
        reg = ToolRegistry([TerminalTool()])
        with self.assertRaises(ValueError):
            reg.register(TerminalTool())


if __name__ == "__main__":
    unittest.main()
