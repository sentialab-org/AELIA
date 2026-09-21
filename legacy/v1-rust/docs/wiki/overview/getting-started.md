---
title: Getting Started
summary: Quick-start commands and first reading paths for working in the repository.
order: 10
---

# Getting Started

This page gives the shortest practical path to understanding and running the repository locally.

## 1. Know the main entrypoints

- `make agent` runs the main Rust agent.
- `make discord` runs the official Discord bot service.
- `make telegram` runs the Telegram bot service.
- `make discord-selfbot` runs the Discord selfbot relay service.
- `make wiki` starts the local wiki app.
- `make test` runs the Rust test suite.

These commands come from the root `Makefile` and are the most useful defaults for day-to-day work.

## 2. Run the main runtime

```bash
make agent
```

Direct equivalent:

```bash
cargo run -p agent --bin polyverse-agent
```

The agent composition root lives in `apps/agent/src/main.rs`.

If you are working with platform integrations, start the relevant platform binary in a second terminal after the agent is up.

The platform relay socket defaults to `/tmp/polyverse-agent-relay.sock`, and the path can be overridden with `PLATFORM_RELAY_SOCKET`.

## 3. Run the platform services

```bash
make discord
make telegram
make discord-selfbot
```

These services are intentionally separate so the platform SDKs and process models do not leak into the core agent binary.

## 4. Run the local wiki

```bash
make wiki
```

The wiki app uses `next dev --hostname 0.0.0.0`, so it is reachable on the local network unless you override the default Next.js behavior.

## 5. Run the most common checks

Run the Rust tests:

```bash
make test
```

Check a single crate:

```bash
cargo check -p cognitive
```

Run MCP tests:

```bash
cargo test -p mcp
```

Typecheck or build the wiki app directly when needed:

```bash
npm --prefix apps/wiki run typecheck
npm --prefix apps/wiki run build
```

## 6. Know the local service defaults

By default:

- MCP binds to `127.0.0.1:4790` when enabled
- MCP is disabled unless `MCP_ENABLED=true`
- MCP can run over HTTP or stdio depending on `MCP_TRANSPORT`

MCP is opt-in through `MCP_ENABLED`.

If you are connecting from an external MCP client, `MCP_TRANSPORT=stdio` is usually the most direct option. The HTTP transport remains available for local integrations that prefer a simple REST-style surface.

## 7. Read next

- Use [Repository Map](./repository-map.md) to understand where code lives.
- Use [Runtime Configuration](../operations/configuration/runtime-configuration.md) before changing environment or local runtime behavior.
- Use [Architecture](../architecture/core-runtime/) to follow the worker runtime in more detail.
