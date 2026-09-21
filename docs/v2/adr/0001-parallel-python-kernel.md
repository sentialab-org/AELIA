# ADR 0001: Build V2 as a parallel Python modular monolith

- Status: Accepted
- Date: 2026-07-30

## Context

V1 is a useful architecture experiment but is not the behavioral baseline. Its
distributed Rust worker flow makes causal ordering, replay, and state ownership
hard to verify. Existing V1 runtime data is not a migration requirement.

## Decision

Build V2 under `src/polyverse` as a Python modular monolith. Keep V1 untouched
while V2 develops. The core transition is deterministic and sequential; async is
limited to storage and future external adapters.

## Alternatives

- Refactor V1 in place: rejected because it couples new invariants to experimental behavior.
- Start with microservices: rejected because no scale or isolation requirement justifies them.

## Consequences

V1 and V2 coexist temporarily. Cutover requires V2 acceptance gates, but no V1
behavioral parity or data migration.
