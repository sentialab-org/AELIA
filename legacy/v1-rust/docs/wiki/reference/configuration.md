---
title: Configuration
summary: Current configuration files, environment variable groups, and runtime defaults.
order: 40
---

# Configuration

This page is the detailed reference for how the runtime and local platform services are configured today.

## Configuration layers

The main runtime in `apps/agent/src/main.rs` resolves configuration in this order:

1. `.env` via `dotenvy`
2. `config.toml` or the path from `PA_CONFIG`
3. environment overrides for platform tokens, MCP settings, agent identity, and model config
4. `settings.json` for local non-API runtime knobs

Agent profile resolution is separate:

- `config/agent_profile.toml` if present
- otherwise `config/agent_profile.toml.sample`
- then environment overrides handled by the agent profile loader

## Important files

| File | Purpose |
| --- | --- |
| `config/agent_profile.toml.sample` | sample local agent profile, including identity and storage paths |
| `config/prompt_registry.json` | maps logical prompt IDs to files under `prompts/` |
| `config/state_schema.v0.json` | state dimension schema loaded by `state` |
| `config/state_prompt.json` | controls which state domains are injected into dialogue prompts |
| `settings.json` | local non-API overrides such as debug mode, log level, and token limits |
| `config.toml` | optional runtime config file used by `apps/agent` |

## Agent profile defaults

The sample profile defines these default storage paths:

- `data/polyverse-agent/memory.db`
- `data/polyverse-agent/graph`
- `data/polyverse-agent/lancedb`

It also defines identity fields such as `agent_id`, `display_name`, and `graph_self_id`.

## Runtime service defaults

### Platform relay

The platform relay is the UDS bridge used by the standalone platform binaries.

- `PLATFORM_RELAY_SOCKET=/tmp/polyverse-agent-relay.sock`

### Discord bot service

- `DISCORD_BOT_TOKEN`

### Telegram bot service

- `TELEGRAM_TOKEN`

### Discord selfbot runner

- `DISCORD_SELFBOT_TOKEN`

## MCP configuration

### Core transport

- `MCP_ENABLED`
- `MCP_TRANSPORT` with values `http` or `stdio`
- `MCP_BIND`
- `MCP_REQUEST_TIMEOUT_MS`
- `MCP_MAX_TOOL_CALLS_PER_TURN`

Current defaults when MCP is enabled:

- `MCP_TRANSPORT=http`
- `MCP_BIND=127.0.0.1:4790`
- `MCP_REQUEST_TIMEOUT_MS=2000`
- `MCP_MAX_TOOL_CALLS_PER_TURN=4`

### Search tool provider

These settings control `search.web`:

- `MCP_SEARCH_ENABLED`
- `BRAVE_SEARCH_API_KEY`
- `MCP_SEARCH_TIMEOUT_MS`
- `MCP_SEARCH_MAX_RESULTS`
- `MCP_SEARCH_BRAVE_API_BASE`

### Web fetch tool provider

These settings control `web.fetch`:

- `MCP_WEB_FETCH_ENABLED`
- `MCP_WEB_FETCH_TIMEOUT_MS`
- `MCP_WEB_FETCH_MAX_BYTES`
- `MCP_WEB_FETCH_MAX_CHARS`
- `MCP_WEB_FETCH_MAX_REDIRECTS`
- `MCP_WEB_FETCH_MAX_KEY_LINKS`

### Fast web retrieval provider

These settings control `web.retrieve_fast`:

- `MCP_WEB_RETRIEVE_FAST_ENABLED`
- `MCP_WEB_FAST_TOTAL_BUDGET_MS`
- `MCP_WEB_FAST_SEARCH_TIMEOUT_MS`
- `MCP_WEB_FAST_FETCH_TIMEOUT_MS`
- `MCP_WEB_FAST_FETCH_K_DEFAULT`
- `MCP_WEB_FAST_MAX_CHARS_PER_PAGE_DEFAULT`
- `MCP_WEB_FAST_CACHE_TTL_MS`
- `MCP_WEB_FAST_CACHE_MAX_ENTRIES`

These tools are disabled unless their feature flags are enabled. They also clamp unsafe minimums and maximums in code so a bad environment variable cannot push them outside supported ranges.

## Important environment variable groups

### Dialogue engine

Primary variables:

- `DIALOGUE_ENGINE_API_BASE`
- `DIALOGUE_ENGINE_API_KEY`
- `DIALOGUE_ENGINE_MODEL`
- `DIALOGUE_ENGINE_REASONING`

The runtime also accepts the fallback aliases `OPENAI_API_BASE`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_REASONING`, and the generic `API_BASE`, `API_KEY`, `MODEL`, `REASONING`.

### Affect evaluator

- `AFFECT_EVALUATOR_API_BASE`
- `AFFECT_EVALUATOR_API_KEY`
- `AFFECT_EVALUATOR_MODEL`
- `AFFECT_EVALUATOR_REASONING`

The same OpenAI-style and generic aliases are also accepted here.

### State runtime

- `STATE_SCHEMA_PATH`
- `STATE_SYSTEM_ENABLED`
- `STATE_SYSTEM_INTERVAL_MS`

### State prompt injection

- `STATE_PROMPT_CONFIG_PATH`
- `STATE_PROMPT_ENABLED`
- `STATE_PROMPT_PRECISION`
- `STATE_PROMPT_INCLUDE_DERIVED`
- `STATE_PROMPT_DOMAINS`

### Local runtime behavior

- `PA_AGENT_NAME`
- `PA_LOG_LEVEL`
- `DEBUG_MODE`
- `CHAT_MAX_TOKENS`
- `SEMANTIC_MAX_TOKENS`

### Dialogue tool-calling knobs in `settings.json`

Current local settings support these keys:

- `dialogue_tool_calling_enabled`
- `dialogue_tool_max_calls_per_turn`
- `dialogue_tool_timeout_ms`
- `dialogue_tool_max_candidate_users`

## Default local binds

Unless overridden:

- the platform relay binds to `/tmp/polyverse-agent-relay.sock`
- MCP binds to `127.0.0.1:4790` when enabled

## Notes

- `settings.json` does not replace API credentials; it is for local behavior and tuning.
- `scripts/protoc-wrapper.sh` is configured through Cargo and should stay in place when changing protobuf-related build behavior.
- If a behavior change seems prompt-driven rather than code-driven, check `config/prompt_registry.json` and the corresponding files under `prompts/`.

