# MCP (Model Context Protocol) — stdio client notes

MCP lets an agent discover and call tools hosted by external server
processes. For local-first fleets the stdio transport is the whole
story: spawn the server, speak newline-delimited JSON-RPC 2.0 over its
stdin/stdout.

## Lifecycle

1. Spawn: `command + args` from config; env = os.environ plus extras;
   stderr -> devnull (or a log) so it never corrupts your stream.
2. Initialize handshake:
   send `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
     "protocolVersion":"2024-11-05","capabilities":{},
     "clientInfo":{"name":"<you>","version":"<ver>"}}}`
   read until a response with that id arrives; result carries
   serverInfo + negotiated capabilities.
3. Notify: `{"jsonrpc":"2.0","method":"notifications/initialized"}`
   (no id — notifications get no reply).
4. `tools/list` (id=2...) → `result.tools[]` each with
   {name, description?, inputSchema{properties,required}}.
5. Call: `tools/call` with {name, arguments} →
   `result.content[]` items of type "text" carry `text`;
   `result.isError` marks tool-level failure (still exit-0 transport).
6. Shutdown: close stdin (EOF politely ends most servers), wait(5s),
   then kill if needed.

## Robustness rules

- Skip blank lines and non-JSON lines when reading; servers sometimes
  emit logs on stdout despite the spec.
- Notifications have no `id` field — loop past them when awaiting a
  response for a specific id.
- One connection per server per agent run. Connections are cheap;
  shared state across conversations is how secrets leak.

## Naming and security

Register remote tools namespaced: `mcp__<server>__<tool>` so collisions
are impossible and provenance is visible in every action event. Run
them through the SAME risk analyzer as native tools — remote does not
mean trusted. Config lives in the workspace (`.ptah/mcp.json`) using
the de-facto shape:

    {"mcpServers": {"fetch": {"command":"uvx","args":["mcp-server-fetch"]}}}

Optional regex filter drops tools by full name. A dead or unspawnable
server must degrade to a logged warning, never block agent startup.

## What to avoid

HTTP/OAuth transports need browser flows and token caches — hostile to
headless fleets. Prefer servers that ship API-key or no auth. Never
pipe server stderr into your parser. Never share one connection across
conversations with different trust levels.
