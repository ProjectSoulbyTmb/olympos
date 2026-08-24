import unittest

from ptah.condenser import condense, estimate_tokens, summarize_dropped
from ptah.events import (ActionEvent, AgentMessage, ObservationEvent,
                         UserMessage)


def make_history(n_actions=5):
    evs = [UserMessage(text="build the widget")]
    for i in range(n_actions):
        evs.append(ActionEvent(tool="file_editor",
                               args={"op": "create", "path": f"f{i}.txt"}))
        evs.append(ObservationEvent(tool="file_editor",
                                    output=f"created f{i}.txt"))
    evs.append(AgentMessage(text="done"))
    return evs


class TestCondenser(unittest.TestCase):
    def test_small_history_untouched(self):
        evs = make_history(2)
        kept, dropped = condense(evs, budget_tokens=10_000)
        self.assertEqual(dropped, [])
        self.assertEqual([e.to_dict() for e in kept],
                         [e.to_dict() for e in evs])

    def test_budget_respected_and_head_kept(self):
        evs = make_history(50)
        budget = estimate_tokens("build the widget") + 40
        kept, dropped = condense(evs, budget_tokens=budget)
        self.assertTrue(dropped)
        self.assertIs(kept[0].__class__, UserMessage)
        self.assertEqual(kept[0].text, "build the widget")
        self.assertIn(evs[-1].to_dict(),
                      [e.to_dict() for e in kept])

    def test_deterministic(self):
        evs = make_history(30)
        a = [e.to_dict() for e in condense(evs, budget_tokens=100)[0]]
        b = [e.to_dict() for e in condense(evs, budget_tokens=100)[0]]
        self.assertEqual(a, b)

    def test_summary_mentions_tools(self):
        dropped = make_history(3)[1:]
        text = summarize_dropped(dropped)
        self.assertIn("file_editor", text)
        self.assertIn("condensed", text.lower())


if __name__ == "__main__":
    unittest.main()
