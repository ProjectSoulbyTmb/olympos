import json
import os
import sys
import tempfile
import unittest

from ptah.mcp import McpConnection, load_mcp_config, register_into
from ptah.tools import ToolContext, ToolRegistry
from ptah.workspace import LocalWorkspace

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "mcp_echo_server.py")


class TestMcpClient(unittest.TestCase):
    def test_config_loader(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"mcpServers": {
            "echo": {"command": sys.executable, "args": [FIXTURE]},
            "broken": {"args": ["no-command"]},
        }}, tmp)
        tmp.close()
        cfg = load_mcp_config(tmp.name)
        self.assertEqual(list(cfg), ["echo"])
        os.unlink(tmp.name)

    def test_full_roundtrip_via_registry(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"mcpServers": {
            "fixt": {"command": sys.executable, "args": [FIXTURE]}}},
            tmp)
        tmp.close()
        registry = ToolRegistry()
        errors = register_into(registry, tmp.name)
        self.assertEqual(errors, [])
        name = "mcp__fixt__echo"
        self.assertIn(name, registry.names())
        tool = registry.get(name)
        ws = LocalWorkspace(tempfile.mkdtemp(prefix="ptah-mcp-ws-"))
        ctx = ToolContext.build(ws)
        obs = tool.run({"message": "ptah<->mcp"}, ctx)
        self.assertEqual(obs.output, "ECHO:ptah<->mcp")
        self.assertTrue(obs.ok)
        # description + schema surface into the prompt text
        self.assertIn(name, registry.describe_all())
        for conn_file in []:
            pass


if __name__ == "__main__":
    unittest.main()
