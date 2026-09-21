# AELIA Agent

AELIA is the active development line: a strictly typed Python
cognitive kernel built around explicit observation, belief, world/self/social
models, appraisal, internal dynamics, goals, participation, action policy,
memory, learning, and shadow-only autonomy.

The Rust workspace remains a frozen V1 reference. It is not the behavioral
oracle, production fallback, or default path for new V2 work. The only V1 asset
carried forward is the byte-preserved, source-traced persona package.

## Start V2 locally

Requirements: Python 3.12+ and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cp config.example.toml config.toml
cp .env.example .env
make sync
make doctor
make init
make quality
```

Ingest the deterministic direct-mention fixture:

```bash
uv run --frozen aelia event ingest \
  tests/fixtures/events/direct_mention.json
```

The active adapter has:

- `shadow`: persist and suppress outbound commands;
- `test_canary`: allowlisted simulation through a mock transport;
- `external_canary`: queue an allowlisted command until an isolated connector
  submits an external receipt.

An OpenAI-compatible Chat Completions language provider is available through
typed configuration. The checked-in example remains `provider=mock`; real keys
belong only in ignored `.env`. Validate the configured endpoint without
sending a chat completion:

```bash
uv run --frozen aelia llm doctor --probe
```

No live platform is enabled implicitly. Three isolated Node.js connectors are
available, each with its own ignored credential file and default-off send
switch:

- [`discord-selfbot`](platforms/discord-selfbot/);
- [`discord-officialbot`](platforms/discord-officialbot/);
- [`telegram-officialbot`](platforms/telegram-officialbot/).

The runtime backend and platform gates are independent processes. The default
`make` target is the backend only:

```bash
make backend
# in another terminal
make discord-selfbot-run
```

The backend exposes `/health`, `/ready`, `/runtime/status`, and the versioned
gate protocol at `/v1/gates/ingress` and `/v1/gates/receipts`. Current operations
are unary request/response, so the boundary is HTTP; WebSocket is reserved for
future server-pushed streaming or tool events.

Normal settings—including the model route, runtime port, gate allowlists, send
switches, and timeouts—live in ignored `config.toml`. The root `.env` contains
only backend secrets. Each platform `.env` contains only that platform's token
and, optionally, the shared runtime-gate token.

For Discord selfbot, set this in `config.toml` to accept every visible channel:

```toml
[platforms.discord_selfbot]
allowed_conversation_ids = ["-1"]
```

`-1` must be used alone; the backend resolves it to the actual inbound channel
for each request.

External connector requirements are checked separately:

```bash
uv run --frozen aelia adapter connector-preflight \
  tests/fixtures/adapter/connector_capabilities.json
```

Run all offline platform checks:

```bash
make platforms-test
```

## Evidence and operating docs

- [Báo cáo hiện trạng kiến trúc V2](docs/BAO_CAO_HIEN_TRANG_KIEN_TRUC_V2.md)
- [Implementation status](docs/IMPLEMENTATION_STATUS.md)
- [Requirement evidence](docs/REQUIREMENT_EVIDENCE.md)
- [Final local audit](docs/FINAL_AUDIT.md)
- [Definition of Done](docs/DEFINITION_OF_DONE.md)
- [Adapter cutover/rollback](docs/P8_CUTOVER_RUNBOOK.md)
- [External connector acceptance](docs/CONNECTOR_ACCEPTANCE.md)

The complete V1 environment, including its `.env`, settings, config, prompts,
data, Cargo workspace and legacy Makefile, lives under
[`legacy/v1-rust/`](legacy/v1-rust/). Do not repair, extend, or migrate V1 data
as part of V2 work.
