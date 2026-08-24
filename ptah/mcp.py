"""PTAH mcp - Model Context Protocol client (stdio transport, stdlib only).

Learns from OpenHands' MCP integration: external tool servers are
declared in a config file and their tools are discovered dynamically,
then registered into the agent's toolset under a namespaced id:

    .ptah/mcp.json
    {
      "mcpServers": {
        "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
        "repo":  {"command": "npx", "args": ["-y", "repomix@1.4.2", "--mcp"]}
      }
    }

Transport: newline-delimited JSON-RPC 2.0 over the server process
stdio (the MCP stdio convention). Each connection performs the
initialize handshake, sends notifications/initialized, then lists
tools. Tool calls map onto PTAH's Action/Observation surface so the
security analyzer classifies them like any native tool:

    {"action": {"tool": "mcp__fetch__fetch", "args": {...}}}

Optional "filter_tools_regex" drops servers' tools by full name.
"""

import json
import os
import re
import subprocess

from ptah import content
from ptah.tools import Observation, Tool


class McpError(Exception):
    pass


def _rpc(method, params=None, msg_id=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if msg_id is not None:
        msg["id"] = msg_id
    return msg


class McpConnection:
    """One stdio MCP server process speaking newline-delimited JSON-RPC."""

    def __init__(self, name, command, args=(), env=None, cwd=None):
        self.name = name
        self.command = command
        self.args = list(args)
        self.extra_env = dict(env or {})
        self.cwd = cwd
        self.proc = None
        self._next_id = 1
        self.server_info = {}

    # ------------------------------------------------------------ io
    def _send(self, msg):
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _recv(self):
        assert self.proc and self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise McpError(f"mcp[{self.name}]: server closed stream")
            line = line.strip()
            if not line:
                continue                       # tolerate keepalives
            try:
                return json.loads(line)
            except ValueError:
                continue                       # non-JSON noise skipped

    def start(self):
        env = dict(os.environ)
        env.update(self.extra_env)
        try:
            self.proc = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True,
                cwd=self.cwd, env=env,
            )
        except OSError as exc:
            raise McpError(f"mcp[{self.name}]: spawn failed: {exc}")
        self._handshake()
        return self

    def _handshake(self):
        self._send(_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": content.REALM,
                           "version": content.VERSION},
        }, msg_id=self._next_id)); self._next_id += 1
        resp = self._recv()
        while "id" not in resp:                 # skip server requests/notifs
            resp = self._recv()
        if resp.get("error"):
            raise McpError(f"mcp[{self.name}]: initialize error: "
                           f"{resp['error']}")
        self.server_info = resp.get("result", {}) or {}
        self._send(_rpc("notifications/initialized"))

    # ---------------------------------------------------------- tools
    def list_tools(self):
        self._send(_rpc("tools/list", {}, msg_id=self._next_id))
        self._next_id += 1
        resp = self._recv()
        while "id" not in resp:
            resp = self._recv()
        tools = ((resp.get("result") or {}).get("tools")) or []
        return [(t.get("name"), t.get("description") or "",
                 t.get("inputSchema") or {})
                for t in tools]

    def call(self, tool_name, arguments):
        self._send(_rpc("tools/call",
                        {"name": tool_name, "arguments": arguments},
                        msg_id=self._next_id))
        self._next_id += 1
        resp = self._recv()
        while "id" not in resp:
            resp = self._recv()
        if resp.get("error"):
            return {"isError": True,
                    "text": str(resp["error"].get("message", resp["error"]))}
        result = resp.get("result") or {}
        chunks = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(item.get("text", ""))
            else:
                chunks.append(json.dumps(item))
        return {"isError": bool(result.get("isError")),
                "text": "\n".join(chunks)}

    def close(self):
        if self.proc is None:
            return
        try:
            self.proc.stdin.close()             # EOF asks server to exit
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class McpTool(Tool):
    """PTAH adapter around one remote MCP tool."""

    def __init__(self, conn, tool_name, description="", schema=None):
        self.conn = conn
        self.name = f"mcp__{conn.name}__{tool_name}"
        self._tool_name = tool_name
        self.description = description or "(remote MCP tool)"
        props = schema.get("properties") if isinstance(schema, dict) else None
        required = schema.get("required") if isinstance(schema, dict) else []
        if props:
            arg_bits = ", ".join(
                f"{k}: {'*' if k in (required or []) else 'opt'}"
                for k in props)
            self.schema_text = "{" + arg_bits + "}"
        else:
            self.schema_text = "{...}"

    def run(self, args, ctx):
        result = self.conn.call(self._tool_name, args)
        return Observation(output=result.get("text", ""),
                           error="" if not result.get("isError")
                           else "remote tool reported failure",
                           exit_code=1 if result.get("isError") else 0)


def load_mcp_config(path):
    """Parse .ptah/mcp.json -> ordered {name: {command,args,env}}."""
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    servers = data.get("mcpServers") or {}
    out = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, dict) or not cfg.get("command"):
            continue
        cfg = dict(cfg)
        cfg["args"] = cfg.get("args") or []
        out[name] = cfg
    return out


def connect_all(config_path):
    """Start every configured server; returns ([connections], [errors])."""
    conns, errs = [], []
    for name, cfg in load_mcp_config(config_path).items():
        try:
            conns.append(McpConnection(name, cfg["command"], cfg["args"],
                                       env=cfg.get("env")).start())
        except McpError as exc:
            errs.append(str(exc))
    return conns, errs


def register_into(registry, config_path, filter_regex=None):
    """Discover tools from all servers; register them. Returns errors."""
    rx = re.compile(filter_regex) if filter_regex else None
    errors = []
    for conn in connect_all(config_path)[0]:
        try:
            for tool_name, desc, schema in conn.list_tools():
                full = f"mcp__{conn.name}__{tool_name}"
                if rx and not rx.search(full):
                    continue
                registry.register(McpTool(conn, tool_name, desc, schema))
        except (McpError, ValueError) as exc:
            errors.append(str(exc))
    return errors
