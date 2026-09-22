# ARCHITECTURE — the Python kernel as implemented

**updated_at:** 2026-09-22T00:00:00Z
**basis:** commit `68a3359`, `src/aelia` (73 files / 13,490 lines), read-only.
**labels:** `IMPLEMENTED` · `PARTIAL` · `STUB` · `ABSENT` (see `PROTOCOL.md` §4).
**cross-ref:** `ARCHITECTURE_GAP.md` §A.1b carries the findings that were measured
against `data/aelia.db` rather than read from the source; §A.1c carries the
per-document cross-check added on 2026-09-22.

This file describes **what the code does**. It does not describe what the system
is meant to become. Where a doc, ADR, comment, or type annotation describes a
capability the code does not contain, that is recorded here as the state the
code is actually in — not as the state the annotation claims.

---

## 1. Layer map

`src/aelia/` is twelve packages under one enforced import direction:

```
contracts ──► models ──► cognition ──► runtime ──► app ──► backend
                 │           │            │
                 └───────────┴────────────┴──► storage, llm, persona, adapters, autonomy
```

The direction is enforced, not conventional: `tests/architecture/test_dependency_direction.py:9-46`
holds a literal `FORBIDDEN_PREFIXES` table and asserts the internal module graph
is acyclic by DFS (`:130`). `:110-128` asserts no core layer imports a platform
SDK (`discord`, `telegram`, `telethon`, `aiogram`, `platforms.`).

Two gates guard the JS side: `tests/architecture/test_runtime_backend_separation.py:22-31`
(backend imports no platform package) and `:34-51` (production JS contains no
`child_process`/`spawn(`/`exec(`/`uv run`/`aelia adapter`).

**`tests/architecture/test_legacy_separation.py`** asserts no `src/aelia` source
mentions `legacy/v1-rust` (`:34-43`) and that root holds no Cargo artefacts.

**Gate robustness — a known weakness.** These gates walk the tree; a walk that
returns nothing passes vacuously. `:58` now asserts
`len(PACKAGE_ROOT.rglob("*.py")) >= 70` before the loop, and the legacy and
separation gates similarly assert non-empty. The margin is thin: the real count
is 73.

---

## 2. Entrypoints and composition roots

**`src/aelia/app/bootstrap.py` is the intended single composition root.** It
builds the repository, ports, LLM provider, and orchestrator. `bootstrap.py:105-111`
constructs `AutonomyOrchestrator`, and **nothing else** — the other six
orchestrators are never wired here.

**The CLI is a second, divergent composition root.**
`src/aelia/cli.py:184-206` re-implements the wiring that `bootstrap.py:31-32`
claims prevents drift. Two roots means the claim is not enforced by structure.

**Provider selection is duplicated** between `bootstrap.py:71-88` and
`cli.py:209-226`.

| Entrypoint | Site |
|---|---|
| Backend service | `src/aelia/backend/main.py` → `application.py` → `api.py` |
| CLI | `src/aelia/cli.py` (a Typer app) |
| Backend ASGI app | `src/aelia/backend/api.py:81-83` (`docs_url`/`redoc_url`/`openapi_url` all `None`) |

---

## 3. The cycle — runtime data flow

`src/aelia/runtime/orchestrator.py` is the spine. Only `AutonomyOrchestrator`
runs in production; the chain below is the delegation it follows.

```
AutonomyOrchestrator.transition   orchestrator.py:1246
  └─► MemoryOrchestrator.transition          (delegates)
        └─► ActionOrchestrator.transition     orchestrator.py:758
              ├─ ConversationPolicy().project                    (context)
              ├─ AttentionPolicy().evaluate                      (attention)
              ├─ PerceptionPolicy().perceive                     (cognition/perception.py)
              ├─ BeliefPolicy()                                  (cognition/beliefs.py)
              ├─ AppraisalPolicy()                               (cognition/appraisal.py)
              ├─ InternalDynamics()                              (cognition/dynamics.py)
              ├─ GoalManager()                                   (cognition/goals.py)
              ├─ ActionPolicy() + TurnTakingPolicy()  ──► OutboundAction
              ├─ language_port.create_content_plan(...)          ports.py
              ├─ language_generator.generate(...)                ports.py
              └─ execution_port.execute(action)                  ports.py
  └─► one transaction writes the whole cycle result; optimistic
      state-version check, mismatch → ConcurrentStateError → bounded retry
      (ADR 0010)
```

**Retry loop is copy-pasted, not shared.** The same retry block appears verbatim
six times: `orchestrator.py:217-248`, `:339-377`, `:497-542`, `:705-755`,
`:972-1042`, `:1158-1243`. Six copies of one policy is a correctness hazard, not
a style issue: a fix applied to five of them looks applied.

**Determinism guarantee at the language boundary is enforced.**
`src/aelia/contracts/traces.py:179-202` raises if
`language_generation.changed_participation` is set, or if the generation
contradicts the decision. Language cannot alter the decision.

**But the live wiring makes both language ports mock.** No production
orchestrator injects a real `LanguagePort`, so `ContentPlan` always originates
from `MockLanguagePort` (`orchestrator.py:1149`), and the default `ExecutionPort`
is the mock, so `execution_result` is always `SIMULATED`. The OpenAI-compatible
provider is real (`src/aelia/llm/openai_compatible.py`) and is reachable — but
not through the cycle as wired.

**An expected executor failure does not re-route.** With mock wiring, a SKIPPED
language generation still proceeds to execution; only `FAILED` blocks.

---

## 4. Component blocks

### 4.1 contracts (`src/aelia/contracts/`)
Versioned boundary types. `actions`, `adapter`, `common`, `connector`, `events`,
`observation`, `participation`, `runtime_api`, `traces`.

- `CURRENT_TRACE_SCHEMA_VERSION = "2.3.0"` — `contracts/traces.py:42`
- Four `CURRENT_*_SCHEMA_VERSION` constants exist and are **unused**.
- **Two versioning idioms coexist**: a `Literal[...]` `schema_version` on the
  envelope types, and a free-form `str` `policy_version` elsewhere. They are not
  reconciled anywhere.
- **One version comparison is a hardcoded literal**:
  `adapters/repository.py:451` — `if parsed_receipt.get("schema_version") == "2.0.0":`.
- **`PermissionContext` is never constructed in `src/`.** Its `scopes` default
  to `()` (`contracts/events.py:71`), so every scope-dependent guardrail reads an
  empty set. Nothing mints `proactive_message`, `confirm:<proposal_id>`, or
  `proactive_private`.
- `~2/3` of the declared event vocabulary is unreferenced.
- Ingress dedup hashes the envelope **including `schema_version`**, so a schema
  bump silently converts a duplicate into a hard conflict.
- `RuntimeApplication.status_payload` returns an untyped `dict`
  (`backend/application.py:138-151`).

### 4.2 models (`src/aelia/models/`)
Pydantic types for `autonomy`, `belief`, `cognition`, `conversation`, `goals`,
`memory`, `perception`, `prompt`, `self_model`, `social`, `world`.

Two literal `False` fields act as architectural locks — see §6 of
`CURRENT_STATE.md`: `models/autonomy.py:186` (`proactive_action_materialized`)
and `models/memory.py:129` (`vector_index_used`).

### 4.3 cognition (`src/aelia/cognition/`)
`action_policy`, `appraisal`, `attention`, `beliefs`, `conversation`,
`deliberation`, `dynamics`, `goals`, `memory`, `participation`, `perception`,
`social`, `world`.

This is the largest block and the most unevenly implemented.

| Component | State | Site / note |
|---|---|---|
| Perception | `PARTIAL` | `perception.py:83-96` extracts age; `:98-112` extracts description. Two regex patterns only. |
| Attention | `PARTIAL` | `attention.py:138-146` — MEDIUM is indistinguishable from LOW. `:91-97` — `goal_domain_relevance` is a flat `0.70` for "question + open invitation in a group". |
| Beliefs | `PARTIAL` | `beliefs.py:82` — confidence moves a flat `+0.05` per observation. `BeliefStatus.REJECTED` is unreachable; a CONTESTED belief can never return to PROVISIONAL/ACCEPTED. |
| Appraisal | `PARTIAL` | `appraisal.py:54` emits reason code `'goal_relevance_placeholder'`; `:66` sets `goal_relevance=0.0`. There is **no goal linkage**. |
| World model | `PARTIAL` | Rebuilt and **discarded every cycle**. No table, no loader; only a `cycle_artifacts` row (`storage/repositories.py:656-657`). 3 of 5 `WorldStatementKind`s are write-only. |
| Internal dynamics | `IMPLEMENTED` | Drives are computed and feed autonomy trigger detection. |
| Goals | `PARTIAL` | `goals.py:228-303` `GoalManager.merge` has **zero call sites in `src/`**. `Goal.allowed_actions` and `conflict_set` are written, never read. `goals.py:98` hardcodes `USER_REQUEST`, making three `InternalTriggerType` branches unreachable. |
| Deliberation | `STUB` | `deliberation.py:20-30` declares `DeliberationPort` with no implementer. |
| Action policy | `IMPLEMENTED` | Scores and selects one schema-bound candidate. `policy_version` reports `'action-policy-v2'` whenever `memory_retrieval is not None` — a constant dressed as a version. |
| Memory | `PARTIAL` | See §4.4. |
| Social | `PARTIAL` | `social.py:18-29` holds a privacy phrase list; `:49-54` updates relationship state by **naive substring match on user content**. Two independent copies of the phrase list exist (`social.py:18-29` and `persona/disclosure.py`). `SocialState.attachment` is structurally dead. |
| Self-model | `PARTIAL` | Content is inert. `models/self_model.py:95-122` declares a literal capability `'limitation.no_live_language_model'` that **contradicts the real LLM wiring**. |

### 4.4 memory (`src/aelia/cognition/memory/`)
The learning loop **terminates at INSERT**. `cycle_outcomes`, `learning_proposals`
and `reflection_triggers` have no read path anywhere in `src/`.

- Summaries are fixed template strings, not generated.
- Retrieval is dominated by the per-turn buffer: working memory scores
  `0.8`/`1.0`/`OBSERVED` against episodic `0.4`.
- Retrieved memory **never reaches the prompt path**.
- Canonical refs are never resolved.
- Replay does not verify retrieval — `runtime/replay.py:157-159`, `:179`,
  `:200-201`, `:223`.
- Consolidation, decay, and forgetting are `ABSENT`. `decay_policy` is
  decorative.
- `load_memory_candidates` over-fetches with `query.limit * 10` and returns the
  over-fetched set **untruncated** (`storage/repositories.py:439`, `:454`).

### 4.5 persona (`src/aelia/persona/`)
`disclosure`, `loader`, `models`, `participation`, `selector`, `source`.

- The persona is versioned evidence: sources are sha256-pinned in
  `persona/source/manifest.json`; `persona_id` is **`ryuuko`** and is deliberately
  separate from the system name (ADR 0002).
- `verify_sources()` runs only in the CLI `config doctor` and in tests.
- **Raw active source text is never used at runtime** — `load_active_source`'s
  sole caller is a test.
- The disclosure ceiling is **advisory prompt text only** (`ports.py:70-80`).
- `selector.py:32`, `:36-38`, `:61-64` use **unanchored substring matching** —
  `'age'` matches `message`, `language`, `page`, `manage`.
- `ConversationLanguage.MIXED` and `.ANY` are never produced; `selector.py:112-133`
  is a hard binary VI/EN switch.
- Selector rules are coupled to spec rule ids by **bare string literals** and
  raise `ValueError`, aborting the cycle, on a mismatch.
- 8 of 43 spec rules are unreachable; the typed rule taxonomy is decorative.
- `loader.py:155-161` `_find_repository_root` **still carries a V1-Rust branch**.
- The identical persona block is **triplicated** across orchestrators:
  `orchestrator.py:395-405`, `:577-603`, `:798-831`.

### 4.6 llm (`src/aelia/llm/`)
`config`, `openai_compatible`, `prompts`.

- OpenAI-compatible Chat Completions provider: `IMPLEMENTED`.
- **No streaming.** `"stream": False` at `openai_compatible.py:340` is the only
  occurrence of `stream` in the package.
- **Prompts are hashed on paths that never send them**: composition + sha256 runs
  in the Persona (`orchestrator.py:421-442`) and Cognitive (`:622-642`) slices,
  whose prompt is then discarded.
- `MAX_RESPONSE_BYTES` is enforced **after** the whole body is buffered.
- One scalar timeout for all phases; a new `httpx.AsyncClient` per request;
  `Retry-After` truncated to 30 s.
- `_plain_text_fallback` accepts any non-brace text.
- The prompt-required guard raises a bare `ValueError` that **escapes the retry
  loop**.
- `thinking` is a non-standard vendor key sent whenever `thinking_mode != AUTO`
  (`:343-344`).
- `JSON_SCHEMA` response mode is implemented but the shipped default is
  `JSON_OBJECT`.
- The declared `input_schema="aelia.contracts.actions.OutboundAction@2.2.0"` is
  **factually wrong** about what `compose()` receives.
- Prompt registry `input_schema`/`output_schema` are inert.
- Prompt definition version is `1.2.0` (`llm/prompts.py:21`), bumped by the
  rename; ADR 0014 still records an older number.

### 4.7 autonomy (`src/aelia/autonomy/`)
`guardrails`, `initiative`.

- **`GuardrailOutcome = {BLOCKED, REQUIRE_CONFIRMATION, SHADOW_APPROVED}`.** There
  is no outcome that authorises an action. The mode check passes only for SHADOW
  (`guardrails.py:52`).
- **`REQUIRE_CONFIRMATION` is unreachable on the live path by construction**:
  `initiative.py:201` hardcodes `reversible=True` and `:181-185` fixes risk at
  MEDIUM.
- Initiative scoring is **fully hardcoded**: `estimated_cost` is always `0.5`
  (`initiative.py:199`); `expected_value` is a per-type constant table
  (`:175-180`). The daily cost budget and `minimum_expected_value` therefore gate
  on constants.
- `PolicyVersion` labels disagree between the evaluation and the decision
  (`orchestrator.py:1330` vs `initiative.py:20`).
- The per-cycle counter bump is not persisted — `running_runtime` is rebuilt
  inside the loop (`orchestrator.py:1300-1336`) and the un-bumped
  `autonomy_runtime` is what gets stored.
- One goal can emit two triggers (`COMMITMENT_DUE` + `DEADLINE_DUE`) because the
  branches are independent (`initiative.py:36-59`).
- `evidence_audit_ids` is write-only (`storage/repositories.py:546` writes;
  `models/autonomy.py:82` declares).
- Budget counts only `SHADOW_APPROVED` (`storage/repositories.py:512`), so a
  blocked decision consumes no budget despite having incurred trigger and
  proposal cost.
- **No test asserts a successful send originating from autonomy.** Every autonomy
  assertion is negative.
- `set_autonomy_opt_out` (`storage/repositories.py:549-588`) has **no production
  caller**, so the opt-out guardrails are unreachable in production.

### 4.8 adapters (`src/aelia/adapters/`)
`conformance`, `repository`, `runtime`. Implements the versioned adapter with a
transactional outbox (ADR 0008).

- Modes: `shadow` (persist, suppress), `test_canary` (allowlisted simulation via
  mock transport), `external_canary` (queue until an external receipt arrives).
- **Outbox recovery cannot drain external-canary rows.** `_complete_reservation`
  returns `QUEUE_EXTERNAL_CANARY` rows unchanged (`runtime.py:189-198` with
  `:259-262`), so they stay `RESERVED` forever.
- `recover_pending()` is **not wired into the service**; its only non-test caller
  is `cli.py:486`.
- A fresh `RuntimeAdapter` and `MockAdapterTransport` are built **per ingress
  request**.
- `finalize` does **not** verify its optimistic `UPDATE` matched a row.
- Conformance is **never enforced by the runtime** — call sites are `cli.py:308`
  and `tests/unit/test_connector_readiness.py` only.
- **`ConnectorReadinessPolicy` performs no probing.** `conformance.py:56-70`
  copies manifest booleans into evidence strings, and `:71` sets the verdict to
  `all(declared flags)`. A hand-asserted `capabilities.json` becomes
  `ready_for_authorized_canary`. The policy's own docstring concedes it is a
  static gate.
- `AdapterPolicyConfig.policy_version` is a dead field.

### 4.9 storage (`src/aelia/storage/`)
`database`, `migrations`, `repositories`.

- 24 tables + `schema_migrations`, across 8 migrations
  (`migrations.py:15-466`).
- **The trace is written twice.** `store_observation_cycle` writes one
  `trace_json` blob per cycle into `cycles` **and** explodes the same trace into
  ~21 `cycle_artifacts` rows. Measured over the live corpus: 311.27 MB + 349.58 MB
  = 92.6% of the database. `cycle_artifacts` holds 85,832 rows over 4,085 cycles.
- **Retention covers exactly two tables** — `conversation_buffer`
  (`repositories.py:1530`) and `conversation_participation` (`:1541`). Nothing
  prunes `cycles` or `cycle_artifacts`, which grow at ~264 MB/day.
- **Ten tables have no read path anywhere in `src/`.**
- **17 `*_sha256` columns are written; exactly one is ever compared** —
  `inbound_events.payload_sha256` (`repositories.py:169`, `:752`).
- **One inbound event's text is persisted at least four times**:
  `inbound_events.payload_json`, `conversation_buffer`, `memory_records`, and
  inside `cycles.trace_json` via `ObservationSnapshot.recent_messages`
  (`contracts/observation.py:38-43`).
- **Conversation state is not platform-namespaced; social state is.**
  `conversation_state` is `conversation_id TEXT PRIMARY KEY` with no platform
  column (`migrations.py:80-85`); `social_relationships` is
  `UNIQUE(platform, actor_id)` (`:145-155`). Both Discord connectors derive
  `conversation_id` from the bare channel id, so the same channel seen through
  both connectors collides in conversation state but not in social state.
- `store_foundation_cycle` is reachable only from tests.
- **Migration application is not concurrency-safe.**
  `apply_migrations` reads applied versions outside any lock (`migrations.py:463-464`)
  and the DDL that follows (`:469`) lacks `IF NOT EXISTS`.
- No connection pooling.
- `cycle_artifacts` is write-only, so artifact-level schema-version drift is
  undetectable.
- The redaction key set includes the generic key `"value"`
  (`runtime/observability.py:11-22`).

### 4.10 backend (`src/aelia/backend/`)
`api`, `application`, `main`. FastAPI over the runtime.

- **Gate-token auth fails open.** With `AELIA_RUNTIME_GATE_TOKEN` unset,
  `/v1/gates/ingress`, `/v1/gates/receipts` and `/runtime/status` are **fully
  unauthenticated** (`api.py:133-138`). When set, it is compared with
  `hmac.compare_digest` (`:129-138`).
- `/health` is a **constant stub** that ignores `application` (`api.py:177-179`).
- `/ready` **never returns non-200** (`api.py:181-189`).
- `shutdown()` is a flag flip (`application.py:69-72`).
- `recover_pending` is unreachable from the backend.
- **Gate allowlist trap**: an empty `allowed_conversation_ids` rejects every
  envelope with 403 (`application.py:94-96`).
- `resolve_path` (`app/bootstrap.py:127-129`) has no caller.
- `runtime_public_url` (`app/config.py:110`) is declared, validated, and
  TOML-mapped, but never read by Python.
- `db init` (`cli.py:332-341`) **prints without migrating**.
- `_STRUCTURED_FIELDS` (`app/logging.py:9-20`) whitelists `"command"` (zero emit
  sites) while the actual emits are `command_id`/`delivery_status`
  (`cli.py:322-327`) — **silently dropped**.
- **The runtime package emits no logs whatsoever.**

### 4.11 platforms (`platforms/`)
Four isolated Node packages: `node-common`, `discord-selfbot`,
`discord-officialbot`, `telegram-officialbot`. Normalize platform events into the
adapter envelope, POST to `/v1/gates/ingress`, and deliver only commands the
backend returns as `queue_external_canary`.

Real and load-bearing: `RuntimeClient` (`node-common/runtime-client.js`), the
TOML/env config kernel (`config.js`), the fsynced append-only `DeliveryJournal`
(`journal.js`), `createExternalReceipt` (`receipts.js`), and the three
entrypoints + connectors.

Enforced invariants include: every response must carry
`api_version "1.0.0"` or the client throws (`runtime-client.js`); responses over
5 MB are rejected (`:5`, `:88-93`); `sendEnabled` must be literally `true` before
any send (`discord-selfbot/src/connector.js:139-141`); the journal attempt record
is fsynced **before** the platform side effect; an interrupted attempt is
reported `unknown` with `retryable: false` and never retried
(`connector.js:67-75`, `receipts.js:34`); a duplicate inbound reconciles the
stored receipt instead of re-sending (`connector.js:61-66`).

Notable gaps:
- **`max_sends_per_hour` is parsed, validated, printed — and enforced nowhere**
  (`discord-selfbot/src/config.js:101-107`, `:122`). The `.env` comment claiming
  "the Python external-canary outbox enforces the same cap" describes a control
  that does not exist on either side.
- **A command failing connector-side validation throws with no receipt written**,
  stranding the backend's reserved dispatch forever
  (`connector.js:60`; the backend's `_complete_reservation` never drains it).
- Telegram captures `retry_after` into `TelegramApiError.retryAfter` and never
  consumes it; the polling loop sleeps a fixed 1 s on every error class
  (`telegram-officialbot/src/api-client.js:6`, `:11`, `:100`).
- `adapterMode` is parsed by officialbot/Telegram and **never enforced**; only the
  selfbot couples `send_enabled` to `external_canary`.
- The `kernel-client` compatibility shim is dead outside its own test.
- Discord-officialbot and Telegram reject inbound with a bare boolean, so their
  logs carry no identifiers.
- Selfbot and Telegram lack a platform-level idempotency token, unlike
  discord-officialbot's nonce (`connector.js:10-15`, `:176-189`).
- `capabilities.json` flags become a readiness verdict without executable checks.

---

## 5. Cross-cutting

### Concurrency
One mechanism: optimistic state-version check inside `BEGIN IMMEDIATE`;
mismatch raises `ConcurrentStateError` and the cycle retries (ADR 0010). It is
**not** a general retry policy — an expected executor failure leaves the selected
action un-routed.

### Tracing and replay (`src/aelia/runtime/replay.py`, `observability.py`)
- Trace hash per cycle; `export_cycle` redacts by default.
- **Replay's determinism is weaker than its name.** A compatibility shim
  (`replay.py:237-263`) **copies expected values into the actual trace before
  hashing** when retries are non-empty, when schema or orchestrator versions
  differ, or on a legacy `2.1.0` action. Replay also re-attaches
  `RecordedLanguageGenerator(expected.language_generation)` and
  `RecordedExecutionPort(expected.execution_result)` (`:125`, `:130`, `:163`,
  `:168`, `:207`, `:212`). The guarantee is "deterministic given the recording",
  not "the generator is deterministic".
- **Redaction is 8 fixed key names plus `_id`/`_ids` suffixes**
  (`observability.py:11`). Any new sensitive field with an unlisted name leaks
  verbatim, and `constraints` (often rule-id lists) is unlisted.
- **`TraceExportPackage` hashes are computed over the unredacted payloads**
  (`observability.py:93-99`).

### Logging
The runtime package emits nothing. The CLI's structured-logging whitelist does
not match the keys the CLI actually emits — see §4.10.

---

## 6. Invariants the code enforces (not merely states)

1. Language generation cannot alter the decision — `contracts/traces.py:179-202`.
2. A proactive action can never be materialized — `models/autonomy.py:186` +
   DB `CHECK` at `migrations.py:373-374`.
3. No vector index is used — `models/memory.py:129`.
4. Kernel layers import no platform SDK — `test_dependency_direction.py:110-128`.
5. Layer import direction is one-way and acyclic — `:9-46`, `:130`.
6. The architecture gates cannot pass on an empty tree — `:58`, `:61-71`.
7. The only automatic kernel retry is the bounded state-conflict retry.

Everything else — the disclosure ceiling, the persona rule taxonomy, the
readiness verdict, the memory retrieval policy, the autonomy budget — is
**declared in types, docs, or manifests, and not enforced by a site in the
execution path**. That distinction is the subject of `ARCHITECTURE_GAP.md`.

---

## 7. Change log

| Date | Change |
|---|---|
| 2026-09-21 | Initial architecture record at `68a3359` (coordination bootstrap). |
| 2026-09-21 | §4.9 rewritten with the measured trace-duplication findings (G-37, G-39): the trace is written twice, owns 92.6% of the database, and only two tables have retention. |
| 2026-09-22 | Header cross-reference extended to `ARCHITECTURE_GAP.md` §A.1c. No architectural claim in this file changed. |
