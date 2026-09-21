# ADR 0003: Persist deterministic traces with optimistic state versions

- Status: Accepted
- Date: 2026-07-30

## Context

Observation, silence, relationship changes, and persona influence must be
explainable and replayable. Concurrent messages must not silently overwrite
conversation or relationship state.

## Decision

Persist each inbound event, cycle trace, decision artifact, conversation
position, and social transition in one SQLite transaction. Conversation and
relationship writes compare the state version observed by the transition.
Replay uses the recorded input snapshots and dispatches by orchestrator version.

## Alternatives

- Last-write-wins updates: rejected because causal state can be lost.
- Store only final replies: rejected because silence and internal changes disappear.
- Replay against current database state: rejected because results become time-dependent.

## Consequences

Stale transitions retry from fresh state. Traces are larger, but decisions,
persona influence, disclosure, and social provenance can be audited exactly.
