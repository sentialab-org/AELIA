# ARCHITECTURE_GAP — current implementation vs. target AELIA

**updated_at:** 2026-09-22T00:00:00Z
**basis:** commit `68a3359`, read-only audit. Documentation cross-check and figure
re-measurement added 2026-09-22 (§A.1c).

Two sides. They are kept strictly apart, because the failure this file exists to
prevent is exactly the two being read as one.

| Side | Meaning | Evidence standard |
|---|---|---|
| **A. CURRENT IMPLEMENTATION** | What the code does today. | `file:line`, read from source. |
| **B. TARGET AELIA** | What AELIA is meant to become. | A `DECISIONS.md` entry. Nothing less. |

**Side B is empty, and that is a finding, not an omission.**
No document in this repository states a target AELIA architecture. The target
concept set is expected from ChatGPT. Until it arrives in writing and is
recorded as decisions, **every item on side B is `RESEARCH` and nothing on side A
may be refactored toward it.** That is the current instruction from the user, and
it is also the only correct default: refactoring toward an unwritten target is
how the described/built confusion starts.

---

# SIDE A — CURRENT IMPLEMENTATION

## A.1 The gap register

Each entry is a place where the code does not do what a reader would reasonably
conclude from the repository. Every entry is a **fact about `68a3359`**, not a
request to change it.

Severity is impact-on-a-reader-who-trusts-it, not effort to fix.

### Authority and identity

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-01** | high | **Two composition roots.** The CLI re-implements the wiring `bootstrap.py` claims to centralise, so "one root prevents drift" is a docstring, not a structure. | `src/aelia/cli.py:184-206` vs `src/aelia/app/bootstrap.py:31-32` |
| **G-02** | high | **Six of seven orchestrators are unreachable.** Only `AutonomyOrchestrator` is built on a production path; `v2-001`…`v2-006` exist only for tests and replay. `v2-007` has no constant, producer, or replay branch. | `src/aelia/app/bootstrap.py:105-111` |
| **G-14** | high | **The ADR set has rotted with no supersession mechanism.** ADRs 0008 and 0012 are de-facto superseded by 0015/0016 and still read Accepted, with no `Superseded` line. Nothing in the repo makes rot detectable. | `docs/adr/0008-…md:26-31`, `docs/adr/0012-…md`; `grep -rl 'Superseded' docs/adr/` → empty |
| **G-32** | low | **Two versioning idioms coexist** — `Literal[...]` `schema_version` on envelopes, free-form `str` `policy_version` elsewhere — unreconciled. | `src/aelia/contracts/traces.py:42` vs `src/aelia/autonomy/initiative.py:20` |
| **G-16** | medium | **A schema-version comparison is a hardcoded literal.** | `src/aelia/adapters/repository.py:451` — `== "2.0.0"` |
| **G-31** | medium | **A declared self-capability is factually false.** The self-model asserts `limitation.no_live_language_model` while the LLM wiring is live. | `src/aelia/models/self_model.py:95-122` |
| **G-33** | medium | **Prompts are composed and hashed on paths that never send them.** Provenance is recorded for a prompt the model never saw. | `src/aelia/runtime/orchestrator.py:421-442`, `:622-642` |

### Autonomy

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-03** | high | **There is no guardrail outcome that authorises an action.** The set is `{BLOCKED, REQUIRE_CONFIRMATION, SHADOW_APPROVED}`, and the mode check passes only for SHADOW — so shadow-only is not a policy setting, it is a closed door. | `src/aelia/autonomy/guardrails.py:52` |
| **G-04** | high | **Nothing in `src/` constructs a `PermissionContext`,** so the scopes the guardrails depend on are always empty. No code mints `proactive_message`, `confirm:<proposal_id>`, or `proactive_private`. | `src/aelia/contracts/events.py:71` (default `()`) |
| **G-30** | low | **`evidence_audit_ids` is write-only** — the audit trail behind the rate/cost counters is recorded and never read. | `src/aelia/storage/repositories.py:546` (write), `src/aelia/models/autonomy.py:82` (declaration) |
| **G-34** | medium | **Initiative scoring is fully hardcoded.** `estimated_cost` constant `0.5`; `expected_value` a per-type table. The budget and value gates therefore gate on constants. | `src/aelia/autonomy/initiative.py:175-180`, `:199` |
| **G-25a** | medium | **The opt-out guardrails are unreachable in production** — `set_autonomy_opt_out` has no production caller. | `src/aelia/storage/repositories.py:549-588` |
| — | low | `REQUIRE_CONFIRMATION` is unreachable on the live path by construction; budget counts only SHADOW_APPROVED, so a blocked decision consumes no budget despite incurring cost. | `src/aelia/autonomy/initiative.py:201`, `:181-185`; `src/aelia/storage/repositories.py:512` |

### Runtime and ports

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-05** | high | **The live cycle runs mock ports.** No production orchestrator injects a `LanguagePort`, so `ContentPlan` always comes from `MockLanguagePort`; the default `ExecutionPort` is the mock, so `execution_result` is always `SIMULATED`. The real OpenAI-compatible provider exists but is not on this path. | `src/aelia/runtime/orchestrator.py:1149` |
| **G-21** | medium | **The retry loop is copy-pasted verbatim six times.** A fix applied to five of six looks applied. | `orchestrator.py:217-248`, `:339-377`, `:497-542`, `:705-755`, `:972-1042`, `:1158-1243` |
| — | medium | With mock wiring a SKIPPED language generation still proceeds to execution; only FAILED blocks. | `orchestrator.py` ActionOrchestrator path |

### Memory and learning

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-07** | high | **The learning loop terminates at INSERT.** `cycle_outcomes`, `learning_proposals`, `reflection_triggers` have no read path in `src/`. ADR 0006's validation gate has nothing behind it. | no reader found; writes only |
| **G-10** | high | **Retrieved memory never reaches the prompt path.** Retrieval runs and its result is discarded before generation. | retrieval result consumed nowhere downstream |
| **G-23** | medium | **Embedding/vector retrieval is ABSENT** — and structurally locked off. | `src/aelia/models/memory.py:129` `vector_index_used: Literal[False]` |
| **G-24** | medium | **Consolidation, decay and forgetting are ABSENT.** `decay_policy` is decorative. | `src/aelia/cognition/memory/` |
| — | medium | `load_memory_candidates` over-fetches `query.limit * 10` and returns the over-fetched set untruncated. | `src/aelia/storage/repositories.py:439`, `:454` |
| — | low | Memory summaries are fixed template strings, not generated; canonical refs are never resolved. | `src/aelia/cognition/memory/` |

### Cognition

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-08** | high | **The world model is rebuilt and discarded every cycle.** No table, no loader; only a `cycle_artifacts` row survives. 3 of 5 `WorldStatementKind`s are write-only. | `src/aelia/storage/repositories.py:656-657` |
| **G-09** | high | **Appraisal has no goal linkage.** It emits a placeholder reason code and a zero relevance. | `src/aelia/cognition/appraisal.py:54` (`'goal_relevance_placeholder'`), `:66` (`goal_relevance=0.0`) |
| — | medium | Perception is two regex patterns — age and description. | `src/aelia/cognition/perception.py:83-96`, `:98-112` |
| — | medium | MEDIUM attention is indistinguishable from LOW; `goal_domain_relevance` is a flat `0.70`. | `src/aelia/cognition/attention.py:138-146`, `:91-97` |
| — | medium | Belief confidence moves a flat `+0.05` per observation; `BeliefStatus.REJECTED` is unreachable; a CONTESTED belief can never return to PROVISIONAL/ACCEPTED. | `src/aelia/cognition/beliefs.py:82` |
| — | medium | `GoalManager.merge` has zero call sites in `src/`; `Goal.allowed_actions` and `conflict_set` are written, never read; three `InternalTriggerType` branches are unreachable. | `src/aelia/cognition/goals.py:228-303`; `:98` |
| **G-35** | low | `DeliberationPort` is a STUB with no implementer. | `src/aelia/cognition/deliberation.py:20-30` |
| — | low | `ObservedSignals` are produced every cycle and never consumed. | `src/aelia/cognition/perception.py` |
| — | medium | Social state is updated by **naive substring matching on user content**; the privacy phrase list exists in two independent copies; `SocialState.attachment` is structurally dead; familiarity/uncertainty drift unbounded. | `src/aelia/cognition/social.py:18-29`, `:49-54`; `src/aelia/persona/disclosure.py` |

### Persona

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-19** | high | **The persona's guarantees are text, not code.** The disclosure ceiling is advisory prompt text; `verify_sources()` runs only in the CLI doctor and tests; raw active source text is never used at runtime (`load_active_source`'s sole caller is a test). | `src/aelia/persona/ports.py:70-80`; `verify_sources` call sites |
| — | medium | **Unanchored substring matching** — `'age'` matches `message`, `language`, `page`, `manage`. | `src/aelia/persona/selector.py:32`, `:36-38`, `:61-64` |
| — | medium | 8 of 43 spec rules are unreachable; the typed rule taxonomy is decorative; rules couple to spec rule ids by bare string literals and raise `ValueError`, aborting the cycle. | `src/aelia/persona/selector.py` |
| — | medium | `ConversationLanguage.MIXED`/`.ANY` are never produced — a hard binary VI/EN switch. | `src/aelia/persona/selector.py:112-133` |
| — | medium | The identical persona block is **triplicated** across orchestrators. | `orchestrator.py:395-405`, `:577-603`, `:798-831` |
| — | low | `loader.py` still carries a V1-Rust branch. | `src/aelia/persona/loader.py:155-161` |

### Adapter and connectors

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-11** | high | **`ConnectorReadinessPolicy` performs no probing.** It copies manifest booleans into evidence strings and sets the verdict to `all(declared flags)`, so a hand-asserted `capabilities.json` becomes `ready_for_authorized_canary`. Its own docstring concedes it is a static gate. | `src/aelia/adapters/conformance.py:56-70`, `:71` |
| **G-12** | high | **Outbox recovery cannot drain external-canary rows.** `_complete_reservation` returns them unchanged, so they stay `RESERVED` forever. | `src/aelia/adapters/runtime.py:189-198`, `:259-262` |
| **G-13** | high | **A connector-side validation failure strands the backend reservation.** The connector throws before writing any receipt, so the reserved dispatch is never finalized by either side. | `platforms/discord-selfbot/src/connector.js:60` |
| **G-26** | medium | **`max_sends_per_hour` is parsed, validated, printed — and enforced nowhere.** The `.env` comment claiming "the Python external-canary outbox enforces the same cap" describes a control that exists on neither side. | `platforms/discord-selfbot/src/config.js:101-107`, `:122` |
| **G-25b** | medium | **`recover_pending()` is not wired into the service**; conformance is never enforced by the runtime; `finalize` does not verify its optimistic `UPDATE` matched a row; a fresh adapter and mock transport are built per ingress request. | `cli.py:486`; `cli.py:308`; `src/aelia/adapters/runtime.py` |
| — | medium | Telegram captures `retry_after` and never consumes it; the poll loop sleeps a fixed 1 s for every error class. | `platforms/telegram-officialbot/src/api-client.js:6`, `:11`, `:100` |
| — | low | `adapterMode` is parsed by officialbot/Telegram and never enforced. | `platforms/discord-officialbot/src/config.js:69-74` |
| — | low | The `kernel-client` compatibility shim is dead outside its own test. | `platforms/node-common/kernel-client.js:5-7` |

### Storage, backend and process

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-06** | high | **Gate-token auth fails open.** With `AELIA_RUNTIME_GATE_TOKEN` unset, ingress, receipts and `/runtime/status` are fully unauthenticated. | `src/aelia/backend/api.py:133-138` |
| **G-15** | medium | **Ten of 24 tables have no read path in `src/`.** 17 `*_sha256` columns are written; exactly one is ever compared. | `src/aelia/storage/repositories.py:169`, `:752` |
| **G-22** | medium | **Migration application is not concurrency-safe** — applied versions are read outside any lock and the DDL lacks `IF NOT EXISTS`. | `src/aelia/storage/migrations.py:463-464`, `:469` |
| **G-20** | medium | **The runtime emits no logs at all**, and the CLI's structured-field whitelist does not match the keys the CLI emits — actual emits are silently dropped. | `src/aelia/app/logging.py:9-20` vs `src/aelia/cli.py:322-327` |
| — | medium | `/health` is a constant stub ignoring `application`; `/ready` never returns non-200; `shutdown()` is a flag flip. | `src/aelia/backend/api.py:177-179`, `:181-189`; `application.py:69-72` |
| — | medium | The gate allowlist trap: an empty `allowed_conversation_ids` rejects every envelope with 403. | `src/aelia/backend/application.py:94-96` |
| **G-25c** | low | Dead on the production path: `resolve_path`, `runtime_public_url` (validated and TOML-mapped, never read by Python), `store_foundation_cycle` (tests only), `AdapterPolicyConfig.policy_version`. | `app/bootstrap.py:127-129`; `app/config.py:110` |
| — | low | `db init` prints without migrating; docs/openapi URLs all `None`; no connection pooling. | `src/aelia/cli.py:332-341`; `backend/api.py:81-83` |

### Replay, observability and tests

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-18** | high | **Replay copies expected values into the actual trace before hashing** — on non-empty retries, on version mismatch, and on a legacy `2.1.0` action. Replay also re-attaches the recorded language generation and execution result, so the gate verifies wiring, not determinism. | `src/aelia/runtime/replay.py:237-263`; `:125`, `:130`, `:163`, `:168`, `:207`, `:212` |
| **G-17** | medium | **Redaction is 8 fixed key names** plus `_id`/`_ids`; any new sensitive field with an unlisted name leaks verbatim, and `constraints` is unlisted. **`TraceExportPackage` hashes are computed over the unredacted payloads.** | `src/aelia/runtime/observability.py:11`, `:93-99` |
| **G-27** | high | **CI has drifted from the Makefile**: `runtime-client.js` is `node --check`ed locally but omitted from CI, so a syntax error in it passes CI. | `Makefile:59-63` vs `.github/workflows/quality.yml:77-80` |
| **G-28** | low | **The non-vacuity floor is thin.** `MINIMUM_PACKAGE_SOURCES = 70` against an actual 73 — one small refactor from being a tripwire rather than a guard. | `tests/architecture/test_dependency_direction.py:58` |
| **G-29** | medium | **The rename-identity gate does not scan repo-root config or docs**, so the pre-rename marker is unenforced outside `src`/`tests`/`platforms`. | `tests/architecture/test_package_identity.py:16` |
| — | medium | `test_core_kernel_does_not_import_adapter_implementation` uses a substring scan and ends on an unrelated enum check — it does not test what its name claims. | `tests/contract/test_adapter_contract.py:75-97` |
| — | medium | `contracts/traces.py` imports `aelia.models.*` and `aelia.persona.models`, contradicting `FORBIDDEN_PREFIXES['contracts']`. The gate's table and the code disagree. | `test_dependency_direction.py:9` vs `src/aelia/contracts/traces.py:22-39` |
| — | medium | The "behavioral" persona suite is 9/10 catalog data-integrity assertions; the one executing test hand-wires a simplified pipeline. | `tests/behavioral/persona/test_behavior_scenarios.py` |
| — | low | Two committed event fixtures are dead; there is no `conftest.py` anywhere. | `tests/fixtures/events/` |

## A.1b Empirical findings — measured against the production database

**Evidence class: measured, not read.** The register above was built by reading
source. This section was built by querying `data/aelia.db` — **read-only**
(`file:…?mode=ro`, `PRAGMA query_only=ON`) — and it exists because the first pass
of this audit did not do that. Every number below carries its query.

Corpus: **4,085 cycles**, 748,343,296 bytes on disk (713.68 MB of live pages),
WAL mode. This is one user's real traffic over roughly 2.7 days.

| ID | Severity | Gap | Evidence |
|---|---|---|---|
| **G-37** | **high** | **The trace is written twice and owns the database.** `store_observation_cycle` writes one `trace_json` blob per cycle into `cycles` *and* explodes the same trace into ~21 `cycle_artifacts` rows. Measured: `cycles` 311.27 MB + `cycle_artifacts` 349.58 MB = **660.85 MB of 713.68 MB (92.6%)**. `cycle_artifacts` = 85,832 rows ÷ 4,085 cycles = 21.0 per cycle. **Retention exists for exactly two tables** — `conversation_buffer` (`repositories.py:1530`) and `conversation_participation` (`:1541`) — and nothing prunes the trace. At ~264 MB/day the substrate grows ~96 GB/year with no reaper. | `sqlite3`: `SELECT name, SUM(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC` |
| **G-36** | **high** | **The permission-scope vocabularies on the two sides of the boundary are disjoint, so the guardrails are structurally unpassable.** Producers emit only `explicit_mention` (`discord-selfbot/src/contracts.js:71`, `discord-officialbot/src/contracts.js:61`) and `message_thread` (`telegram-officialbot/src/contracts.js:111`). Consumers read only `send_message` (`orchestrator.py:284`, `:437`, `:638`, `:898`; `action_policy.py:146`), `proactive_message` (`initiative.py:202`), `confirm_high_risk` / `confirm:{proposal_id}` / `proactive_private` (`guardrails.py:32`, `:37`, `:107`, `:115`). **The intersection is empty.** This is stronger than G-04: even if something constructed a `PermissionContext`, no scope any consumer checks could ever be present. | `grep -rn 'scopes' platforms/*/src/contracts.js` against `grep -rn '"proactive_message"\|"confirm_high_risk"\|"proactive_private"\|"send_message"' src/aelia/` |
| **G-38** | **high** | **The belief layer is empirically inert while its machinery runs every cycle.** `beliefs` holds **0 rows** after 4,085 cycles. Confirms G-08 from the data side: the world model is rebuilt and discarded, and the belief policy's flat `+0.05` confidence update (`beliefs.py:82`) has never once been persisted. The only durable cognition is 6 commitment rows (from 6 goals) and 625 social rows. | `SELECT COUNT(*) FROM beliefs` → 0 |
| **G-39** | medium | **One inbound event's text is persisted at least four times**: `inbound_events.payload_json`; `conversation_buffer`; `memory_records` (**4,718** rows); and again inside `cycles.trace_json`, because `ObservationSnapshot` embeds `recent_messages` (`contracts/observation.py:38-43`). One of those four is itself duplicated by G-37. The redaction pass covers 8 fixed key names (G-17) and `constraints` is unlisted. _(Corrected 2026-09-22: this entry previously read 7,418. No table in the corpus holds 7,418 rows; the figure was a transcription error in the first measurement pass and did not reproduce. See `EVENTS.jsonl` `evt-2026-09-22-009`.)_ | `SELECT COUNT(*) FROM memory_records` → 4718 |
| **G-40** | medium | **`LanguageGenerationResult` is the one unversioned boundary contract — and it is the one the LLM crosses.** All three `schema_version` sites in `contracts/actions.py` (`:41`, `:61`, `:63`) are on the **request** side; the **response** type (`:221-234`) has no version field at all, while the prompt registry advertises `…@2.3.0` (`llm/prompts.py:25`). Every other boundary is versioned and drift-detected. | `grep -n 'schema_version' src/aelia/contracts/actions.py` |
| **G-41** | medium | **The attachment channel is populated end-to-end and read by nothing in Python.** `AttachmentKind`/`AttachmentReference` (`contracts/events.py:44`, `:52`), field at `:92`; all three connectors produce it (`discord-selfbot/src/contracts.js:65`, `discord-officialbot/src/contracts.js:46`, `telegram-officialbot/src/contracts.js:37-68`). Zero Python readers — the only hit outside the contract is a `.pyc`. It crosses the Node→HTTP boundary and dies. | `grep -rln 'AttachmentReference\|AttachmentKind' src/aelia/` → contract only |
| **G-42** | medium | **Conversation state is not platform-namespaced; social state is.** `conversation_state` is keyed `conversation_id TEXT PRIMARY KEY` with no platform column (`migrations.py:80-85`), and `conversation_buffer` / `conversation_participation` inherit that key (`:87-100`, `:121-132`). `social_relationships` is `UNIQUE(platform, actor_id)` (`:145-155`). Both Discord connectors derive `conversation_id` from the bare channel id (`discord-selfbot/src/contracts.js:50`, `discord-officialbot/src/contracts.js:31`), so the same channel seen through both connectors **collides in conversation state and does not collide in social state**. Latent today (25 conversation rows); becomes a data-migration question the moment both run. | `migrations.py:80-85` vs `:145-155` |
| **G-43** | medium | **Two ingress paths with unequal authorization.** HTTP enforces an actor allowlist (`backend/application.py:92`), but `AdapterPolicyConfig` carries only `policy_version, mode, canary_conversation_ids, conversation_limit_per_hour` — **no actor field** (`contracts/adapter.py:54-57`) — so the CLI `adapter ingest` path (`cli.py:434`) cannot perform the same check. | `contracts/adapter.py:54-57` |
| **G-44** | low | **Action generation is rare, and the two candidate outboxes agree by accident.** `selected_action`, `language_generation` and `execution_result` exist as **9** artifacts each against 4,085 cycles (0.22%). `outbound_actions` = 9 and `adapter_dispatches` = 9. The open question "which is authoritative?" is **answered by reading, not by deciding**: `recover_pending` drains `adapter_dispatches`, and `outbound_actions` is never `SELECT`ed. **The outbox is authoritative; `outbound_actions` is a coincidentally-equal write-only mirror** (G-15). | `SELECT COUNT(*) FROM outbound_actions` → 9; `adapter_dispatches` → 9 |
| **G-45** | low | **Unreferenced enum members confirmed at zero rows**, not merely unreferenced in code: `BeliefStatus.REJECTED` (beliefs = 0 rows), `MemoryValidationStatus.PROVISIONAL` and `MemoryCategory.SEMANTIC` (memory categories present are episodic/social/commitment/autobiographical/procedural only). `ProvenanceKind.PLATFORM`/`.TOOL` have no construction site in `src/` (`contracts/common.py:24-29`). | `SELECT DISTINCT` over `memory_records`; `contracts/common.py:24-29` |

**One correction to a document, found here.** The audit's docs layer reports
"182 Python tests" (`docs/IMPLEMENTATION_STATUS.md:47`). The verified figures are
**191 collected across 39 files** (`pytest --collect-only -q`; `find tests -name
'*.py'`). `HANDOFF.md` already states 191/39 correctly. Two numbers in the
repository disagree and nothing in the repo catches it — which is the same
class of defect as G-14.

## A.1c Documentation audit — every `docs/*.md` checked against this register

**Evidence class: read.** Method: each of the nine `docs/*.md` files was read in
full and every status-bearing claim was matched against a register entry or a
measured figure. This section exists because the register above says what the
*code* does, and said nothing about what the *documents* say it does — which is
the comparison a reader actually makes.

The documents are not wrong about the machinery. They are wrong about what the
machinery is worth. A phase described as `Complete` because its tests pass is
`Complete` in the sense that the code exists; it is not complete in the sense a
reader takes from the word. That gap is the whole finding.

### Mismatches found

| Doc | Claim | What the register shows | Class |
|---|---|---|---|
| `IMPLEMENTATION_STATUS.md` | `M6 memory and learning — Complete` | G-07: the loop terminates at `INSERT`; G-38: `beliefs` = **0 rows** after 4,085 cycles | Written, never read |
| `IMPLEMENTATION_STATUS.md` | `C4 cognition dynamics — Complete` | G-08: the world model is rebuilt and discarded every cycle; G-09: appraisal emits a placeholder reason code and `goal_relevance=0.0` | Written, never read |
| `IMPLEMENTATION_STATUS.md` | `X8 context causality — Complete` | G-08: `WorldStatementKind` 3 of 5 write-only; no table, no loader | Written, never read |
| `IMPLEMENTATION_STATUS.md` | `U7 initiative — Complete` | G-03/G-04/G-36: no guardrail outcome authorises an action, and the permission vocabularies either side of the boundary are disjoint — the path cannot execute | Declared, not enforced |
| `IMPLEMENTATION_STATUS.md` | `P8 adapter boundary — Complete` | G-12: external-canary reservations cannot be drained and stay `RESERVED`; G-06: gate auth fails open when the token is unset | Declared, not enforced |
| `IMPLEMENTATION_STATUS.md` | `Runtime backend + platform gates — Complete locally` | G-06, G-20 (the runtime emits no logs at all), `/health` is a constant stub, G-27 (CI omits a file the Makefile checks) | Partial |
| `FINAL_AUDIT.md` | `Recovery — no unexplained reserved adapter dispatch remains` | G-12: `_complete_reservation` returns external-canary rows unchanged, so they remain `RESERVED` **by construction**. The audit row is true only because no external canary has run | Direct contradiction |
| `FINAL_AUDIT.md` | `Architecture boundary — kernel modules do not import adapter implementations or platform SDKs` | True in fact, but `contracts/traces.py:22-39` imports `aelia.models.*` and `aelia.persona.models`, contradicting the gate's own `FORBIDDEN_PREFIXES['contracts']` table | Gate/code disagreement |
| `FINAL_AUDIT.md` | `Dependency direction — AST conformance and import-cycle tests pass` | G-28: the non-vacuity floor is 70 against an actual 73; G-29: the identity gate does not scan repo-root config or docs | Thin guard |
| `FINAL_AUDIT.md` | `Initiative is shadow-only and cannot materialize an outbound action` | True, but stated as a safety posture. G-03: it is a closed door — `SHADOW_APPROVED` is the only passing outcome, enforced by `Literal[False]` and a DB `CHECK` | Framing |
| `FINAL_AUDIT.md` | `Automated tests — 182 Python, 34 Node` | Measured 191 and 40. **Corrected in place.** | Stale figure |
| `REQUIREMENT_EVIDENCE.md` | `Model-derived memory requires validation — Pass` | G-07/G-38: the validation gate has nothing behind it and the belief table is empty | Written, never read |
| `REQUIREMENT_EVIDENCE.md` | `Memory has one canonical source per concept — Pass` | G-15: ten of 24 tables have no read path in `src/` | Written, never read |
| `REQUIREMENT_EVIDENCE.md` | `Deterministic replay — Pass` | G-18: replay copies expected values into the actual trace before hashing | Declared, not enforced |
| `REQUIREMENT_EVIDENCE.md` | `Trace inspect/compare/export/redact — Pass` | G-17: redaction is 8 fixed key names, and `TraceExportPackage` hashes are computed over the **unredacted** payloads | Partial |
| `REQUIREMENT_EVIDENCE.md` | `Resolved config and privacy-bounded structured logging — Pass` | G-20: the runtime emits no logs; the CLI's whitelist does not match the keys it emits, so its fields are silently dropped | Declared, not enforced |
| `REQUIREMENT_EVIDENCE.md` | `Adapter reconnect/crash/outbox recovery — Pass` | G-12, G-13: an external-canary row cannot be drained, and a connector-side validation failure strands the reservation | Partial |
| `REQUIREMENT_EVIDENCE.md` | `Initiative cannot bypass guardrails — Pass` | Vacuously true: G-36 makes the check unpassable, so nothing can bypass it because nothing can reach it | Fail-open by emptiness |
| `REQUIREMENT_EVIDENCE.md` | `World and Conversation Models are explicit — Pass` | G-08: the world model has no table and no loader | Written, never read |
| `REQUIREMENT_EVIDENCE.md` | `Observations do not automatically become facts — Pass` | G-38: no belief has ever been persisted, so the invariant is untested by reality rather than satisfied | Vacuous |
| `REQUIREMENT_EVIDENCE.md` | `Architecture governance and Definition of Done — Pass` | G-14: two ADRs are de-facto superseded and still read Accepted, with no supersession mechanism anywhere in the repo | Declared, not enforced |
| `DEFINITION_OF_DONE.md` | `Documentation, requirement evidence, test count, and runbook are current` | Self-violated at the audit commit: the test count was 182 against a measured 191. The checklist item that would have caught every other row in this table was itself unmet | Self-referential |
| `P8_CUTOVER_RUNBOOK.md` | required result: `no adapter dispatch is left in reserved state` | G-12 makes this unachievable for any external-canary row, independent of operator action | Direct contradiction |
| `P8_CUTOVER_RUNBOOK.md` | `external_canary … require an external receipt` | G-11: `ConnectorReadinessPolicy` declares readiness without probing; `ExternalReceiptStatus` has no producer in `src/` | Declared, not enforced |
| `IMPLEMENTATION_PLAN.md` | §14 criterion: `persona behavioral suite passes` | The behavioral suite is 9/10 catalog data-integrity assertions; the one executing test hand-wires a simplified pipeline | Thin evidence |

### Verified accurate

Stated so the table above is not read as "the documents are unreliable":

- **`CONNECTOR_ACCEPTANCE.md` — no mismatches.** It is the one document that
  already draws the line this section is about: *"A passing report means only
  that required mechanisms are declared. It is not evidence that they work."*
  Every claim in it is either an input request or a description of evidence that
  does not yet exist.
- **`P8_CUTOVER_RUNBOOK.md` §Contracts** — all eight version values re-verified
  against `src/aelia/contracts/` and correct.
- **`RUNTIME_BACKEND_PLATFORM_GATES_REFACTOR_PLAN.md` §7** — verified, not
  assumed: no Node production file imports `child_process` or invokes `uv`/`aelia`
  (`grep -rn 'child_process\|spawn(' platforms/*/src/ platforms/node-common/` →
  empty), so its stated completion criterion — *"the old per-message Python spawn
  path is removed, not merely bypassed"* — is genuinely met.
- **`ARCHITECTURE_STATUS_REPORT.md`** — the translated report. Its figures were
  re-measured rather than carried over, and the three claims that had become
  factually false (source-control status, ADR count, test counts) are marked
  `[SUPERSEDED]` in place rather than silently rewritten.

### What was changed, and what was deliberately not

Changed: every stale figure (test counts, source/ADR/mypy counts) refreshed to a
measured value with the original shown alongside; the `V2` product-name residue
replaced with `AELIA` at 14 sites, keeping the three `V2-00x` milestone
identifiers and two old-filename citations; three broken `../../` relative links
repaired to `../`; `README.md` reduced to a work-in-progress stub; the Vietnamese
report translated to `ARCHITECTURE_STATUS_REPORT.md` and the original deleted.

Not changed: **no status word was rewritten.** Where a document says `Complete`
and the register disagrees, the document now carries a banner pointing here
instead of a corrected verdict. Editing a status in place would destroy the
evidence that the status was ever claimed — and the divergence between claim and
measurement is itself the finding. Only claims that had become *factually* false
(a number, a name, a path) were corrected outright.

---

## A.2 The pattern worth naming

The register is not a list of unrelated bugs. Three shapes recur, and they are
the reason this coordination layer exists:

1. **Declared, not enforced.** A capability exists as a type annotation, a
   prompt paragraph, a manifest flag, a docstring, or a test name, with no site
   in the execution path that makes it true. G-11, G-19, G-31, G-29, G-03.
2. **Written, never read.** A value is computed and persisted with no consumer —
   so the system pays its cost and gets none of its benefit, while the schema
   implies the feature ships. G-07, G-08, G-15, G-30, G-10, G-41.
3. **Fail-open by emptiness.** A check passes because its input set is empty — a
   vacuous architecture gate, unauthenticated endpoints when a token is unset, a
   readiness verdict over declared booleans, empty permission scopes. G-06, G-04,
   G-11, G-28, and the four gates repaired in `68a3359`.

Shapes 1 and 3 are the same failure at different layers: **a check that cannot
fail is not a check.** Any target architecture that does not explicitly address
this will reproduce it.

**The production data turns shape 3 from a code-reading into a measurement.**
G-36 is the extreme case: the two sides of the permission boundary share *no
vocabulary at all*, so the scope check cannot pass for any input — it is not
misconfigured, it is structurally incapable of succeeding. And G-38 shows shape 2
at full scale: a belief policy that has run 4,085 times and persisted nothing.
Neither was visible from the source alone. **The coverage lesson is part of the
finding: an audit that reads code and never queries the database will miss the
class of defect where the machinery runs and the state never accrues.**

## A.3 What is genuinely solid

Stated so the register is not read as a verdict on the whole system:

- The layer rules are real and machine-enforced (`test_dependency_direction.py`).
- Optimistic concurrency under `BEGIN IMMEDIATE` is correctly implemented and is
  the only automatic retry (D-003).
- The language-cannot-change-the-decision invariant is enforced by a raise, not a
  convention (`contracts/traces.py:179-202`).
- The connector journal is fsynced before the side effect, and an interrupted
  attempt is never blind-retried (`journal.js`, `receipts.js:34`).
- The persona archives are byte-pinned and genuinely verified in the suites that
  run `verify_sources()`.
- The rename landed as a true rename, and the four gates it emptied were repaired
  rather than left vacuously green.

---

# SIDE B — TARGET AELIA

## B.1 Status: **AWAITING INPUT**

No target architecture for AELIA exists in this repository. Not in `docs/`, not
in `docs/adr/`, not in `README.md`, not in `legacy/`. This was verified, not
assumed: the audit read all 9 `docs/*.md`, all 17 ADRs and the `legacy/v1-rust`
dev-notes, and every statement about future capability found there is either
(a) a V1-Rust aspiration frozen inside the archive, or (b) an ADR
`Consequences` paragraph about a path since built differently.

**Therefore side B currently contains no `DECIDED` item, and every bullet below
is `RESEARCH`.** Nothing in side A may be refactored toward any of them until
the user or ChatGPT converts them into `DECISIONS.md` entries.

## B.2 Candidate inputs — `RESEARCH`, from inside this repository

Listed so the target discussion starts from what the repo already says rather
than from a blank page. Each is labelled with what it actually is.

| # | Candidate | Origin | What it is |
|---|---|---|---|
| B-1 | A promotion path from `SHADOW_APPROVED` to a real action, with canary controls and recovery tests | ADR 0007 `Consequences` | A stated future, never built. The door is currently closed by type and by DB constraint (G-03). |
| B-2 | Authorising guardrail outcomes beyond the current three | Implied by B-1 | Would require adding a `GuardrailOutcome` member and reopening `guardrails.py:52`. Unspecified. |
| B-3 | A channel for answering `REQUIRE_CONFIRMATION` | ADR 0007 bullet list | No endpoint, no CLI, no code. |
| B-4 | Live language and live execution on the real cycle path | Implied by G-05 | The providers exist; the wiring does not. |
| B-5 | A validated-learning loop end to end | ADR 0006 | The ADR is Accepted; the read path is missing (G-07). |
| B-6 | Semantic memory retrieval | Absent | No embedding dependency exists; `vector_index_used` is locked `False` (G-23). |
| B-7 | Memory consolidation, decay and forgetting | Absent | `decay_policy` is decorative (G-24). |
| B-8 | Durable world / self / social models | Implied by G-08 | The world model is discarded each cycle. |
| B-9 | Streaming responses | `README.md` reserves WebSocket | Reserved, not built. `"stream": False` is the only occurrence in `llm/`. |
| B-10 | Executable connector conformance instead of declared manifests | ADR 0012 vs G-11 | The ADR's intent; the implementation is a copy of booleans. |
| B-11 | Supersession discipline for the ADR set | G-14 | A process decision, not an architecture one. |
| B-12 | Graph memory / social tree / truth knowledge graph | `legacy/v1-rust/docs/dev-notes/` | **V1 Rust design documents inside a frozen archive.** They describe designs around V1, not AELIA. Treat as historical input only. |

## B.3 What ChatGPT is being asked for

See `HANDOFF.md`. In short: a written target architecture for AELIA, and — for
each element of it — an explicit statement of which side-A component it replaces,
extends, or leaves alone. Until that arrives, side A is frozen as-is.
