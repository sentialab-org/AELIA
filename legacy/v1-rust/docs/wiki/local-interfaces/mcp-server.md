---
title: MCP Server
summary: The local Model Context Protocol surface for AI integrations.
order: 32
---

# MCP Server

The `McpWorker` in `services/mcp` exposes a local Model Context Protocol surface for external clients and for internal tooling that wants the same tool registry the dialogue engine uses.

The worker supports two transports:

- `http` for a simple local HTTP API
- `stdio` for native MCP clients that expect JSON-RPC over standard input/output

The transport is selected with `MCP_TRANSPORT`, and the whole worker is gated by `MCP_ENABLED`.

## HTTP transport

The HTTP transport binds to `MCP_BIND`, which defaults to `127.0.0.1:4790` when MCP is enabled.

The current HTTP routes are intentionally small:

### `GET /api/mcp/tools`

Returns the list of registered tools in MCP-compatible JSON schema form.

### `POST /api/mcp/tools/call`

Executes a tool call.

The request body uses:

```json
{
  "name": "social.get_affect_context",
  "input": { "user_id": "123" }
}
```

The response shape is:

```json
{ "ok": true, "result": {} }
```

or, on failure:

```json
{ "ok": false, "error": "..." }
```

## Stdio transport

The stdio transport speaks MCP JSON-RPC directly and is the better fit when a client wants to manage the protocol lifecycle itself.

Important points:

- the protocol version advertised by the server is `2025-03-26`
- the server responds to the usual MCP initialization flow
- tool calls use `arguments` in the JSON-RPC payload, not the HTTP `input` field
- the server exposes `tools/list`, `tools/get`, `tools/call`, and `logging/setLevel`

If you are wiring up an MCP client that already knows how to speak stdio, set `MCP_TRANSPORT=stdio` and connect to the worker process directly.

## Execution and timeout

Every tool call is wrapped in a timeout controlled by `MCP_REQUEST_TIMEOUT_MS`.

Current default when MCP is enabled:

- `MCP_REQUEST_TIMEOUT_MS=2000`

If a tool runs too long, the worker returns a timeout error instead of hanging the request path.

The worker also enforces `MCP_MAX_TOOL_CALLS_PER_TURN` for dialogue-side tool loops.

## Tool families

The default tool registry is split into clearly separated families:

### Social tools

These are always read-only and are the core shared tools between the dialogue engine and MCP:

- `social.get_affect_context`
- `social.get_dialogue_summary`

### Web search and fetch tools

These tools are only registered when their corresponding environment flags are enabled:

- `search.web` when `MCP_SEARCH_ENABLED=true` and `BRAVE_SEARCH_API_KEY` is set
- `web.fetch` when `MCP_WEB_FETCH_ENABLED=true`
- `web.retrieve_fast` when `MCP_WEB_RETRIEVE_FAST_ENABLED=true`

`web.retrieve_fast` reuses the same Brave search configuration as `search.web`, so in practice they are most useful when enabled together.

### Action tools

The registry has an `Action` namespace, but the default MCP surface is read-only. Action tools are not part of the normal exposed set.

## Read-only behavior

The MCP worker intentionally exposes the same read tools that the dialogue engine can use, but it does not expose mutation tools by default.

That keeps external clients safe to use for inspection, search, and bounded web retrieval without giving them direct write access to the runtime state.

