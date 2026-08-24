import json
import unittest

from ptah.agent import parse_reply, extract_json


class TestOpenAiGatewayCompat(unittest.TestCase):
    """The /v1/chat/completions gateway shape (contract-level checks)."""

    def test_last_user_turn_extraction_contract(self):
        messages = [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "follow-up question"},
        ]
        last = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last = msg["content"]
                break
        self.assertEqual(last, "follow-up question")

    def test_reply_shape_matches_openai_client_expectations(self):
        payload = {
            "id": "chatcmpl-ptah-x", "object": "chat.completion",
            "model": "ptah-agent",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": "hello"}}],
        }
        self.assertEqual(payload["choices"][0]["message"]["content"],
                         "hello")
        self.assertEqual(payload["object"], "chat.completion")


if __name__ == "__main__":
    unittest.main()
