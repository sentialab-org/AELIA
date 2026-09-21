# P8 Adapter Cutover and Rollback Runbook

Updated: 2026-08-24

## Scope and current safety boundary

P8 uses the independent Python runtime backend and versioned HTTP gate protocol.
The Python CLI adapter remains a compatibility and offline test surface; it does
not wrap the V1 Rust relay and does not migrate V1 runtime data. Discord,
Telegram, and future platforms run as separate Node gate processes.

Implemented modes:

- `shadow`: kernel cycles run; adapter commands are persisted and suppressed.
- `test_canary`: only explicitly allowlisted conversations reach the idempotent
  mock transport.
- `external_canary`: only explicitly allowlisted conversations are queued for an
  isolated platform connector and require an external receipt.

No external connector starts with the Python kernel. Discord self-bot, Discord
official bot, and Telegram official bot are separate Node.js processes with
independent credential files and default-off send switches. Simulated receipts
still require `side_effect_performed=false`; external receipt `2.0.0` records
real `sent`/`not_sent`/`unknown` evidence.

## Contracts

- Adapter envelope schema version: `1.0.0`
- Kernel event schema version: `2.0.0`
- Kernel action schema version: `2.2.0`
- Kernel trace schema version: `2.3.0`
- Outbound command schema version: `1.1.0`
- Delivery receipt schema version: `1.1.0`
- Future external connector capability schema: `1.0.0`
- External delivery receipt schema: `2.0.0`

Print machine-readable JSON Schemas:

```bash
uv run polyverse adapter schema
```

The adapter owns platform SDK types and translates them into the envelope. The
kernel never imports an adapter implementation or platform SDK.

## Preflight

Run from the repository root:

```bash
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run polyverse config doctor
uv run polyverse llm doctor --probe
uv run polyverse db init
```

Required results:

- all quality gates pass;
- persona integrity is valid;
- the configured LLM endpoint completes TLS/authentication, lists the selected
  model, and the isolated backend smoke produces a bounded completion;
- SQLite migrations 1–8 are applied;
- `PRAGMA integrity_check` returns `ok`;
- no adapter dispatch is left in `reserved` state;
- adapter mode resolves to `shadow`.

## Stage 1 — CLI shadow

Keep:

```text
POLYVERSE_ADAPTER_MODE=shadow
```

Ingest a versioned envelope:

```bash
uv run polyverse adapter ingest tests/fixtures/adapter/inbound_envelope.json
```

Expected:

- one adapter ingress record;
- one kernel event/cycle;
- reconnect returns `ingress_duplicate=true`;
- any selected outbound action produces `suppressed_shadow`;
- receipt status is `suppressed`;
- `side_effect_performed=false`.

Observe shadow behavior for representative DM, group, reply, permission-denied,
opt-out, quiet-hour, failure, and reconnect fixtures.

## Stage 2 — Test canary

Test-canary mode requires an explicit conversation allowlist and a bounded rate:

```text
POLYVERSE_ADAPTER_MODE=test_canary
POLYVERSE_ADAPTER_CANARY_CONVERSATION_IDS=["test-conversation-id"]
POLYVERSE_ADAPTER_CONVERSATION_LIMIT_PER_HOUR=1
```

Only use an injected test language generator and `MockAdapterTransport`.
Non-allowlisted conversations, missing generated content, and exhausted rate
limits remain persisted as blocked receipts. A test-canary receipt is
`simulated`, never `sent`.

The CLI exposes an explicit fixed-content injector for this simulation:

```bash
uv run polyverse adapter ingest \
  tests/fixtures/adapter/inbound_envelope.json \
  --test-content "Test-only adapter response."
```

The flag is rejected outside `test_canary`; without it, the default mock
generator has no deliverable content and the dispatch remains blocked.

Promotion criteria:

- zero conflicting ingress/idempotency keys;
- zero duplicate transport calls;
- reconnect and crash-recovery tests pass;
- all blocked decisions preserve reason codes;
- rate-limit reservations remain correct under concurrency;
- replay hashes match;
- no pending outbox row remains unexplained.

## Crash recovery

| Failure point | Recovery |
|---|---|
| Before kernel commit | Redeliver the same envelope |
| After kernel commit, before ingress record | Redeliver; kernel event idempotency returns the committed cycle, then ingress is recorded |
| After ingress, before dispatch reservation | Redeliver the same envelope; dispatch is derived from the stored cycle |
| After reservation, before transport | Run `uv run polyverse adapter recover` |
| After mock transport, before final receipt | Recover with the same command idempotency key; transport returns the same receipt |
| After external send attempt, before receipt | Connector journal prevents blind retry and records `unknown` unless prior sent evidence exists |
| Structured transport failure | Keep the finalized failed receipt for audit; do not silently retry a future real side effect |

The outbox reserves rate capacity before transport. Pending and finalized
test-canary commands both count against the hourly limit.

## Rollback

1. Set `POLYVERSE_ADAPTER_MODE=shadow`.
2. Restart only the adapter process.
3. Stop test-canary ingestion if envelope translation is suspect.
4. Inspect `adapter_ingress`, `adapter_dispatches`, `cycles`, and
   `outbound_actions`; do not delete or rewrite them.
5. Replay affected cycles and compare hashes.
6. Preserve the database and logs for diagnosis.

Rollback never requires switching the Python kernel back to Rust V1. V1 remains
frozen reference material, not a production dependency or data recovery path.

## Stage 3 — Platform connector external canary

The connectors are isolated under `platforms/`. Install and verify the selected
connector without credentials:

```bash
make platforms-test
```

Create the selected connector's `.env` from its example and provide only its
token. Configure exactly one test conversation and keep the gate in shadow in
root `config.toml`:

```toml
mode = "shadow"
send_enabled = false
```

Start the independent backend, then start only the selected gate and verify
shadow ingestion first:

```bash
make backend
# another terminal:
make discord-selfbot-run
# or make discord-officialbot-run
# or make telegram-officialbot-run
```

For an owner-authorized live canary, set `mode = "external_canary"` and
`send_enabled = true`, then restart the backend and gate. The backend resolves
the gate's configured allowlist and rate cap; Node cannot inject runtime policy.
The outbox remains `reserved` until Node returns external receipt `2.0.0`. The
backend is the only process that constructs the runtime composition; starting a
gate never starts Python or rebuilds the kernel.

Rollback requires restoring `mode = "shadow"` and `send_enabled = false`, then
restarting the backend and gate. Do not delete pending commands, receipts,
cursor, or connector journal.

The executable preflight and behavioral evidence checklist are defined in
[`CONNECTOR_ACCEPTANCE.md`](CONNECTOR_ACCEPTANCE.md). Passing static preflight
does not authorize or activate delivery.
