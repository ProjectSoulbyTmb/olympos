"""Fixture: minimal MCP stdio server for tests (line-delimited JSON-RPC).

Exposes one tool `echo` with argument {message}; replies "ECHO:<message>".
"""
import json
import sys


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    if method == "initialize":
        send({"id": msg["id"], "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "echo-fixture", "version": "0.1"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"id": msg["id"], "result": {"tools": [{
            "name": "echo",
            "description": "Echo the message back",
            "inputSchema": {"type": "object",
                            "properties": {"message": {"type": "string"}},
                            "required": ["message"]}}]}})
    elif method == "tools/call":
        args = (msg.get("params") or {}).get("arguments") or {}
        send({"id": msg["id"], "result": {
            "content": [{"type": "text",
                         "text": "ECHO:" + str(args.get("message", ""))}]}})
    elif "id" in msg:
        send({"id": msg["id"], "error": {"code": -32601,
                                         "message": "unknown method"}})
