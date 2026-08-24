import tempfile
import unittest

from ptah.conversation import Conversation, Store
from ptah.events import (ActionEvent, AgentMessage, ConfirmationRequiredEvent,
                         FinishedEvent, UserMessage)


def populate(conv):
    conv.append(UserMessage(text="mission"))
    conv.append(ActionEvent(tool="file_editor", args={"op": "view"},
                            risk="SAFE", risk_reason=""))
    conv.append(AgentMessage(text="all done"))


class TestConversation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ptah-conv-")

    def tearDown(self):
        self.tmp.cleanup()

    def test_persist_and_replay_identical(self):
        conv = Conversation.new(root=self.tmp.name)
        populate(conv)
        reloaded = Conversation.load(conv.dir)
        self.assertEqual([e.to_dict() for e in reloaded.events],
                         [e.to_dict() for e in conv.events])
        self.assertEqual(reloaded.status, Conversation.IDLE)

    def test_status_transitions(self):
        conv = Conversation.new(root=self.tmp.name)
        self.assertEqual(conv.status, Conversation.IDLE)
        conv.append(ConfirmationRequiredEvent(tool="terminal", args={},
                                              risk="DESTRUCTIVE",
                                              reason="rm"))
        self.assertEqual(conv.status, Conversation.WAITING_CONFIRMATION)
        self.assertEqual(conv.pending_action, ("terminal", {}))
        conv.append(FinishedEvent(reason="answered"))
        self.assertEqual(conv.status, Conversation.FINISHED)
        self.assertIsNone(conv.pending_action)

    def test_resume_pending_survives_reload(self):
        conv = Conversation.new(root=self.tmp.name)
        conv.append(ConfirmationRequiredEvent(tool="terminal",
                                              args={"command": "x"},
                                              risk="DESTRUCTIVE", reason="r"))
        reloaded = Conversation.load(conv.dir)
        self.assertEqual(reloaded.pending_action,
                         ("terminal", {"command": "x"}))

    def test_incremental_slice(self):
        conv = Conversation.new(root=self.tmp.name)
        populate(conv)
        chunk, total = conv.slice(after=1)
        self.assertEqual(total, 3)
        self.assertEqual(len(chunk), 2)
        chunk2, total2 = conv.slice(after=total)
        self.assertEqual((chunk2, total2), ([], 3))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ptah-store-")
        self.store = Store(root=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_list_get(self):
        conv = self.store.create(workspace_root="/tmp/w")
        metas = self.store.list()
        self.assertEqual(len(metas), 1)
        fetched = self.store.get(conv.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, conv.id)
        self.assertIsNone(self.store.get("does-not-exist"))

    def test_prune_removes_only_old_conversations(self):
        fresh = self.store.create()
        import os
        import time as t
        old_dir = os.path.join(self.tmp.name, "20200101-000000-old123")
        os.makedirs(old_dir, exist_ok=True)
        with open(os.path.join(old_dir, "meta.json"), "w") as fh:
            fh.write('{"id": "old", "status": "finished"}')
        past = t.time() - 30 * 86400
        os.utime(os.path.join(old_dir, "meta.json"), (past, past))
        removed = self.store.prune(keep_days=14)
        self.assertEqual(removed, 1)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp.name,
                                                   fresh.id)))
        # non-conversation dirs are never touched
        stray = os.path.join(self.tmp.name, "not-a-conversation")
        os.makedirs(stray, exist_ok=True)
        self.assertEqual(self.store.prune(keep_days=14), 0)
        self.assertTrue(os.path.isdir(stray))


if __name__ == "__main__":
    unittest.main()
