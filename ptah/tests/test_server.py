import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from ptah.agent import Agent
from ptah.conversation import Store
from ptah.llm import ScriptedLLM
from ptah.security import ConfirmationPolicy
from ptah.server import make_handler, ApiServer
from ptah.tools import ToolRegistry, TerminalTool, FileEditorTool
from ptah.workspace import LocalWorkspace


class TestSkillsParsing(unittest.TestCase):
    def test_frontmatter_parse_and_triggers(self):
        from ptah.skills import parse_skill, select_skills
        card = ("---\nname: test-card\ntriggers: alpha, beta ; gamma\n"
                "---\nBody line one.\nBody two.\n")
        skill = parse_skill(card, source="card.md")
        self.assertEqual(skill.name, "test-card")
        self.assertEqual(skill.triggers, ["alpha", "beta", "gamma"])
        self.assertIn("Body line one", skill.body)
        self.assertTrue(skill.matches("please ALPHA now"))
        self.assertFalse(skill.matches("nothing here"))

    def test_malformed_cards_rejected(self):
        from ptah.skills import parse_skill
        for bad in ("no frontmatter", "---\nno close\nbody",
                    "---\nname: x\n---\n"):
            with self.subTest(bad=bad[:20]):
                with self.assertRaises(ValueError):
                    parse_skill(bad)

    def test_builtin_skills_load(self):
        from ptah import content
        from ptah.skills import load_skills
        skills = load_skills(content.BUILTIN_SKILLS_DIR)
        names = {s.name for s in skills}
        self.assertIn("Olympos-conventions", names)
        self.assertIn("ptah-workflow", names)
        y = next(s for s in skills if s.name == "Olympos-conventions")
        self.assertTrue(y.matches("check the gate before you verify"))


class ApiHarness:
    def __init__(self, replies=None, token=None, run_delay=0.0,
                 max_active_runs=None, llm=None,
                 handler_max_active_runs=None, server_max_active_runs=None):
        self.tmp = tempfile.TemporaryDirectory(prefix="ptah-api-")
        self.store = Store(root=self.tmp.name)
        replies = replies or [json.dumps({"answer": "done"})]
        self.llm = llm or ScriptedLLM(replies)
        if handler_max_active_runs is None:
            handler_max_active_runs = max_active_runs
        if server_max_active_runs is None:
            server_max_active_runs = max_active_runs

        def runner(conv, text, confirm):
            if run_delay:
                time.sleep(run_delay)
            ws = LocalWorkspace(conv.meta.get("workspace") or ".")
            registry = ToolRegistry([TerminalTool(), FileEditorTool()])
            agent = Agent(llm=self.llm, registry=registry,
                          policy=ConfirmationPolicy("confirm-risky"),
                          max_iterations=6)
            return agent.run(conv, text, confirm=confirm, workspace=ws)

        self.server = ApiServer(("127.0.0.1", 0),
                                make_handler(self.store, runner,
                                            token=token,
                                            max_active_runs=
                                            handler_max_active_runs),
                                max_active_runs=server_max_active_runs)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def request(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url(path), data=data,
                                     method=method,
                                     headers=headers or
                                     {"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()


class TestServerApi(unittest.TestCase):
    def setUp(self):
        self.h = ApiHarness()

    def tearDown(self):
        self.h.close()

    def test_healthz_open_to_all(self):
        status, body = self.h.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_full_conversation_flow_synchronous(self):
        status, meta = self.h.request("POST", "/api/v1/conversations",
                                      {"workspace": "."})
        self.assertEqual(status, 201)
        cid = meta["id"]
        status, run = self.h.request(
            "POST", f"/api/v1/conversations/{cid}/messages",
            {"text": "hello", "wait": True})
        self.assertEqual(status, 200)
        self.assertEqual(run["reason"], "answered")
        self.assertEqual(run["status"], "finished")

    def test_async_start_and_event_polling(self):
        _, meta = self.h.request("POST", "/api/v1/conversations",
                                 {"workspace": "."})
        cid = meta["id"]
        status, started = self.h.request(
            "POST", f"/api/v1/conversations/{cid}/messages",
            {"text": "hello", "wait": False})
        self.assertEqual(status, 202)
        deadline = time.time() + 10
        seen_finished = False
        after = 0
        while time.time() < deadline:
            try:
                _, feed = self.h.request(
                    "GET",
                    f"/api/v1/conversations/{cid}/events?after={after}")
                # transient partial frames under load are retried
                if "total" in feed:
                    after = feed["total"]
                    if feed.get("status") == "finished":
                        seen_finished = True
                        break
            except (json.JSONDecodeError, KeyError, OSError):
                pass                       # dropped frame - poll again
            time.sleep(0.05)
        self.assertTrue(seen_finished)

    def test_unknown_conversation_404(self):
        status, _ = self.h.request("GET", "/api/v1/conversations/nope")
        self.assertEqual(status, 404)

    def test_bad_json_400(self):
        _, meta = self.h.request("POST", "/api/v1/conversations", {})
        cid = meta["id"]
        req = urllib.request.Request(
            self.h.url(f"/api/v1/conversations/{cid}/messages"),
            data=b"{broken", method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("expected 400")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)

    def test_unknown_route_404(self):
        status, _ = self.h.request("GET", "/api/v2/whatever")
        self.assertEqual(status, 404)


class TestServerAuth(unittest.TestCase):
    def setUp(self):
        self.h = ApiHarness(token="sekrit")

    def tearDown(self):
        self.h.close()

    def test_api_requires_bearer(self):
        status, _ = self.h.request("GET", "/api/v1/conversations")
        self.assertEqual(status, 401)
        status, body = self.h.request(
            "GET", "/api/v1/conversations",
            headers={"authorization": "Bearer sekrit",
                     "content-type": "application/json"})
        self.assertEqual(status, 200)
        self.assertIn("conversations", body)

    def test_wrong_token_rejected_but_healthz_open(self):
        status, _ = self.h.request(
            "GET", "/api/v1/conversations",
            headers={"authorization": "Bearer nope"})
        self.assertEqual(status, 401)
        status, _ = self.h.request("GET", "/healthz")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
