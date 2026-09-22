# DECISIONS — settled architecture decisions

**updated_at:** 2026-09-21T15:35:00Z
**rule:** append-only. A changed decision is **superseded by a new entry**, never
edited in place (`PROTOCOL.md` §6).

A decision recorded here is settled. It may be cited without re-reading code, and
**no agent may overturn one alone** — reopening requires the user.

A decision is **not** a claim about implementation. "We decided X" and "X is
built" are independent. A decision with no implementing code behind it is
recorded here *and* as a gap in `ARCHITECTURE_GAP.md`.

**The ADR set in `docs/adr/` is the primary evidence for these entries.** Where
an ADR is marked Accepted but its content is contradicted by the shipped code,
the decision stands and the implementation is the gap — the ADR is not reworded.

---

## D-001 — AELIA is the active development line; V1 Rust is frozen
**Status:** ACTIVE
**Source:** ADR 0001, ADR 0013
**Decision:** The Python kernel is the active line. The Rust workspace is a
frozen V1 reference — not the behavioural oracle, not a production fallback, and
not the default path for new work. `legacy/v1-rust/**` is byte-preserved and is
never repaired, extended, or migrated. V1 data is not migrated as part of AELIA
work. The only V1 asset carried forward is the byte-preserved, source-traced
persona package.
**Enforced by:** `tests/architecture/test_legacy_separation.py`.

## D-002 — The persona is versioned evidence, and its id is `ryuuko`
**Status:** ACTIVE
**Source:** ADR 0002
**Decision:** Persona sources are content-addressed and sha256-pinned in
`persona/source/manifest.json`. Archive files under
`persona/source/archive/*.txt` are never edited. The persona identity
(`ryuuko`) is deliberately separate from the system identity (AELIA); a rename
of the system does not rename the persona.
**Note:** the rename to AELIA preserved `persona_id` and every archive byte.

## D-003 — Deterministic traces and versioned state
**Status:** ACTIVE
**Source:** ADR 0003, ADR 0010
**Decision:** Every cycle produces a trace with a version; state carries a
version and is written under optimistic concurrency. The only automatic kernel
retry is a bounded optimistic state-conflict retry. An expected executor failure
leaves the selected action un-routed — it is not silently retried.

## D-004 — Epistemic and internal state are computed before policy
**Status:** ACTIVE
**Source:** ADR 0004
**Decision:** Perception, belief, world/self/social models, appraisal and internal
dynamics run **before** any action policy reads them. Policy consumes state; it
does not compute it.

## D-005 — Policy selects the action before language is generated
**Status:** ACTIVE
**Source:** ADR 0005
**Decision:** Action selection is policy-driven and happens first. Language
generation is downstream and **may not alter the decision**.
**Enforced by:** `src/aelia/contracts/traces.py:179-202` (raises on
`changed_participation` or on generation contradicting the decision).

## D-006 — Canonical memory, with learning gated on validation
**Status:** ACTIVE
**Source:** ADR 0006
**Decision:** Memory records are canonical; learning proposals do not become
canonical memory until validated. Learning is gated, not automatic.
**Gap:** the loop currently terminates at INSERT (see `ARCHITECTURE_GAP.md` G-07).

## D-007 — Initiative is shadow-only, behind guardrails
**Status:** ACTIVE
**Source:** ADR 0007
**Decision:** Autonomy may evaluate, score and decide, but **no code path turns a
decision into an outbound action**. Promotion beyond shadow is a future, separate,
explicitly-governed step.
**Enforced by:** `models/autonomy.py:186` (`Literal[False]`), the DB
`CHECK(… = 0)` at `storage/migrations.py:373-374`, and the absence of any
authorising member in `GuardrailOutcome`.
**Consequence:** the ADR's own `Consequences` section describes a future P8
promotion path with canary controls, recovery tests, and a route through action
policy and the executor. **That path is not built.** It is `RESEARCH`.

## D-008 — Versioned adapter with a transactional outbox
**Status:** ACTIVE as to the outbox; **SUPERSEDED IN PART** as to mode coverage
**Source:** ADR 0008
**Decision:** Outbound effects go through a versioned adapter and a transactional
outbox; a reservation is committed before the side effect and finalized by a
receipt.
**Supersession note:** ADR 0008's body asserts there is no live mode and no
external SDK, and ADR 0012's body asserts the runtime has only `shadow` and
`test_canary`. Both are retired by ADRs 0015/0016, under which an
`external_canary` mode and three Node connectors exist. **The ADRs were never
updated and still read Accepted, with no `Superseded` line.** That is a
governance defect recorded as G-14, not a licence to reword them.

## D-009 — Context models are rebuildable; group join is explicit
**Status:** ACTIVE
**Source:** ADR 0009
**Decision:** Conversation/context models are derived and rebuildable rather than
authoritative state. Joining a group is an explicit act.

## D-010 — Prompt registry is versioned per module
**Status:** ACTIVE
**Source:** ADR 0011
**Decision:** Each module's prompts are registered with a version and a hash, so
prompt provenance is traceable per module.
**Gap:** the registry's `input_schema`/`output_schema` are inert, and the
definition version drifted to `1.2.0` (`llm/prompts.py:21`) against ADR 0014.

## D-011 — External receipt ambiguity, and connector preflight
**Status:** ACTIVE
**Source:** ADR 0012
**Decision:** An external receipt is the authority on whether a side effect
happened. Where the outcome is ambiguous, it is recorded as ambiguous — never
assumed. Connectors are preflighted before they are trusted.
**Gap:** `ConnectorReadinessPolicy` performs no probing; it promotes declared
manifest booleans into a readiness verdict (`adapters/conformance.py:56-71`).
The *decision* stands; the *check* is not a check. See G-11.

## D-012 — OpenAI-compatible async language provider
**Status:** ACTIVE
**Source:** ADR 0014
**Decision:** The language provider is an async OpenAI-compatible Chat
Completions client, configured through typed config.
**Gap:** no production orchestrator injects a real `LanguagePort`, so the live
cycle runs the mock.

## D-013 — Isolated Node connectors, one per platform
**Status:** ACTIVE
**Source:** ADR 0015, ADR 0016
**Decision:** Platform connectors are isolated Node processes under `platforms/`,
each with its own ignored credentials and a default-off send switch. They speak
to the backend over the versioned HTTP gate protocol. They do not import the
Python kernel and do not shell out to it.
**Enforced by:** `tests/architecture/test_runtime_backend_separation.py:22-62`.

## D-014 — The runtime backend and the platform gates are independent processes
**Status:** ACTIVE
**Source:** ADR 0017
**Decision:** The backend is a standalone process; platform gates reach it over
HTTP through versioned endpoints. Operations are unary today, so the boundary is
HTTP. WebSocket is **reserved, not built**.
**Gap:** gate-token auth fails open when the token is unset.

## D-015 — The system name is AELIA
**Status:** ACTIVE
**Recorded:** 2026-09-21, this bootstrap
**Decision:** The system, repository, Python package, CLI and environment prefix
are **AELIA** (`sentialab-org/AELIA`, `src/aelia`, `aelia`/`aelia-backend`,
`AELIA_*`). The persona keeps its own identity (D-002). Adapter ids keep their
`-v2` suffix, which distinguishes a platform adapter generation from the V1 Rust
system and is not a product name.
**Evidence:** `EVENTS.jsonl` `evt-2026-09-21-002`, `evt-2026-09-21-003`.
**Note:** treated by the code as a breaking change (env prefix).

## D-016 — This coordination layer is mandatory
**Status:** ACTIVE
**Recorded:** 2026-09-21, this bootstrap
**Decision:** Every agent session on this repository — Claude Code, ChatGPT, or
human — follows `PROTOCOL.md`. The three labels (`IMPLEMENTED` / `DECIDED` /
`RESEARCH`) are mandatory on every factual claim. `EVENTS.jsonl` and this file
are append-only. When code and any document disagree, **the code is right and the
document is a bug**.
**Enforcement:** root `CLAUDE.md` requires it for Claude Code sessions.

---

## Superseded

| Entry | Superseded by | Date | Note |
|---|---|---|---|
| — | — | — | none yet |

---

## Change log

| Date | Change |
|---|---|
| 2026-09-21 | D-001 … D-016 recorded at bootstrap. |
