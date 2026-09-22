# CURRENT_STATE — what this repository factually is

**updated_at:** 2026-09-22T00:00:00Z
**verified_at:** 2026-09-22T00:00:00Z (branch `rebrand/aelia`, commit `68a3359`)
**method:** read-only inspection of the working tree, plus read-only queries
against `data/aelia.db`. Nothing in this file was executed against a live
platform.

This file records **facts about the repository**. It does not record intent, and
it does not describe the target AELIA. For the target, see
`ARCHITECTURE_GAP.md`.

---

## 1. Repository identity

| Fact | Value | Evidence |
|---|---|---|
| Remote | `https://github.com/sentialab-org/AELIA.git` | `git remote -v` |
| Local path | `/Users/zvwgvx/Project/AELIA` | — |
| Active branch | `rebrand/aelia` | `git rev-parse --abbrev-ref HEAD` |
| HEAD | `68a33592203d9cf10e035405a4cef384d9d662d7` | `git rev-parse HEAD` |
| Tracking | `origin/rebrand/aelia`, in sync | `git rev-list --left-right --count origin/rebrand/aelia...HEAD` → `0 0` |
| Working tree | clean except untracked `.aelia/` | `git status --short` |
| Package | `aelia` (`src/aelia`), CLI `aelia` / `aelia-backend` | `pyproject.toml` |
| Python | 3.12+ (venv is 3.13) | `pyproject.toml`, `.venv/lib/python3.13` |

**Lineage.** `zvwgvx/ryuuko-chatbot` → `polyverse-agent` → `sentialab-org/AELIA`.
The rename of the *local tree* to AELIA landed on this branch on 2026-09-21
(`e6aa49c`, `68a3359`). See `EVENTS.jsonl` `evt-2026-09-21-001..004`.

**`main` diverges.** `origin/main` is 10 commits ahead of local `main` and is
still the **V1 Rust monorepo at root** (`.cargo/`, `Cargo.toml`, `apps/`,
`libs/`, `services/`). Merging `rebrand/aelia` into `main` is a large structural
merge and is **not authorised**. The single content conflict is
`docs/wiki/local-interfaces/platform-relay.md`, which upstream added inside a
directory this branch renamed; its correct home here is
`legacy/v1-rust/docs/wiki/local-interfaces/`.

---

## 2. Size and shape

| Measure | Count | Command |
|---|---|---|
| Python sources under `src/aelia` | 73 files, 13,490 lines | `find src/aelia -name '*.py' \| wc -l` |
| Python test files under `tests` | 39 | `find tests -name '*.py' \| wc -l` |
| Collected pytest cases | 191 | `pytest --collect-only -q` |
| ADRs | 17 (`docs/adr/0001..0017`) | `ls docs/adr \| wc -l` |
| Node connector packages | 4 (`platforms/*`) | `ls -d platforms/*/` |
| DB migrations | 8 (24 tables + `schema_migrations`) | `src/aelia/storage/migrations.py` |

Top level: `LICENSE`, `Makefile`, `README.md`, `config.example.toml`,
`config.toml`, `data/`, `docs/`, `legacy/`, `platforms/`, `pyproject.toml`,
`src/`, `tests/`, `uv.lock`.

`src/aelia/` subpackages (12): `adapters`, `app`, `autonomy`, `backend`,
`cognition`, `contracts`, `llm`, `models`, `persona`, `runtime`, `storage`.

`tests/` subdirectories: `architecture`, `behavioral`, `contract`, `fixtures`,
`integration`, `replay`, `unit`.

---

## 3. How it runs today

| Entry point | Command | Status |
|---|---|---|
| Backend HTTP service | `make backend` → `aelia-backend` | IMPLEMENTED — `src/aelia/backend/main.py` |
| CLI | `uv run --frozen aelia …` | IMPLEMENTED — `src/aelia/cli.py` |
| Ingest one event | `aelia event ingest <file.json>` | IMPLEMENTED |
| Connector processes | `make discord-selfbot-run`, `make telegram-officialbot-run` | IMPLEMENTED, `send_enabled` default off |
| Autonomy | `AutonomyOrchestrator` only | IMPLEMENTED, shadow-only — see §6 |

Endpoints exposed by the backend: `/health`, `/ready`, `/runtime/status`,
`/v1/gates/ingress`, `/v1/gates/receipts`. HTTP because current operations are
unary request/response; **WebSocket is reserved and ABSENT**.

The only orchestrator reachable from a production entrypoint is
`AutonomyOrchestrator` (`src/aelia/app/bootstrap.py:105-111`). The Foundation,
Observation, Persona, Cognitive, Action and Memory orchestrators (`v2-001`
through `v2-006`) are constructible but unreachable outside tests and
`ReplayService`. `v2-007` has no constant, producer, or replay branch — an
orphaned version label.

---

## 4. Persistence

Single SQLite database at `data/aelia.db` (WAL). **Never delete.** It is
gitignored and holds real user data.

**Measured 2026-09-21, read-only** (`file:…?mode=ro`, `PRAGMA query_only=ON`):

| Measure | Value |
|---|---|
| File size | 748,343,296 bytes (713.68 MB of live pages) |
| Cycles recorded | 4,085 (≈2.7 days of traffic) |
| Largest tables | `cycle_artifacts` 349.58 MB, `cycles` 311.27 MB — **92.6% of the database between them** |
| `cycle_artifacts` rows | 85,832 (= 21.0 per cycle) |
| Inbound events | 4,085 |
| Memory records | 4,718 _(corrected 2026-09-22; see change log)_ |
| **`beliefs`** | **0 rows** |
| `outbound_actions` / `adapter_dispatches` | 9 / 9 |
| Growth | ≈264 MB/day, no reaper for the trace tables |

The database is the only place where "the machinery ran" and "state accrued" can
be told apart. See `ARCHITECTURE_GAP.md` §A.1b — G-37, G-38 and G-44 are
measurements that source-reading could not produce.

Forbidden-file status: `data/` is untracked and ignored; `.env` and
`config.toml` are ignored; `platforms/*/.env` are ignored.

---

## 5. Configuration and secrets

- Root `config.toml` (ignored) — normal settings. Current live values include
  `[platforms.discord_selfbot] allowed_conversation_ids = ["-1"]` and
  `mode = "external_canary"` with `send_enabled = true` for the selfbot. **This
  configuration is live-capable.** Treat any run against it as touching a real
  platform.
- Root `.env` (ignored) — backend secrets.
- `platforms/*/.env` (ignored) — per-platform token, optional gate token.
- `.env.example` files are tracked and must stay key-for-key equal to the real
  ones; `tests/unit/test_v2_env_example.py` asserts this.

**Key names only are ever recorded in this coordination layer. No values.**

---

## 6. What is live vs. what is inert

This is the distinction the protocol exists to protect. Read it as the single
most important table in this file.

### Live on the production path
- Ingress → cycle → persistence → dispatch decision → outbox → receipt.
- Governance: optimistic state-version concurrency under `BEGIN IMMEDIATE`.
- The persona block is composed into the prompt and hashed.
- The language provider is wired (`provider=mock` in the checked-in example; an
  OpenAI-compatible provider is implemented).
- Guardrails evaluate every initiative and produce a decision.

### Present but not reachable from production
- Six of the seven orchestrators.
- `GoalManager.merge`, `resolve_path`, `set_autonomy_opt_out`,
  `recover_pending()` from the backend, `verify_sources()`,
  `load_active_source`, the connector conformance policy.
- Every `ExternalDeliveryReceipt` producer: `ExternalReceiptStatus` has no
  producer in `src/`, so the external-canary finalization path is unexercised.
- Ten of the 24 tables have no read path anywhere in `src/`.

### Permanently closed by construction
- `proactive_action_materialized` is `Literal[False]`
  (`src/aelia/models/autonomy.py:186`) and a DB `CHECK(… = 0)`
  (`src/aelia/storage/migrations.py:373-374`).
- `vector_index_used` is `Literal[False]` (`src/aelia/models/memory.py:129`).
- `GuardrailOutcome` has **no member that authorises an action** — only
  `BLOCKED`, `REQUIRE_CONFIRMATION`, `SHADOW_APPROVED`
  (`src/aelia/autonomy/guardrails.py`), and the mode check passes only for
  `SHADOW` (`:52`).

---

## 7. Verification surface

`make quality` = `ruff format --check` → `ruff check` → `mypy src tests`
(strict) → `pytest -q` → `node --check` → connector preflight.

`tests/architecture/` holds the executable architecture gates: dependency
direction and acyclicity, legacy separation, rename identity, runtime/backend
separation. These gates are **load-bearing** — they are what keeps the layer
rules true — and they are **not self-verifying**: a gate whose directory walk
comes back empty passes vacuously. Non-vacuity assertions were added in
`68a3359` after the rename emptied four of them.

Known divergence: `Makefile:61` runs `node --check` over `runtime-client.js` but
`.github/workflows/quality.yml:77-80` does not, so a syntax error in that file
passes CI.

---

## 8. Frozen and out-of-scope

| Path | Status |
|---|---|
| `legacy/v1-rust/**` | FROZEN, byte-preserved (ADR 0013). Not repaired, extended, or migrated. |
| `src/aelia/persona/source/archive/*.txt` | Byte-pinned by sha256 (ADR 0002). Never edited. |
| `data/**` | Real user data. Never deleted. |
| v1-rust `Worker`/`EventBus`/`Coordinator`/UDS relay | Reference only. Not the behavioural oracle. |

---

## 9. Change log

| Date | Change |
|---|---|
| 2026-09-21 | Initial state recorded at `68a3359` (coordination bootstrap). |
| 2026-09-21 | §4 rewritten with measured production-corpus figures after a completeness review found the first pass had not queried `data/aelia.db`. |
| 2026-09-22 | §4 `memory_records` corrected 7,418 → **4,718**. The original figure did not reproduce and no table in the corpus holds 7,418 rows; recorded as `EVENTS.jsonl` `evt-2026-09-22-009`. |
| 2026-09-22 | Documentation standardised: all `docs/*.md` converted to English, `V2` product-name residue replaced with `AELIA`, stale figures re-measured, broken relative links repaired, `README.md` reduced to a work-in-progress stub. The nine-document cross-check against this file and `ARCHITECTURE_GAP.md` is recorded in `ARCHITECTURE_GAP.md` §A.1c. |
