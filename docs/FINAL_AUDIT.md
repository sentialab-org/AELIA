# AELIA — Final Local Audit

Updated: 2026-08-24
Figures re-measured: 2026-09-21 at commit `68a3359`

> **Scope note.** This audit verifies that the machinery is present, wired, and
> tested. It is a code-and-test audit; it does not measure runtime state accrual.
> Counterexamples of machinery that runs without state accruing are recorded in
> `.aelia/coordination/ARCHITECTURE_GAP.md` §A.1b.

## Verdict

The Python kernel, long-lived runtime backend, OpenAI-compatible model
boundary, adapter outbox, and three isolated Node platform gates pass
offline/local acceptance. The exact configured model route also passes an
isolated provider probe and a synthetic Discord-envelope HTTP smoke through the
real backend. A live platform canary has not been run; no external platform
side effect was activated during this audit.

## Verified evidence

| Gate | Result |
|---|---|
| Reproducible environment | `uv sync --frozen` passes |
| Continuous integration | AELIA-only GitHub Actions workflow reproduces all local quality gates |
| Formatting and lint | Ruff passes |
| Static typing | strict mypy passes for `src` and `tests` |
| Automated tests | 191 Python tests and 40 Node connector tests pass _(re-measured 2026-09-21; previously 182 and 34)_ |
| Persona preservation | 4 source artifacts match their recorded SHA-256 hashes |
| Persona specification | 43 source-traced rules and 18 behavioral scenarios |
| Fresh database | migrations 1–8 apply; `PRAGMA integrity_check` returns `ok` |
| Idempotency | reconnect reuses the stored ingress/cycle |
| Recovery | no unexplained reserved adapter dispatch remains |
| Failure semantics | failed execution is a failed structured cycle; recovered state contention is persisted and replayed |
| Logging and privacy | bounded JSON logs carry cycle/event correlation without message content |
| Architecture boundary | kernel modules do not import adapter implementations or platform SDKs |
| Dependency direction | AST conformance and internal import-cycle tests pass |
| LLM provider boundary | Async OpenAI-compatible Chat Completions; structured output, bounded retry, failure trace, replay, and secret-redaction tests pass |
| LLM external probe | Endpoint/authentication pass; `uai/claude-sonnet-4-6` is listed and full backend HTTP smoke generates content with no send side effect |
| Runtime backend/gate boundary | FastAPI backend starts without Discord; Node gates use versioned HTTP ingress/receipt calls and no production process launcher |
| External connectors | Discord self-bot, Discord official bot, and Telegram official bot; allowlists, kill switches, journal/cursor, receipts, tests, audits, and static preflights pass |
| V1 isolation | 205/205 tracked V1 files byte-preserved under `legacy/v1-rust`; Cargo metadata resolves 13 packages |
| Default developer path | root quickstart, safe AELIA env example, and machine-readable Make targets verified |

## Architecture acceptance

- The kernel is a Python modular monolith with strict, versioned Pydantic
  contracts.
- The cognitive path is explicit and sequential; asynchronous work stays at I/O
  boundaries.
- Persona, World/Conversation Models, relationship state, appraisal, drives,
  affect, goals, memory, and guardrails participate causally in policy and are
  represented in cycle traces.
- Language generation and execution are ports downstream of action selection.
- Prompt composition is module-owned, versioned, hash-traced, and contains no
  duplicated private event text.
- Resolved configuration is inspectable; the configured log level controls
  privacy-bounded JSON operational logs.
- SQLite remains the only canonical store; no graph or vector store was added.
- Initiative is shadow-only and cannot materialize an outbound action.
- The adapter supports `shadow`, allowlisted `test_canary`, and
  `external_canary`. Real commands remain reserved until a connector submits
  receipt `2.0.0`.
- Ambiguous delivery is recorded as `unknown` and is never blindly retried.
- Platform SDK/API clients and credentials remain inside isolated Node
  connectors.
- `make backend` starts only the backend, while `make discord-selfbot-run`
  starts only the Discord gate; `make dev-all` only supervises independent
  processes.
- The root `.env` contains backend secrets only; ordinary runtime/model/gate
  configuration is loaded from ignored `config.toml`.
- The old V1 persistent relay carried complete response frames rather than
  model-token streaming. Since the current provider is unary, HTTP is the
  current protocol and WebSocket is deliberately deferred until a real
  server-pushed capability exists.

## Deliberate scope decisions

- No V1 runtime data is migrated because persona continuity is the only required
  asset.
- V1 source, settings, `.env`, prompts, documentation, and local data are
  retained as one isolated legacy environment rather than mixed into the AELIA root.
- V1 behavior and response text are not compatibility oracles.
- The current participation policy enables `observe`, `silent`, `wait`, `reply`,
  and guarded group `join`. Other versioned outcomes remain disabled until a
  later behavior phase needs them.
- An OpenAI-compatible model provider is configured locally. The selected
  `uai/claude-sonnet-4-6` route is listed and passes the isolated backend HTTP
  completion smoke with `thinking_mode = "disabled"` and
  `max_output_tokens = 4096`.
- All three connectors are implemented but default to send-disabled; no real
  canary evidence has been recorded.

## Open production gate

External cutover requires all of the following:

1. a successful authenticated provider probe and bounded model-backed persona
   evaluation;
2. one selected connector credential and one allowlisted canary conversation;
3. connector-side permission and login probe;
4. a bounded live transcript proving sent/not-sent/unknown receipt semantics;
5. secrets and privacy review;
6. kill-switch rollback and observation-window evidence.

Until those inputs exist, rollback means returning the adapter to `shadow`;
Rust V1 is not a runtime fallback.
