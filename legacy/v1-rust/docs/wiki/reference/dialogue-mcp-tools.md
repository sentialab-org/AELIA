---
title: Dialogue & MCP Tools
summary: The available tool definitions for dialogue and MCP consumption.
order: 43
---

# Dialogue & MCP Tools

The internal `DialogueEngineWorker` and the external `McpWorker` share the same tool registry.

That shared registry is important for two reasons:

1. the dialogue engine and MCP clients see the same tool names and input schemas
2. documentation can describe the actual runtime surface instead of two separate tool catalogs

## Namespaces

Tools are grouped by mutability:

1. `ToolNamespace::Read` contains tools that do not change agent state. These are the tools exposed through MCP by default.
2. `ToolNamespace::Action` contains tools that can mutate state or trigger behavior. The default MCP surface does not expose these tools.

## Available tools

### `social.get_affect_context`

- Namespace: `Read`
- Availability: always registered
- Purpose: fetch relationship and affect metrics for a specific user
- Input: `user_id`, plus optional staleness and projection hints

This is the most direct lookup when you want to inspect the emotional or relationship context for a user.

### `social.get_dialogue_summary`

- Namespace: `Read`
- Availability: always registered
- Purpose: fetch a coarse natural-language summary of the relationship state
- Input: the same social lookup schema as `social.get_affect_context`

This tool is useful when the caller wants a lighter-weight summary instead of the full affect payload.

### `search.web`

- Namespace: `Read`
- Availability: only when `MCP_SEARCH_ENABLED=true` and `BRAVE_SEARCH_API_KEY` is set
- Purpose: search the public web and return top Brave results
- Input: `query`, optional `count`, `offset`, and `safesearch`

This tool is a search-first primitive. It returns a list of results plus metadata about the response.

### `web.fetch`

- Namespace: `Read`
- Availability: only when `MCP_WEB_FETCH_ENABLED=true`
- Purpose: fetch a public HTTP(S) page and return bounded text content
- Input: `url`, optional extraction `instruction`, optional `max_chars`

The fetcher normalizes HTML to text, extracts key links, and trims content to a safe limit.

### `web.retrieve_fast`

- Namespace: `Read`
- Availability: only when `MCP_WEB_RETRIEVE_FAST_ENABLED=true`
- Purpose: do a budgeted search-and-fetch pass for fast evidence gathering
- Input: `query`, optional `safesearch`, optional `fetch_k`, optional `max_chars_per_page`

This tool is the most opinionated web primitive. It trades completeness for speed by combining search, bounded fetches, caching, and a tight time budget.

## Execution model

The registry resolves a tool name, validates the input schema, and then dispatches the request to the matching provider.

The same registry is used in two contexts:

- inline inside the dialogue engine
- through the MCP worker with the transport-specific timeout and protocol wrappers applied

## What is not exposed by default

The registry contains an `Action` namespace for mutating tools, but the default MCP provider set does not register any action tools.

That is intentional. External clients get a read-oriented surface first, while write-capable behavior stays behind explicit runtime wiring.

