import json
import os
import tempfile
import unittest

from ptah.agent import Agent
from ptah.conversation import Conversation
from ptah.llm import ScriptedLLM
from ptah.security import ConfirmationPolicy
from ptah.tools import ToolRegistry, FileEditorTool
from ptah.workspace import LocalWorkspace


def make(tmp, replies):
    ws = LocalWorkspace(tmp)
    conv = Conversation.new(root=tmp + "/_state", workspace_root=ws.root)
    agent = Agent(llm=ScriptedLLM(replies),
                  registry=ToolRegistry([FileEditorTool()]),
                  policy=ConfirmationPolicy("auto"))
    return conv, ws, agent


class TestForkAndAsk(unittest.TestCase):
    def test_fork_is_independent_deep_copy(self):
        tmp = tempfile.mkdtemp(prefix="ptah-fork-")
        conv, ws, agent = make(tmp, [
            '{"answer": "source answer"}'])
        agent.run(conv, "hello", workspace=ws)
        n_source = len(conv.events)
        fork = conv.fork(title="investigation",
                         tags={"purpose": "debug"})
        self.assertEqual(len(fork.events), n_source)
        self.assertNotEqual(fork.id, conv.id)
        self.assertEqual(fork.meta.get("parent"), conv.id)
        self.assertEqual(fork.meta.get("title"), "investigation")
        self.assertEqual(fork.meta["purpose"], "debug")
        self.assertEqual(fork.status, Conversation.IDLE)
        # fork continues independently; source untouched
        from ptah.agent import Agent as A
        from ptah.tools import ToolRegistry, FileEditorTool
        agent2 = A(llm=ScriptedLLM(['{"answer": "fork answer"}']),
                   registry=ToolRegistry([FileEditorTool()]),
                   policy=ConfirmationPolicy("auto"))
        result = agent2.run(fork, "continue", workspace=ws)
        self.assertEqual(result.reason, "answered")
        self.assertEqual(len(conv.events), n_source)

    def test_ask_is_non_intrusive(self):
        tmp = tempfile.mkdtemp(prefix="ptah-ask-")
        conv, ws, agent = make(tmp, ['{"answer": "main done"}'])
        agent.run(conv, "mission one", workspace=ws)
        brain = agent.llm
        brain._replies = ['a side answer']      # refill scripted queue
        before = len(conv.events)
        text = agent.ask(conv, "summarize progress")
        self.assertEqual(text, "a side answer")
        self.assertEqual(len(conv.events), before)   # nothing appended

    def test_secrets_never_enter_history(self):
        os_env_backup = dict(os.environ)
        try:
            os.environ["PTAH_SECRET_TOKEN"] = "super-secret-value"
            tmp = tempfile.mkdtemp(prefix="ptah-sec-")
            replies = [json.dumps({"action": {
                "tool": "terminal", "args": {
                    "command": "echo super-secret-value"}}}),
                '{"answer": "done"}']
            conv, ws, agent = make(tmp, replies)
            agent.secrets = ["super-secret-value"]
            agent.run(conv, "run echo with the token", workspace=ws)
            blob = "".join(e.to_dict().get("output", "") or ""
                           for e in conv.events)
            blob += json.dumps([e.to_dict() for e in conv.events])
            self.assertNotIn("super-secret-value", blob)
        finally:
            for key in [k for k in os.environ if k.startswith(
                    "PTAH_SECRET_")]:
                del os.environ[key]
            os.environ.clear()
            os.environ.update(os_env_backup)


if __name__ == "__main__":
    unittest.main()
