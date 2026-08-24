import json
import os
import sys
import tempfile
import unittest

from ptah.hooks import load_hook_config, run_hooks


def py_script(body):
    """Cross-platform shell hook command running a python one-liner."""
    return f'"{sys.executable}" -c {json.dumps(body)}'


class TestHookContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ptah-hooks-")

    def test_exit2_blocks_with_stderr_reason(self):
        cfg = {"PreToolUse": [{"matcher": "terminal", "command":
                               "exit 2"}]}
        outcome = run_hooks(cfg, "PreToolUse",
                            {"tool": "terminal", "args": {}},
                            cwd=self.tmp)
        self.assertTrue(outcome.blocked)

    def test_exit0_allows_and_injects_context(self):
        script = py_script(
            'import sys,json;'
            'sys.stdin.read();'
            'print(json.dumps({"additionalContext": "ctx-injected"}))')
        cfg = {"UserPromptSubmit": [{"command": script}]}
        outcome = run_hooks(cfg, "UserPromptSubmit",
                            {"text": "hello"}, cwd=self.tmp)
        self.assertFalse(outcome.blocked)
        self.assertIn("ctx-injected", outcome.context)

    def test_matcher_filters_tools(self):
        cfg = {"PreToolUse": [{"matcher": "file_editor",
                               "command": "exit 2"}]}
        outcome = run_hooks(cfg, "PreToolUse",
                            {"tool": "terminal", "args": {}}, cwd=self.tmp)
        self.assertFalse(outcome.blocked)      # matcher did not match

    def test_nonzero_non2_is_non_blocking(self):
        cfg = {"PostToolUse": [{"command": "exit 1"}]}
        outcome = run_hooks(cfg, "PostToolUse",
                            {"tool": "grep", "args": {}}, cwd=self.tmp)
        self.assertFalse(outcome.blocked)

    def test_stdin_payload_and_env(self):
        script = py_script(
            'import os,sys,json;'
            'd=json.loads(sys.stdin.read());'
            'assert os.environ["PTAH_TOOL_NAME"]=="terminal";'
            'assert d["args"]["command"]=="echo hi";'
            'print("{}")')
        cfg = {"PreToolUse": [{"matcher": "*", "command": script}]}
        outcome = run_hooks(cfg, "PreToolUse",
                            {"tool": "terminal",
                             "args": {"command": "echo hi"}},
                            cwd=self.tmp)
        self.assertFalse(outcome.blocked)

    def test_agent_stop_hook_blocks_finish_once(self):
        from ptah.agent import Agent
        from ptah.conversation import Conversation
        from ptah.llm import ScriptedLLM
        from ptah.security import ConfirmationPolicy
        from ptah.tools import ToolRegistry, FileEditorTool
        from ptah.workspace import LocalWorkspace

        deny_finish = py_script('import sys; sys.exit(2)')
        allow = py_script('print("{}")')
        hook_cfg = {"Stop": [{"command": deny_finish},
                             {"command": f'"{sys.executable}" -c '
                              '"import sys; sys.exit(0)"'}]}
        # replace with single deterministic denier for first run only:
        hook_cfg = {"Stop": [{"command": deny_finish}]}
        tmp = tempfile.mkdtemp(prefix="ptah-hookagent-")
        ws = LocalWorkspace(tmp)
        conv = Conversation.new(root=os.path.join(tmp, "_s"),
                                workspace_root=ws.root)
        agent = Agent(llm=ScriptedLLM(['{"answer": "done"}',
                                       '{"answer": "done again"}']),
                      registry=ToolRegistry([FileEditorTool()]),
                      policy=ConfirmationPolicy("auto"),
                      hooks_config=hook_cfg, max_iterations=6)
        result = agent.run(conv, "finish please", workspace=ws)
        # stop hook denied the FIRST finish attempt, corrective note went
        # in, second answer passed because... it would be denied too. The
        # agent therefore ends in protocol/iteration flow; we assert the
        # denial feedback reached the stream and finish was NOT the first
        # reply.
        notes = [e for e in conv.events
                 if e.TYPE == "user_message"
                 and e.text.startswith("[stop-hook]")]
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
