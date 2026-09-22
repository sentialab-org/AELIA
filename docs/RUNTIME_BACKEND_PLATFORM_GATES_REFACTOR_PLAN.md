# AELIA — Runtime Backend + Platform Gates Refactor Plan

Status: implemented and locally verified; owner-authorized live canary pending  
Date: 2026-08-24

## 1. Current architecture audit

The Python kernel is already platform-neutral and the existing Pydantic adapter
contracts are suitable as the shared protocol. The ownership problem is at the
process boundary:

1. every Node platform process constructs `KernelClient`;
2. `KernelClient` starts `uv run aelia adapter ingest -` for every inbound
   platform event;
3. the child process rebuilds settings, repositories, persona, LLM provider,
   orchestrator, and adapter policy;
4. the platform process injects backend policy through child-process environment
   variables; and
5. an external receipt starts another Python child process.

The platform gates therefore do not import the Python kernel, but they still own
its lifecycle one message at a time. There is no independently addressable
runtime backend today.

Reusable boundaries already present:

- `InboundEvent` already normalizes platform, identity, conversation, reply,
  attachment, permission, and source metadata;
- `AdapterInboundEnvelope`, `AdapterOutboundCommand`, and
  `ExternalDeliveryReceipt` are strict, independently versioned contracts;
- `AutonomyOrchestrator` owns the platform-independent cognitive runtime;
- `SqliteKernelRepository` and `SqliteAdapterRepository` own durable state,
  idempotency, outbox, and recovery;
- each Node connector already owns only platform normalization, permissions,
  delivery, rate observation, and reconnect behavior apart from `KernelClient`.

Configuration is currently split incorrectly. The root `.env` contains secrets
and ordinary behavior settings, while each gate `.env` contains its token plus
allowlists, paths, timeouts, and switches. Python settings are centralized, but
normal configuration is not separated from secrets and Node gates read
environment variables directly.

## 2. Target architecture

```text
Discord / Telegram / future platform
                │
                ▼
        platform-specific gate
        normalization + delivery
                │
        versioned HTTP protocol
                │
                ▼
       independent runtime backend
  config + orchestrator + LLM + memory
       state + outbox + persistence
```

Dependency direction:

```text
platform gate -> runtime protocol contracts -> backend application
                                             -> runtime/core services
                                             -> storage and LLM ports
```

The backend must not import any platform package or SDK. Gates may depend on the
wire schemas, but never start, import, or configure the runtime implementation.

## 3. HTTP versus WebSocket decision

Use HTTP for this refactor because every implemented operation is currently a
bounded request/response operation:

- `GET /health` for liveness;
- `GET /ready` for initialized runtime readiness;
- `GET /runtime/status` for redacted status;
- `POST /v1/gates/ingress` for one normalized inbound envelope and its completed
  trace/dispatch result; and
- `POST /v1/gates/receipts` for external delivery finalization.

The current LLM provider is non-streaming, the runtime does not emit typing or
tool-progress events, and the outbox returns a command in the ingress response.
Adding WebSocket now would add reconnect, subscription, buffering, and delivery
ordering semantics without a current producer.

Reserve WebSocket for a later protocol version when at least one real
server-pushed capability exists (token streaming, typing, tool events, message
updates, or runtime notifications). That endpoint must reuse the same versioned
event/command contracts and idempotency keys rather than introduce a parallel
message model.

## 4. Minimal implementation structure

```text
src/aelia/
├── app/
│   ├── bootstrap.py          # one runtime composition root
│   └── config.py             # config.toml + secret environment loader
├── backend/
│   ├── application.py        # long-lived runtime service
│   ├── api.py                # HTTP boundary and structured errors
│   └── main.py               # independent backend process entry point
├── contracts/
│   ├── adapter.py            # existing wire contracts
│   └── runtime_api.py        # API response/status/error contracts
├── adapters/
│   └── runtime.py            # platform-neutral adapter/outbox service
└── ... existing cognition, runtime, storage, persona, and LLM modules

platforms/
├── node-common/
│   ├── runtime-client.js     # HTTP protocol client; never spawns Python
│   └── config.js             # shared TOML/config helpers
└── discord-selfbot/ ...      # platform-only integration
```

Do not move or rewrite the cognitive modules. Rename the CLI-specific adapter
service conceptually while keeping a compatibility alias for existing tests and
operator commands.

## 5. Configuration model

- `config.toml` is the local non-secret configuration source.
- `config.example.toml` is the checked-in safe template.
- root `.env` contains backend secrets only, initially the LLM API key and an
  optional runtime-gate bearer token.
- each gate `.env` contains only that gate's platform credential and the
  optional runtime-gate token.
- Python code accesses configuration only through `load_settings()`.
- Node gates access configuration only through their `loadConfig()` boundary,
  which reads the same root TOML file plus the gate secret file.

Normal TOML configuration includes runtime host/port/client URL, SQLite paths,
agent/autonomy policy, model provider/base/model/tokens, gate enablement,
allowlists, send switches, state paths, and timeouts.

The backend maps the authenticated/declared `adapter_id` to a server-side gate
policy. A gate can no longer choose backend mode or canary scope by setting child
process environment variables. Wildcard `-1` remains supported by resolving it
to the actual inbound conversation for that request.

## 6. Migration phases

1. Add the composition root and centralized configuration loader while keeping
   CLI behavior working.
2. Add the long-lived runtime application and HTTP server.
3. Add strict runtime API contracts, request IDs, bounded bodies, and structured
   errors.
4. Replace Node `KernelClient` process spawning with `RuntimeClient` HTTP calls.
5. Convert all existing gates so none can start Python.
6. Move ordinary values from `.env` files to TOML and retain only secrets.
7. Redesign Make targets:
   - `make` and `make backend` start only the backend;
   - `make discord-selfbot-run` starts only that gate;
   - existing `*-start` targets remain compatibility aliases;
   - `make dev-all` only supervises independent processes.
8. Update ADR/runbook/README evidence and architecture checks.

## 7. Verification and acceptance

Required evidence:

- backend starts and answers health/readiness without loading Discord;
- source and runtime dependency checks show no platform import in the backend;
- no Node production file imports `child_process` or invokes `uv`/`aelia`;
- a mocked platform envelope reaches the live ASGI application and returns a
  valid runtime result;
- duplicate ingress preserves the same cycle and dispatch;
- external receipt finalization remains idempotent;
- Discord gate tests prove event normalization and runtime-response delivery;
- attachment, reply, conversation, and actor mappings remain unchanged;
- `.env.example` and gate env examples contain secret keys only;
- normal settings resolve from TOML and `config doctor` remains redacted;
- `make backend` and `make discord-selfbot-run` have independent process
  ownership and clean shutdown;
- Ruff, mypy, Python tests, all Node tests, and connector preflights pass.

The refactor is complete only when the old per-message Python spawn path is
removed, not merely bypassed.
