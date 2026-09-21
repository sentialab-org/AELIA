# AELIA — Definition of Done

Updated: 2026-07-30

A module or phase is complete only when every applicable item below has
reviewable evidence. “Not applicable” requires a written reason; a green test
suite by itself is insufficient.

## Contract and behavior

- [ ] Public inputs, outputs, and persisted artifacts use strict typed schemas.
- [ ] A public contract change has an independent version bump and compatibility
      decision.
- [ ] Policy outcomes have reason codes and deterministic fixtures.
- [ ] Persona-relevant behavior has source-traced behavioral coverage.
- [ ] Model or language output cannot bypass policy, permission, or execution
      ports.

## State and failure

- [ ] Each durable concept has one canonical source with provenance.
- [ ] Transaction boundaries, rollback behavior, idempotency, and duplicate
      handling are explicit.
- [ ] Expected failures are structured; automatic retries are bounded, safe, and
      visible in the cycle trace.
- [ ] Restart, conflict, or partial-failure recovery has an integration test when
      the module crosses an I/O boundary.

## Operability and privacy

- [ ] Resolved configuration is inspectable and has no unused knob.
- [ ] Structured logs contain cycle/event identifiers but exclude message
      content, secrets, and private identifiers unless explicitly approved.
- [ ] Cycle artifacts can be inspected, replayed, compared, and exported with
      redaction where applicable.
- [ ] External side effects have an allowlist, budget/rate limit, idempotency key,
      receipt, kill switch, and rollback procedure.

## Architecture and quality

- [ ] The main causal path remains readable in the explicit orchestrator.
- [ ] Dependency direction and import-cycle tests pass; the kernel imports no
      platform SDK.
- [ ] New dependencies, stores, frameworks, or major abstractions have an
      accepted ADR and measured need.
- [ ] Ruff format/lint, strict mypy, and pytest pass locally and in the V2 CI
      workflow.
- [ ] Documentation, requirement evidence, test count, and runbook are current.
- [ ] V1 remains isolated under `legacy/v1-rust/`; any change to its preserved
      source is separately authorized and recorded.

## Phase closure record

The closing review must name:

1. contract versions affected;
2. exact tests and replay fixtures proving acceptance;
3. remaining external or deferred gates;
4. database migration and rollback implications;
5. confirmation that no live side effect was introduced implicitly.
