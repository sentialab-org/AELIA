# ADR 0017: Independent runtime backend and HTTP platform gates

- Status: Accepted and implemented
- Date: 2026-08-24

## Context

The Node platform connectors normalized and delivered platform events, but each
message also launched `uv run polyverse adapter ingest -`. That made a platform
process own runtime lifecycle and rebuilt configuration, persistence,
orchestration, persona, and model clients for every inbound message.

Normal configuration was also mixed with secrets across root and per-platform
`.env` files.

## Decision

Run one independent Python backend that owns the long-lived runtime composition:

- cognition, autonomy, memory, persona, and model execution;
- SQLite repositories, idempotency, and the adapter outbox;
- server-side gate policy keyed by `adapter_id`; and
- versioned runtime protocol validation and structured errors.

Platform gates own only authentication, platform event normalization,
permissions, reconnect/rate-limit behavior, external delivery, and receipt
evidence. They use a shared Node `RuntimeClient` and cannot spawn Python or
inject adapter policy through child-process environment variables.

The initial protocol is HTTP:

- `GET /health`;
- `GET /ready`;
- `GET /runtime/status`;
- `POST /v1/gates/ingress`; and
- `POST /v1/gates/receipts`.

All currently implemented operations are unary and bounded. The legacy V1 relay
used a persistent local socket for complete response frames and a typing flag;
it did not expose model-token deltas or a server-pushed V2 event stream. V2's
current provider also sends `stream=false`, so HTTP preserves the implemented
behavior without carrying forward runtime ownership in a platform process.
WebSocket is deferred until a real server-pushed feature exists, such as token
streaming, typing, tool progress, message updates, or runtime notifications.

Normal configuration lives in ignored `config.toml`; checked-in defaults live in
`config.example.toml`. Root `.env` contains backend secrets only, and each gate
`.env` contains only its platform token plus an optional shared bearer token.

The `-1` conversation wildcard is accepted only by itself. The backend resolves
it to the actual inbound conversation before constructing adapter policy.

## Consequences

`make` and `make backend` start only the backend. Platform gates start
independently with targets such as `make discord-selfbot-run`. `make dev-all`
only supervises those independent processes.

Backend startup no longer imports Discord or Telegram packages. Production Node
gate code contains no `child_process`, `uv`, or `polyverse adapter` launch path.
HTTP and connector tests preserve envelope mapping, duplicate ingress,
transactional outbox behavior, and idempotent external receipts.
