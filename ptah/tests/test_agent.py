import json
import tempfile
import unittest

from ptah.agent import Agent, ProtocolError, RunResult, extract_json, \
    parse_reply
from ptah.conversation import Conversation
from ptah.events import FinishedEvent
from ptah.llm import Reply, ScriptedLLM
from ptah.security import ConfirmationPolicy
from ptah.tools import ToolRegistry, TerminalTool, FileEditorTool, \
    TaskTrackerTool
from ptah.workspace import LocalWorkspace


def json_action(tool, **args):
    return json.dumps({"action": {"tool": tool, "args": args}})


class AgentHarness:
    """Fresh offline agent + workspace per test."""

    def __init__(self, replies, policy="confirm-risky", max_iters=10):
        self.tmp = tempfile.TemporaryDirectory(prefix="ptah-agent-")
        self.ws = LocalWorkspace(self.tmp.name)
        self.conv = Conversation.new(root=self.tmp.name,
                                     workspace_root=self.ws.root)
        registry = ToolRegistry([TerminalTool(), FileEditorTool(),
                                 TaskTrackerTool()])
        self.brain = ScriptedLLM(replies)
        self.agent = Agent(llm=self.brain, registry=registry,
                           policy=ConfirmationPolicy(policy),
                           max_iterations=max_iters)

    def run(self, task="", confirm=False):
        return self.agent.run(self.conv, task, confirm=confirm,
                              workspace=self.ws)

    def cleanup(self):
        self.tmp.cleanup()


class TestParsing(unittest.TestCase):
    def test_extract_json_with_surrounding_prose(self):
        obj = extract_json('Sure! Here you go:\n{"answer": "done"}\nthanks')
        self.assertEqual(obj, {"answer": "done"})

    def test_extract_json_handles_braces_in_strings(self):
        obj = extract_json('{"answer": "curly } brace"}')
        self.assertEqual(obj["answer"], "curly } brace")

    def test_parse_reply_shapes(self):
        self.assertEqual(parse_reply('{"answer":"x"}'), ("answer", "x"))
        kind, tool, args = parse_reply(
            json_action("terminal", command="ls"))
        self.assertEqual((kind, tool), ("action", "terminal"))
        self.assertEqual(args, {"command": "ls"})

    def test_parse_reply_rejects_garbage(self):
        for bad in ('{"wrong": 1}', '{"action": {"args": {}}}',
                    '{"answer": ""}', "not json at all", '{"action": []}'):
            with self.subTest(bad=bad):
                with self.assertRaises(ProtocolError):
                    parse_reply(bad)


class TestHappyPath(unittest.TestCase):
    def test_native_tool_call_uses_legacy_audit_and_security_path(self):
        h = AgentHarness([
            Reply("", tool_calls=[{"id": "c1", "name": "file_editor",
                                   "arguments": {"op": "create",
                                                 "path": "native.txt",
                                                 "content": "native"}}]),
            json.dumps({"answer": "native call completed"}),
        ])
        try:
            result = h.run("use the native tool interface")
            self.assertEqual(result.reason, "answered")
            self.assertEqual(h.ws.read_file("native.txt"), "native")
            thought = next(e for e in h.conv.events
                           if e.TYPE == "agent_thought")
            self.assertEqual(thought.tool_calls[0]["name"], "file_editor")
            self.assertEqual(len([e for e in h.conv.events
                                  if e.TYPE == "action"]), 1)
        finally:
            h.cleanup()

    def test_creates_file_then_answers(self):
        h = AgentHarness([
            json_action("task_tracker", op="add", title="write note"),
            json_action("file_editor", op="create", path="NOTE.md",
                        content="hello"),
            json.dumps({"answer": "note written"}),
        ])
        try:
            result = h.run("write NOTE.md saying hello")
            self.assertEqual(result.reason, "answered")
            self.assertEqual(result.status, h.conv.FINISHED)
            self.assertEqual(
                h.ws.read_file("NOTE.md"), "hello")
            kinds = [e.TYPE for e in h.conv.events]
            self.assertNotIn("confirmation_required", kinds)
            self.assertNotIn("denied_action", kinds)
            fin = h.conv.last_finished()
            self.assertIsInstance(fin, FinishedEvent)
        finally:
            h.cleanup()

    def test_iteration_counting_and_usage_recorded(self):
        h = AgentHarness([Reply(json.dumps({"answer": "straight away"}),
                                usage={"input": 4, "output": 2})])
        try:
            result = h.run("hello?")
            self.assertEqual(result.iterations, 1)
            thought = next(e for e in h.conv.events
                           if e.TYPE == "agent_thought")
            self.assertIn('"answer"', thought.text)
            self.assertEqual(thought.usage, {"input": 4, "output": 2})
            self.assertIsInstance(thought.latency_s, float)
            self.assertEqual(thought.model, "scripted")
        finally:
            h.cleanup()


class TestSecurityFlow(unittest.TestCase):
    def test_destructive_pauses_then_confirmed_execution(self):
        h = AgentHarness([
            json_action("terminal", command="rm -rf build/"),
            json_action("file_editor", op="create", path="ok.txt",
                        content="resumed"),
            json.dumps({"answer": "done after confirmation"}),
        ])
        try:
            paused = h.run("clean build dir then continue")
            self.assertEqual(paused.status, h.conv.WAITING_CONFIRMATION)
            self.assertFalse(h.ws.exists("ok.txt"))

            resumed = h.run(confirm=True)
            self.assertEqual(resumed.status, h.conv.FINISHED)
            self.assertTrue(h.ws.exists("ok.txt"))
            # the gate re-arms: a second destructive action would pause again
            kinds = [e.TYPE for e in h.conv.events]
            self.assertEqual(kinds.count("confirmation_required"), 1)
        finally:
            h.cleanup()

    def test_denied_action_reported_not_executed(self):
        h = AgentHarness([
            json_action("terminal", command="mkfs.ext4 /dev/sda1"),
            json.dumps({"answer": "refused and stopping"}),
        ])
        try:
            result = h.run("nuke it")
            self.assertEqual(result.reason, "answered")
            denial = next(e for e in h.conv.events
                          if e.TYPE == "denied_action")
            self.assertIn("filesystem format", denial.reason)
        finally:
            h.cleanup()

    def test_confirm_all_policy_gates_even_curl(self):
        h = AgentHarness([
            json_action("terminal", command="curl example.com"),
        ], policy="confirm-all")
        try:
            result = h.run("fetch page")
            self.assertEqual(result.status, h.conv.WAITING_CONFIRMATION)
        finally:
            h.cleanup()

    def test_auto_policy_runs_elevated_without_pause(self):
        h = AgentHarness([
            json_action("terminal", command="curl example.com"),
            json.dumps({"answer": "fetched"}),
        ], policy="auto")
        try:
            result = h.run("fetch page")
            self.assertEqual(result.status, h.conv.FINISHED)
        finally:
            h.cleanup()


class TestFailureModes(unittest.TestCase):
    def test_stuck_detector_stops_repetition(self):
        reply = json_action("terminal", command="echo same")
        h = AgentHarness([reply, reply, reply, reply], max_iters=10)
        try:
            result = h.run("loop much?")
            self.assertEqual(result.reason, "stuck")
            actions = [e for e in h.conv.events if e.TYPE == "action"]
            self.assertEqual(len(actions), 3)
        finally:
            h.cleanup()

    def test_protocol_corrective_retry_then_success(self):
        h = AgentHarness([
            "I think I should create a file first!",
            json.dumps({"answer": "recovered"}),
        ])
        try:
            result = h.run("go")
            self.assertEqual(result.reason, "answered")
            corrective = [e for e in h.conv.events
                          if e.TYPE == "user_message"
                          and e.text.startswith("[protocol]")]
            self.assertEqual(len(corrective), 1)
        finally:
            h.cleanup()

    def test_double_protocol_failure_errors_out(self):
        h = AgentHarness(["garbage one", "garbage two"])
        try:
            result = h.run("go")
            self.assertEqual(result.reason, "protocol_error")
            self.assertEqual(h.conv.status, h.conv.ERROR)
        finally:
            h.cleanup()

    def test_max_iterations_respected(self):
        h = AgentHarness(
            [json_action("terminal", command=f"echo tick-{i}")
             for i in range(50)],
            max_iters=4)
        try:
            result = h.run("keep going")
            self.assertEqual(result.reason, "max_iterations")
            self.assertLessEqual(result.iterations, 4)
        finally:
            h.cleanup()


if __name__ == "__main__":
    unittest.main()
