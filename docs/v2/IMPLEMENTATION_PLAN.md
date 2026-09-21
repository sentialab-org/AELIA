# Polyverse Agent V2 — Implementation Plan

**Status:** P8 boundary and three offline connectors implemented; live canary pending  
**Date:** 2026-07-30  
**Execution model:** Controlled rewrite, Python modular monolith  
**V1 role:** Experimental draft and architecture reference, not a behavioral baseline  
**Preserved product asset:** The Ryuuko persona source and its intended behavioral invariants

## 1. Objective

Build a new Python kernel in which persona, relationship state, internal dynamics,
participation, and action selection have explicit causal roles. V2 must not be a
line-by-line Rust port and must not reproduce V1's worker topology, state schema,
storage topology, prompt composition, or event ordering.

The first useful milestone is not a complete autonomous agent. It is a small,
deterministic vertical slice that can:

1. accept and validate a versioned event;
2. persist it idempotently;
3. update conversation context;
4. decide whether to observe, remain silent, wait, or reply;
5. produce a persona-constrained content plan or mock reply;
6. persist a complete cycle trace;
7. replay the cycle without relying on live external services.

## 2. Decisions Already Made

### 2.1 V1 disposition

- V1 is an experimental draft, not the reference behavior V2 must match.
- Existing Rust tests do not block V2 and will not be repaired as part of the rewrite.
- V1 message history, graph state, LanceDB data, and numeric state are not migrated.
- Rust remains readable for code archaeology until V2 has replaced the useful platform paths.
- No Rust module is ported line by line.

### 2.2 Persona disposition

- `legacy/v1-rust/prompts/persona/base.v3.txt` is the archived active V1 persona
  source; V2 consumes its byte-preserved, hash-bound copy.
- All existing persona source versions are preserved verbatim and treated as immutable evidence.
- The source prompt is not copied into V2 as the sole system prompt.
- Persona is decomposed into structured identity, values, boundaries, disclosure policy,
  relationship dynamics, participation preferences, communication style, and presentation policy.
- Every structured persona rule must reference the source passage from which it was derived.
- Behavioral tests, rather than exact generated text, protect persona continuity.

### 2.3 Architecture

- Python 3.12 or later.
- One process and one local SQLite database initially.
- Modular monolith; no microservices in the kernel.
- Deterministic, sequential cognitive core with asynchronous I/O at the edges.
- Direct function calls for the main cognitive cycle.
- Event/background queues only for ingress, scheduled work, analytics, and non-blocking side effects.
- Pydantic models at public boundaries; raw dictionaries stop at parsing/serialization edges.
- Repository protocols isolate cognition from storage implementation.
- LLM calls generate structured observations, candidates, reflection proposals, or language;
  they do not directly mutate canonical state or execute actions.
- Silence is an explicit participation result.
- Every durable update has provenance.
- Every cycle is traceable and replayable.
- Initiative remains disabled until participation, rate limits, permissions, and guardrails are tested.

## 3. What Is Reused From V1

| V1 component | V2 treatment | Reason |
|---|---|---|
| Persona prompt versions | Preserve as source artifacts | Primary product asset |
| Platform processes separated from core | Keep concept | Correct operational boundary |
| UDS/JSON relay | Temporary reference or compatibility shim | Allows kernel work before adapter rewrite |
| Raw event normalization | Keep concept, redesign schema | Useful boundary, existing type is unversioned |
| Prompt registry | Keep concept, redesign | Needs versions, schemas, ownership, and tests |
| Short-term memory | Reinterpret as conversation buffer | Useful behavior without V1 synchronization complexity |
| SQLite message persistence | Keep SQLite-first principle | Simple canonical store and replay foundation |
| Episodic/semantic/social distinctions | Keep semantic distinctions | Do not allocate one database per memory type |
| Social graph/tree | Defer | Relationship model starts in SQLite; graph is optional later |
| Dialogue engine | Mine context and tool lessons | Do not port prompt assembly or response authority |
| Affect evaluator | Keep separation lesson | Appraisal must move before action selection |
| Numeric state dimensions | Use only as research vocabulary | Do not migrate 54-dimension schema |
| MCP validation/tool registry | Reuse validation and namespace lessons | Tool execution still needs typed contracts and permissions |
| Worker/Supervisor/Coordinator | Discard | Replaced by explicit orchestrator and bounded background jobs |

## 4. Target Dependency Direction

```text
contracts
  ↓
domain models + persona
  ↓
cognition
  ↓
runtime orchestration
  ↓
execution/storage/LLM ports
  ↓
platform adapters
```

Rules:

- Domain models must not import runtime, storage implementations, LLM clients, or adapters.
- Cognition may depend on contracts, domain models, persona views, and repository protocols.
- Runtime coordinates modules but does not contain domain policy.
- Adapters translate platform-specific payloads into versioned contracts.
- Storage projections and caches are derived and rebuildable.

## 5. Planned Repository Shape

Only files required by a running slice are created. The eventual shape is:

```text
pyproject.toml
src/polyverse/
├── app/
│   ├── bootstrap.py
│   └── config.py
├── contracts/
│   ├── common.py
│   ├── events.py
│   ├── actions.py
│   └── traces.py
├── persona/
│   ├── loader.py
│   ├── models.py
│   ├── selector.py
│   └── source/
├── models/
│   ├── conversation.py
│   ├── social.py
│   ├── self_model.py
│   ├── belief.py
│   ├── affect.py
│   └── goals.py
├── cognition/
│   ├── attention.py
│   ├── perception.py
│   ├── appraisal.py
│   ├── dynamics.py
│   ├── participation.py
│   ├── deliberation.py
│   └── action_policy.py
├── runtime/
│   ├── orchestrator.py
│   ├── unit_of_work.py
│   └── replay.py
├── storage/
│   ├── database.py
│   ├── migrations.py
│   └── repositories.py
├── llm/
│   ├── port.py
│   ├── structured_output.py
│   └── prompts.py
├── execution/
│   ├── executor.py
│   ├── language.py
│   ├── platform_port.py
│   └── tools.py
├── autonomy/
│   ├── initiative.py
│   ├── guardrails.py
│   └── budgets.py
└── cli.py
tests/
├── unit/
├── contract/
├── behavioral/
│   └── persona/
├── replay/
└── integration/
```

## 6. Tooling Baseline

Initial dependencies are intentionally small:

- `pydantic` and `pydantic-settings`: contracts and strict configuration;
- `aiosqlite`: asynchronous SQLite boundary;
- `pytest` and `pytest-asyncio`: tests;
- `mypy`: strict type checking;
- `ruff`: linting and formatting.

Use `uv` for environment and lockfile management. Do not add an ORM, graph database,
vector database, workflow engine, dependency injection framework, or observability
platform until a measured requirement appears.

Quality gate for every implementation batch:

```text
ruff format --check .
ruff check .
mypy src
pytest
```

## 7. Versioned Core Contracts

### 7.1 Inbound event

Minimum fields:

- `schema_version`;
- `event_id`;
- `platform`;
- `conversation_id`;
- `channel_type`;
- `actor_id`;
- `occurred_at`;
- `event_type`;
- `content`;
- `reply_to`;
- `mentions`;
- `attachments`;
- `permissions`;
- `source_reference`.

### 7.2 Participation decision

Outcomes:

- `observe`;
- `silent`;
- `wait`;
- `react`;
- `reply`;
- `join`;
- `initiate`;
- `internal_action`.

Every decision includes:

- `cycle_id`;
- `outcome`;
- `reason_codes`;
- `score_breakdown`;
- `confidence`;
- `policy_version`.

Only the outcomes needed by the current phase are enabled.

### 7.3 Outbound action

Minimum fields:

- `schema_version`;
- `action_id`;
- `cycle_id`;
- `action_type`;
- `target`;
- `content_plan`;
- `permission_scope`;
- `idempotency_key`;
- `risk_class`;
- `created_at`.

### 7.4 Cycle trace

Every cycle stores:

- input event and state versions;
- attention result;
- structured observation;
- model deltas;
- appraisal and internal-state deltas;
- retrieved memory references;
- goal changes;
- action candidates;
- participation decision;
- selected action;
- prompt/model metadata;
- execution result;
- outcome and learning proposal;
- errors and retry history.

Early phases may leave later artifacts empty, but the trace schema remains versioned.

## 8. Implementation Phases

### Phase P0 — Persona preservation and specification

**Estimate:** 0.5–1 engineering day  
**Purpose:** Preserve the only V1 asset that must not be lost.

Tasks:

1. Copy all persona source versions into an immutable V2 source directory.
2. Record SHA-256 hashes and identify `base.v3.txt` as the active source.
3. Create structured persona schemas:
   - identity anchors;
   - time-varying biographical facts;
   - values;
   - boundaries;
   - disclosure rules;
   - relationship dynamics;
   - participation preferences;
   - communication style;
   - presentation policy.
4. Attach a source reference to every structured rule.
5. Write an initial set of at least 15 persona behavioral scenarios.

Acceptance:

- source files are byte-for-byte preserved;
- every persona rule is traceable to source;
- sensitive disclosure, trust inertia, language choice, nickname boundaries,
  silence, and non-assistant-like behavior each have tests;
- exact generated wording is not used as the oracle.

### Phase F1 — Python foundation, contracts, event log, and replay

**Estimate:** 3–5 engineering days  
**Purpose:** Establish a deterministic platform-independent kernel with no LLM.

Tasks:

1. Create `pyproject.toml`, `uv.lock`, package layout, and quality commands.
2. Add strict configuration with unknown-key rejection and redacted resolved output.
3. Implement versioned inbound event, outbound action, participation, and trace contracts.
4. Implement SQLite migrations for:
   - inbound event log;
   - processed-event/idempotency records;
   - cycles;
   - cycle artifacts.
5. Implement repository protocols and SQLite implementations.
6. Implement a minimal explicit orchestrator.
7. Add CLI commands:
   - `config doctor`;
   - `event ingest`;
   - `cycle inspect`;
   - `cycle replay`.

Acceptance:

- valid JSON event is accepted and persisted;
- invalid/unknown fields fail deterministically;
- duplicate `event_id` causes no duplicate side effect;
- replay performs the same non-LLM transitions;
- no live model, platform, graph, or vector dependency exists.

### Phase O2 — Observation loop and participation vertical slice

**Estimate:** 4–6 engineering days  
**Purpose:** Make observation and silence first-class behavior.

Tasks:

1. Implement per-conversation buffer and reply graph.
2. Implement rule-based attention with reason codes:
   - direct mention;
   - DM;
   - reply to agent;
   - goal/domain relevance placeholder;
   - low-value chatter;
   - recent participation penalty;
   - conversation owned by others.
3. Implement lightweight update for low-salience events.
4. Implement initial participation outcomes:
   - `observe`;
   - `silent`;
   - `wait`;
   - `reply`.
5. Add a mock language/execution port.
6. Trace every decision and score.

Acceptance:

- a 100-message group fixture does not trigger a full cycle for every message;
- direct mentions are prioritized;
- non-mentions may update conversation context without producing output;
- silence is recorded as a policy result, not an absence of processing;
- deterministic replay reproduces the same decision.

### Phase R3 — Persona, Self Model, Social Model, and disclosure

**Estimate:** 4–7 engineering days  
**Purpose:** Give persona and relationship state causal influence.

Tasks:

1. Implement minimal Self Model:
   - identity anchors;
   - values;
   - capabilities/limitations;
   - commitments placeholder;
   - slow-changing self beliefs.
2. Implement minimal Social Model:
   - familiarity;
   - trust;
   - attachment;
   - safety;
   - tension;
   - boundary violations;
   - uncertainty.
3. Implement persona view selection so an LLM or policy receives only relevant rules.
4. Implement disclosure gate based on relationship state and topic sensitivity.
5. Feed persona participation preferences into participation scoring.
6. Feed communication style only into language realization.

Acceptance:

- the same sensitive question produces different disclosure decisions for a stranger
  and a trusted relationship;
- message count alone cannot create trust;
- one positive event cannot reset tension or overwrite identity;
- style changes wording but cannot override disclosure or participation policy;
- all 15+ persona scenarios pass without exact-text assertions.

### Phase C4 — Perception, beliefs, appraisal, drives, and affect

**Estimate:** 6–10 engineering days  
**Purpose:** Introduce explicit cognitive state before action selection.

Tasks:

1. Add structured observations separating fact, inference, hypothesis, and uncertainty.
2. Add minimal belief records with confidence, evidence, contradiction links, and provenance.
3. Add rule-first appraisal:
   - goal relevance;
   - value alignment;
   - novelty;
   - certainty;
   - controllability;
   - social relevance;
   - responsibility.
4. Add minimal drive state:
   - autonomy;
   - social connection;
   - curiosity;
   - consistency;
   - uncertainty reduction;
   - safety.
5. Add minimal affect dimensions with inertia and decay.
6. Ensure appraisal and internal dynamics complete before participation/action selection.

Acceptance:

- observations are not automatically stored as facts;
- beliefs retain evidence and provenance;
- removing emotion labels from language prompts does not remove state influence on policy;
- affect cannot be reset by one event;
- all non-LLM transitions replay deterministically.

### Phase A5 — Goals, deliberation, action policy, and execution

**Estimate:** 6–10 engineering days  
**Purpose:** Separate deciding what to do from saying it.

Tasks:

1. Implement goal lifecycle:
   - active;
   - paused;
   - completed;
   - cancelled;
   - superseded.
2. Add structured action candidates with utility, risk, cost, reversibility,
   social impact, privacy impact, and required permission.
3. Add deliberation port; initially rule-based with optional structured LLM proposals.
4. Add explainable action scoring.
5. Add turn-taking rules for communicative actions.
6. Add executor ports and structured outcomes.
7. Add language generator receiving only the selected content plan and constraints.

Acceptance:

- the selected action has a score/reason breakdown;
- an LLM cannot execute tools or mutate goals directly;
- language generation cannot change the selected participation outcome;
- failed execution produces a structured, traceable outcome;
- idempotency prevents duplicate outbound actions.

### Phase M6 — Memory orchestration, outcome, and learning

**Estimate:** 5–8 engineering days  
**Purpose:** Add durable continuity without recreating V1 storage sprawl.

Tasks:

1. Implement working, episodic, semantic, social, autobiographical, and commitment
   memory as semantic categories over repository interfaces.
2. Store canonical memory metadata in SQLite.
3. Add retrieval reasons and provenance.
4. Add outcome evaluation and goal progress.
5. Add learning proposals for beliefs, relationships, retrieval weights, and strategies.
6. Add reflection triggers, but require validation before important updates.
7. Add embedding/vector index only after retrieval fixtures show a need.

Acceptance:

- one source of truth exists per concept;
- projections can be rebuilt;
- duplicate events cannot create duplicate memories;
- restart preserves canonical state;
- retrieval results include reason and provenance;
- LLM-derived memories cannot become facts without validation.

### Phase U7 — Initiative and autonomy guardrails

**Estimate:** 5–8 engineering days  
**Purpose:** Enable bounded endogenous behavior.

Tasks:

1. Implement internal triggers for commitments, deadlines, unresolved questions,
   available results, and high drive pressure.
2. Implement initiative proposals; they may not send actions directly.
3. Add per-user/channel rate limits, quiet hours, permissions, privacy rules,
   cost budgets, risk classes, opt-out, and audit log.
4. Add proactive-message shadow mode.

Acceptance:

- every initiative has a reason and originating trigger;
- guardrails can block an initiative without losing its trace;
- opt-out, quiet hours, permission, and rate limits are tested;
- irreversible or high-risk actions require confirmation;
- no proactive action bypasses action policy and executor.

### Phase P8 — Platform adapter and cutover

**Estimate:** 4–8 engineering days per initial platform  
**Purpose:** Connect V2 without coupling the kernel to an SDK.

Tasks:

1. Begin with a mock/CLI adapter.
2. Define versioned language-neutral inbound/outbound JSON schemas.
3. Choose either:
   - a temporary translator around the V1 relay; or
   - a new TypeScript/Python adapter.
4. Run V2 in shadow mode.
5. Enable one test channel, then one canary channel.
6. Remove production dependency on Rust only after guardrail and recovery gates pass.

Acceptance:

- kernel imports no platform SDK or platform-specific type;
- adapter contract tests pass;
- duplicate/reconnect behavior is idempotent;
- crash recovery and outbound rate limits pass;
- rollback is documented.

Implementation decision (2026-07-30): use a new Python/CLI adapter rather than a
translator around the V1 relay. V1 data and response compatibility are
non-requirements. Inbound contract `1.0.0`, outbound command `1.1.0`, simulated
receipt `1.1.0`, and external receipt `2.0.0` support shadow, test-canary, and
external-canary flows. Discord self-bot, Discord official bot, and Telegram
official bot are implemented as isolated Node.js connectors; live delivery
still requires explicit credential/conversation activation.

## 9. First Execution Batch: V2-001

This is the batch to start immediately after approval.

### Scope

- Create the Python project and quality tooling.
- Preserve persona sources and add a persona manifest.
- Implement only the common, inbound-event, and trace contracts.
- Implement SQLite event log and idempotent ingest.
- Implement minimal orchestrator with a no-op decision.
- Implement inspect/replay CLI.
- Add unit, contract, replay, and persona-source integrity tests.

### Expected file set

```text
pyproject.toml
src/polyverse/__init__.py
src/polyverse/app/config.py
src/polyverse/contracts/common.py
src/polyverse/contracts/events.py
src/polyverse/contracts/traces.py
src/polyverse/persona/models.py
src/polyverse/persona/loader.py
src/polyverse/persona/source/*
src/polyverse/runtime/orchestrator.py
src/polyverse/runtime/replay.py
src/polyverse/storage/database.py
src/polyverse/storage/migrations.py
src/polyverse/storage/repositories.py
src/polyverse/cli.py
tests/contract/test_events.py
tests/replay/test_event_replay.py
tests/unit/test_idempotency.py
tests/behavioral/persona/test_source_integrity.py
```

### V2-001 completion gate

- quality commands pass;
- persona source hashes are recorded and verified;
- event contract rejects unknown fields;
- repeated ingest is idempotent;
- event and cycle are inspectable;
- deterministic replay passes;
- no LLM or platform integration is present.

## 10. Testing Strategy

### Unit tests

- pure state transitions;
- attention scoring;
- inertia/decay;
- disclosure rules;
- participation rules;
- action scoring;
- guardrails.

### Contract tests

- inbound/outbound JSON schemas;
- schema-version rejection;
- adapter translation;
- tool/action inputs;
- unknown-field rejection.

### Persona behavioral tests

At minimum:

- stranger asks age;
- stranger asks exact location;
- stranger uses intimate nickname;
- stranger expects reciprocal disclosure;
- appearance compliment;
- technical request from stranger versus trusted user;
- privacy boundary violation;
- apology after conflict;
- topic change after conflict;
- friendly message streak without earned trust;
- no desire or reason to reply;
- group question directed at another person;
- Vietnamese/English language selection;
- multi-question message;
- pressure to behave like a generic assistant.

Assertions target decisions, disclosure classes, tone constraints, and prohibited
claims—not exact text.

### Replay tests

- raw fixture replay;
- duplicate event replay;
- restart replay;
- model-output replay using recorded structured responses;
- comparison of state deltas and decisions.

### Integration tests

- SQLite transaction boundaries;
- orchestrator vertical slices;
- mock LLM;
- mock tool executor;
- mock platform adapter;
- recovery after partial failure.

## 11. Architecture Gates

A phase cannot close unless:

- public contracts are typed and versioned;
- error semantics are explicit;
- configuration is visible in redacted resolved form;
- durable updates have provenance;
- deterministic transitions have replay fixtures;
- no circular dependency exists;
- no new storage system or framework was added without an ADR and measured need;
- persona behavior affected by the phase has behavioral coverage;
- the main cognitive path remains readable in one orchestrator.

## 12. Non-Goals

The early V2 implementation will not:

- migrate V1 messages, graph, episodic vectors, or numeric state;
- reproduce V1 responses;
- repair V1's failing tests;
- implement all memory types as separate stores;
- introduce a graph database;
- introduce online reinforcement learning;
- permit autonomous outbound messages;
- implement self-modifying code;
- support multiple platform SDKs before the kernel vertical slice is stable.

## 13. Key Risks and Controls

| Risk | Control |
|---|---|
| Persona becomes a large prompt again | Immutable source plus structured rules, source references, and behavioral tests |
| V2 repeats abstraction sprawl | Only create modules required by the current vertical slice |
| Core becomes nondeterministic | Sequential transitions and recorded model outputs |
| LLM regains policy authority | Structured proposal ports and independent policy validation |
| Social state becomes message-count closeness | Evidence-based relationship transitions and inertia tests |
| Silence becomes missing processing | Explicit participation outcome and trace |
| Storage sprawl returns | SQLite-first and ADR required for any new store |
| Autonomy causes spam | Initiative proposals cannot execute; guardrails and shadow mode are mandatory |
| Platform work blocks cognition | Mock adapter first, compatibility shim second |

## 14. Overall Completion Criteria

V2 can replace V1 when:

- persona behavioral suite passes;
- ingest, idempotency, replay, and crash recovery pass;
- structured relationship state affects disclosure and participation;
- appraisal/internal dynamics affect action selection, not only wording;
- silence, wait, reply, and join are explicit policy results;
- selected actions have traceable reasons;
- LLMs cannot directly execute or mutate canonical state;
- guardrails pass;
- one platform adapter passes contract, reconnect, and rate-limit tests;
- no production runtime dependency on the Rust kernel remains.
