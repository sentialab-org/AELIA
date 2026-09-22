# HANDOFF — Claude Code → ChatGPT

```
From:        claude-code
To:          chatgpt
Timestamp:   2026-09-22T00:00:00Z
Context:     AELIA coordination bootstrap. A full read-only audit of the Python
             kernel was completed so that any architectural discussion starts
             from verified implementation rather than from documents. A second
             pass then measured the production database — which the first pass
             had not done — and found that the most important defects are
             visible only there.
Findings /
Request:     Seven findings and ten questions below. The request is a written
             target architecture for AELIA, plus a per-element statement of
             which current component it replaces, extends, or leaves alone.
Questions:   Q-01 … Q-10, each answerable independently.
Status:      awaiting-input
```

Read `PROTOCOL.md` first — it binds you as much as it binds Claude Code. Then
`CURRENT_STATE.md`, `ARCHITECTURE.md`, `ARCHITECTURE_GAP.md`, `DECISIONS.md`.
The short version: **every factual claim carries `IMPLEMENTED` (with a
`file:line`), `DECIDED` (with a `DECISIONS.md` entry), or `RESEARCH`. An Accepted
ADR is evidence for what was decided, never for what is built.**

---

## 1. Repository state

| | |
|---|---|
| Remote | `https://github.com/sentialab-org/AELIA.git` (SENTIA Lab) |
| Branch | `dev` @ `89b8099f23ca0682ea0b8b8f39e6bf574c2ed280`, pushed, in sync with `origin/dev` |
| Local | `/Users/zvwgvx/Project/AELIA` |
| Package | `aelia` in `src/aelia` — 73 files, 13,490 lines |
| Tests | 39 files, 191 collected cases |
| ADRs | 17 (`docs/adr/0001…0017`) |
| Node | 4 packages under `platforms/` |
| DB | `data/aelia.db`, SQLite WAL, **748,343,296 bytes (713.68 MB) of real user data — never delete**. 4,085 cycles, 85,832 trace artifacts |

**Lineage:** `zvwgvx/ryuuko-chatbot` → `polyverse-agent` → `sentialab-org/AELIA`.
The local tree was renamed to AELIA on 2026-09-21 across three commits (baseline
tree, atomic rename, identity guards). The persona survived the rename with its
own identity intact: `persona_id` is still **`ryuuko`** (ADR 0002).

**`main` already contains the merge base.** `main` and `origin/main` are both at
`4f78991` ("Merge dev into main"), and the merge base with `dev` is `68a3359`,
which `main` already contains. `main` is therefore **not** the V1 Rust monorepo
at root — it carries the same top-level layout as `dev` (`src/`, `docs/`,
`legacy/`, `platforms/`). An earlier draft of this section described the merge as
pending and unauthorised; it has already happened.

What remains is a 12-file divergence (`git diff --stat 68a3359 main`):
`.gitignore`, plus eleven files under `legacy/v1-rust/docs/wiki/` that upstream
pull requests edited *inside* the byte-preserved archive ADR 0013 freezes —
including `legacy/v1-rust/docs/wiki/local-interfaces/platform-relay.md`, which
upstream added at exactly the path this tree would have chosen for it.
Reconciling those eleven against the ADR 0013 freeze is a decision, not a
fast-forward, and it has not been made.

**What is live right now.** `config.toml` has `mode = "external_canary"` with
`send_enabled = true` for the Discord selfbot, and
`allowed_conversation_ids = ["-1"]` (accept every visible channel). The system is
live-capable. Treat any run against that config as touching a real platform.

---

## 2. Current Python architecture

Twelve packages under one machine-enforced import direction
(`tests/architecture/test_dependency_direction.py`):

```
contracts ──► models ──► cognition ──► runtime ──► app ──► backend
                 │           │            │
                 └───────────┴────────────┴──► storage · llm · persona
                                                · adapters · autonomy
```

**One cycle, one transaction.** Ingress → `AutonomyOrchestrator.transition`
(`runtime/orchestrator.py:1246`) → Memory → Action orchestrators →
ConversationPolicy → Attention → Perception → Belief → Appraisal → Internal
Dynamics → Goals → ActionPolicy + TurnTaking → content plan → language
generation → execution → one transaction writing the whole result, under an
optimistic state-version check that retries on `ConcurrentStateError`.

**Three genuinely enforced invariants** (raise or DB constraint, not convention):

1. Language generation cannot alter the decision — `contracts/traces.py:179-202`.
2. A proactive action can never be materialized — `models/autonomy.py:186`
   `Literal[False]` plus a DB `CHECK(… = 0)` at `migrations.py:373-374`.
3. No vector index is used — `models/memory.py:129`, `Literal[False]`.

**Ports are `typing.Protocol` injection seams** (`LanguagePort`,
`ExecutionPort`, `LanguageGeneratorPort`) — structural, not `@runtime_checkable`.

**Persistence:** one SQLite DB, 24 tables + `schema_migrations`, 8 migrations.
Measured: the trace is stored **twice** (`cycles.trace_json` + `cycle_artifacts`)
and those two tables are **92.6% of the database**; retention exists for exactly
two tables and neither is a trace table. See T-5.

**Process split:** the backend is standalone; the three connectors are isolated
Node processes speaking versioned HTTP to `/v1/gates/ingress` and
`/v1/gates/receipts`, delivering only commands the backend returns as
`queue_external_canary`. WebSocket is **reserved and absent**.

---

## 3. Major architectural changes from the Rust V1

| Dimension | V1 Rust (frozen, `legacy/v1-rust`) | AELIA Python (current) |
|---|---|---|
| **Shape** | Cargo workspace, 13 crates, `apps/` + `libs/` + `services/` | One Python package, 12 subpackages, layer-enforced by test |
| **Composition root** | `apps/agent/src/main.rs` | `app/bootstrap.py` — *nominally*. A second root lives in `cli.py` (G-01) |
| **Process model** | UDS relay (`libs/sensory/src/relay/`) plus separate platform services | HTTP unary gates; connectors as isolated Node processes outside the kernel |
| **Concurrency** | `Worker` + mpsc `EventBus` + `Coordinator` + `Supervisor` | One async cycle, correctness carried by optimistic concurrency on SQLite, not by a supervisor tree |
| **State** | `libs/memory/` memory and state space | 24 SQLite tables, versioned state, 8 migrations |
| **Behaviour source** | The Rust implementation *was* the system | Rust is explicitly **not** the behavioural oracle, fallback, or default path |
| **Governance** | None | 17 ADRs, machine-enforced architecture gates |
| **Persona** | The only V1 asset carried forward | Byte-preserved, sha256-pinned, source-traced (ADR 0002) |

**The single most consequential change:** V1's supervisory process topology was
replaced by *transactional correctness*. There is no supervisor, no bus, no
service mesh in AELIA — correctness now rests on one SQLite transaction and a
version check. That is a real simplification, and it moves the entire
reliability burden onto the storage layer, which is where G-15 and G-22 live.

**Second:** V1 kept the platform code inside the workspace. AELIA pushes it out to
isolated Node processes with a gate protocol and a default-off send switch. This
is the decision most responsible for the current debt shape — the kernel and the
connectors no longer share a type system, so contract drift is only catchable by
the hand-asserted `capabilities.json` (G-11).

---

## 4. Known technical debt

The full register is `ARCHITECTURE_GAP.md` §A.1 (G-01…G-35) for what code-reading
finds, and **§A.1b (G-36…G-45) for what the production database shows that
code-reading cannot**. The seven that should shape any target architecture:

**T-1 · There is no guardrail outcome that authorises an action (G-03).**
`GuardrailOutcome = {BLOCKED, REQUIRE_CONFIRMATION, SHADOW_APPROVED}`, and the
mode check passes only for SHADOW. Shadow-only is not a configuration — it is a
closed door, enforced again by a DB `CHECK` constraint. Additionally, nothing in
`src/` constructs a `PermissionContext`, so every scope the guardrails read is
empty (G-04), and **the two sides of that boundary share no vocabulary at all**
(see T-6). ADR 0007 defers promotion to an unbuilt "P8" path.

**T-2 · The memory learning loop terminates at INSERT (G-07, G-10).**
`cycle_outcomes`, `learning_proposals` and `reflection_triggers` have no read
path anywhere in `src/`. Retrieved memory never reaches the prompt path. ADR
0006's "validation-gated learning" is Accepted and has nothing behind it. Ten of
24 tables have no reader; 17 `*_sha256` columns are written and exactly one is
ever compared. **Measured: `beliefs` holds 0 rows after 4,085 cycles (G-38)** —
the belief layer is not merely unread, it is never populated.

**T-3 · Declared ≠ enforced, and checks that cannot fail (the systemic one).**
Connector readiness is a verdict over hand-written booleans (G-11). The persona's
disclosure ceiling is advisory prompt text (G-19). The self-model asserts
`limitation.no_live_language_model` while the LLM is wired (G-31). Gate-token
auth fails open when the token is unset (G-06). An empty allowlist rejects
everything (403). Four architecture gates passed vacuously after the rename and
had to be repaired by hand in `68a3359`. **Any target architecture that does not
say explicitly how each guarantee is enforced will reproduce this.**

**T-4 · The live cycle does not use the real ports (G-05).**
No production orchestrator injects a `LanguagePort`, so `ContentPlan` always
comes from `MockLanguagePort`; the default `ExecutionPort` is the mock, so
`execution_result` is always `SIMULATED`. The OpenAI-compatible provider is
implemented and reachable — but not through the cycle as wired. The prompt is
composed and hashed on paths that never send it (G-33).

**T-5 · The trace is written twice and owns the database, and nothing reaps it
(G-37, G-39).** `cycles.trace_json` and `cycle_artifacts` are the same trace
stored two ways: **660.85 MB of 713.68 MB — 92.6%** — at 21.0 artifact rows per
cycle. Retention exists for exactly two tables (`conversation_buffer`,
`conversation_participation`); **no reaper touches either trace table**, and
growth is ≈264 MB/day. The same inbound text is persisted in at least four
places. This is not a performance footnote: the trace tables are the *durable
system of record*, and there is currently no policy saying so, no bound on them,
and no way to read back a cycle without them.

**T-6 · The permission boundary's two halves share no vocabulary (G-36).**
Producers emit only `explicit_mention` and `message_thread`. Consumers read only
`send_message`, `proactive_message`, `confirm_high_risk`, `confirm:{id}` and
`proactive_private`. **The intersection is empty**, so the scope check cannot
pass for any input. This is stronger than G-04 ("no `PermissionContext` is
constructed"): even if one were constructed, the strings could not match. Any
target safety model must first say what a scope *is*, and who mints one.

**T-7 · Only the database distinguishes "the machinery ran" from "state
accrued" (G-38, G-44, G-45).** The first audit pass read 13,490 lines of code
and every test and concluded the belief layer, the outbox and the enums were
implemented. The database says: `beliefs` 0 rows; `outbound_actions` and
`adapter_dispatches` 9 each — and G-44 shows they agree **by accident**, the
outbox being authoritative and `outbound_actions` a write-only mirror.
**The coverage lesson is itself a finding: an audit that never queries the
database will systematically miss the class of defect where the machinery runs
and the state never accrues.**

Runner-up: replay's determinism guarantee is weaker than its name — the
compatibility shim copies expected values into the actual trace before hashing
(G-18). Any refactor of `replay.py` must pin that behaviour with a
characterization test *first*, or the refactor will silently change what
"deterministic" means.


---

## 5. Unanswered architectural questions

Each is answerable independently. **These are for the target discussion; none is
a request to change code now** (audit-only freeze in force).

Two things that look like questions are **already answered by reading, not by
deciding**, and are recorded here so they are not reopened: the test count is
**191 cases across 39 files** (`docs/IMPLEMENTATION_STATUS.md` said 182 until it
was re-measured and corrected in place on 2026-09-22), and the authoritative
outbound record is **`adapter_dispatches`**, not `outbound_actions` (G-44).

Q-01 is tracked as `TASKS.yaml` **T-004**; Q-07/Q-08 as **T-013**, and Q-09 as
**T-015** (all `blocked`, owner `user`). Q-02…Q-06 and Q-10 are not yet tasks —
they are questions for the target architecture, and are listed here rather than
tracked as work.

**Q-01 — What is the intended path from a decided autonomy action to a real
action?** Today: no authorising `GuardrailOutcome`, a `Literal[False]` field, a
DB `CHECK` constraint, and empty permission scopes. ADR 0007 defers to a P8 with
canary controls and a route through action policy and the executor — unbuilt, and
unspecified. Does promotion require a new guardrail outcome and a mode member, or
a separate decision path entirely? Who answers `REQUIRE_CONFIRMATION`, and
through what surface? **Related: T-014** — whatever answers this must also name
the permission-scope registry and who mints a scope (G-36).

**Q-02 — Is the external-canary connector the target integration model, or an
interim one?** ADRs 0015/0016 shipped it; ADRs 0008/0012 still read Accepted while
asserting there is no live mode (G-14). If it is the target, the readiness
problem becomes architectural: how is a connector's capability *verified* rather
than declared, now that kernel and connector share no type system?

**Q-03 — Is the learning loop part of AELIA, or is it being retired?** The tables
exist, the writes happen, ADR 0006 is Accepted — and nothing reads any of it. Is
the intent to complete the loop (validation → canonical memory), or to stop
paying for write-only tables?

**Q-04 — Is semantic retrieval in scope?** `vector_index_used` is locked
`Literal[False]` and no embedding dependency exists. If AELIA is meant to recall
by meaning, this is a decision that changes the storage layer. If not, the field
should stop implying it is merely switched off.

**Q-05 — What is the target for the world / self / social models?** The world
model is rebuilt and discarded every cycle. Only one orchestrator is live; six
exist unreferenced. Are those six the target decomposition (with v2-007 to be
defined), or a superseded one to be deleted?

**Q-06 — Autonomy under a live platform: what is the actual safety model?** Rate
and cost inputs are constants (G-34); blocked decisions consume no budget; the
opt-out path has no production caller; the connector's own `max_sends_per_hour`
is enforced nowhere (G-26); and the backend's ingress gate fails open without a
token (G-06). Before autonomy can act, this needs to be a decided model rather
than a set of guards that happen to be closed.

**Q-07 — What is the retention and compaction policy for the trace?** The trace
tables are 92.6% of the database and grow ≈264 MB/day with no reaper (G-37).
`cycles.trace_json` and `cycle_artifacts` store the same trace twice. Is the
duplication intended (one for replay, one for query) or accidental? Is there a
horizon after which a cycle's full trace may be summarised or dropped? Without an
answer the storage layer cannot be refactored safely, and it will eventually fail
on volume rather than on a bug.

**Q-08 — Is the trace a system of record, or a debug aid?** This is the question
underneath Q-07, and it is the one that changes the architecture. A system of
record needs durability, a versioned schema, and a documented read API. A debug
aid needs a bound and a switch. Today it is treated as both and built as neither:
`LanguageGenerationResult` — the one boundary contract the LLM actually crosses —
carries **no `schema_version`** (G-40), while every request-side contract does.

**Q-09 — What is the multi-process contract for one SQLite file?** `data/aelia.db`
is opened concurrently by the CLI, the FastAPI backend and the adapter runtime.
The backend guards its own writes with an **in-process** `asyncio.Lock`
(`backend/application.py:57`), which is not a cross-process guarantee. Optimistic
version checks under `BEGIN IMMEDIATE` (ADR 0010) may be sufficient — but that is
a claim to be stated and tested, not assumed. If AELIA is ever multi-process by
design, this decision constrains everything above it.

**Q-10 — Must `conversation_id` be platform-namespaced?** Conversation state is
keyed on a bare `conversation_id` with no platform column, while social state is
`UNIQUE(platform, actor_id)` (G-42). Both Discord connectors derive the same
`conversation_id` from the same channel, so one channel seen through both
connectors collides in one table and not the other. Is that intended (one
conversation, two transports) or a latent data-model bug?

One further question belongs to the target discussion rather than to the current
code, and is recorded here only so it is not lost: **should the LLM be permitted
to propose actions, or only to realise decisions already made?** Today it cannot
propose (`model_proposals_enabled = False`), and T-4 shows it does not yet
realise either. The target should say which of the two AELIA wants, because the
answer determines whether the language layer sits inside or outside the decision
path.

---

## 6. Recommended next migration boundaries

Offered as **boundaries** — where to draw lines — not as a plan. Every item is
`RESEARCH` until it becomes a `DECISIONS.md` entry, and nothing here is
authorised under the current audit-only freeze.

### The rank

The ordering below is measured, not preferred: **inbound references in `src/`,
existing coverage in `tests/`, and coupling to persisted state.** A module with
few inbound references and real tests can be changed and verified in one
sitting; a module with many of both, sitting on live data, cannot. Counts are
static reference counts over `src/` and `tests/` at `68a3359`.

| # | Boundary | `src` refs | `tests` | Why here |
|---|---|---|---|---|
| 1 | `runtime/ports.py` | 4 | 7 | The safest first slice. It is the seam itself — pure `Protocol` declarations with no persisted state — and it already has the thickest test coverage of anything on this list. |
| 2 | `runtime/replay.py` + `runtime/observability.py` | 1 / 1 | 8 / 1 | Well covered, but **write a characterization test pinning G-18's current behaviour first**. Otherwise the refactor silently redefines "deterministic" and the suite will not notice. |
| 3 | `adapters/conformance.py` | 1 | 1 | Contained. Replacing the tautological readiness verdict (G-11) with a real probe is a local change to one file plus its contract test. |
| 4 | `cognition/deliberation.py` | 1 | **0** | **Needs a test written before it is touched.** Zero test files reference it; it is the clearest case in the repository of code that is load-bearing and unverified. |
| 5 | `llm/prompts.py` (102 lines) + `models/prompt.py` (68 lines) | 1 / 2 | 1 / 1 | The prompt registry: small, confined to two files, and already version-stamped (`1.2.0`). This is where G-40's missing `schema_version` on the result contract should be fixed. |
| **last** | `storage/` | **8** | 9 | **Do not start here — last by construction, not by preference.** 24 tables, 8 migrations, 93% of the database's bytes, the highest inbound reference count in the tree, and the one place where a mistake destroys real user data. It is also where T-5, T-7 and Q-07/Q-08/Q-09 all land. |

**Why the rank matters more than the list.** The first five are all safe to do
in *either* order — they are small, tested or testable, and hold no state. The
last one is unsafe until Q-07 (retention), Q-08 (system of record) and Q-09
(multi-process) are answered, because each of those answers changes the schema.
Starting at `storage/` because it is where the pain is measured is exactly how a
migration destroys the corpus it was meant to preserve.

### Standing boundaries

**B-1 · Do not refactor side A toward side B until side B exists in writing.**
This is the whole point of the bootstrap. `ARCHITECTURE_GAP.md` side B is
deliberately empty. Refactoring toward an unwritten target is precisely how a
repository ends up with documents describing capabilities the code lacks.

**B-2 · Draw boundaries at enforcement, not at features.** The systemic debt
(T-3) is that guarantees are declared rather than enforced. Before adding
capability, each guarantee should have exactly one site that can fail. The
cheapest first move: make the security-relevant ones fail closed — gate-token
auth (G-06) and the readiness verdict (G-11). Both are small changes with
outsized effect on what the repository can be trusted to mean.

**B-3 · The two composition roots (G-01) are a prerequisite, not a cleanup.**
Until there is one root, every wiring claim is a claim about whichever root the
reader happened to open.

**B-4 · Decide the memory/learning scope before touching storage.** G-07, G-10,
G-15, G-23 and G-24 are one decision, not five bugs. Ten unread tables, a
`beliefs` table with zero rows and a locked `vector_index_used` cannot be
resolved component-by-component.

**B-5 · Keep the frozen and live sides apart, permanently.** `legacy/v1-rust/**`
is byte-preserved (ADR 0013); the persona archive is sha256-pinned (ADR 0002);
`data/**` is real user data. None of these is a migration target. The V1
dev-notes (graph memory, social tree, truth knowledge graph) are **V1 designs
inside a frozen archive** — historical input to the target discussion, never a
specification for AELIA.

**B-6 · Do not let the six unreferenced orchestrators set the boundary by
default.** They are 6/7 of the orchestrator code and 0/1 of the live paths.
Either they are the target decomposition or they are dead weight; leaving them
in-between is what produced `v2-007`, an orphaned version with no constant, no
producer and no replay branch.

**B-7 · `main` stays divergent until the user decides.** The merge is a
structural decision about where the Rust monorepo lives, and it is the user's.

---

## 7. What this handoff is asking for

A written target architecture for AELIA covering the questions above, and — for
each element — an explicit statement of whether it **replaces**, **extends**, or
**leaves alone** the corresponding side-A component. Answers become
`DECISIONS.md` entries (`D-017` onward); unresolved ones stay open questions and
are recorded as such.

Until then, side A is frozen as-is. That is not caution — it is the only way the
next session can tell what is built from what is described.

**One request that is not architectural, and is cheap.** Q-07 through Q-09 all
sit on `storage/`. A short written answer to those three unblocks the largest
single mass in the repository. Nothing else in the rank is waiting on anything.

---

*Prepared from a read-only audit of `68a3359`: 16 subsystem passes over
`src/aelia`, `tests/`, `platforms/`, `docs/` and `docs/adr/`, plus a survey of
`legacy/v1-rust`. No file in `src/`, `tests/`, `platforms/` or `docs/` was
modified. Nothing was executed against a live platform.*

*Revised after a completeness review found the first pass had never queried
`data/aelia.db`. Every figure added since was measured read-only against it
(`file:…?mode=ro`, `PRAGMA query_only=ON`) and every code claim was re-checked
with a positive control. See `ARCHITECTURE_GAP.md` §A.1b.*
