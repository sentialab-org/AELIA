# ADR 0002: Treat persona as versioned, hash-bound evidence

- Status: Accepted
- Date: 2026-07-30

## Context

The Ryuuko persona is the only V1 product asset that must be preserved. Keeping
it only as one large runtime prompt would make identity behavior implicit and
hard to test.

## Decision

Archive all persona sources byte-for-byte, record source hashes, and derive a
structured specification from the active source. Every rule references exact
1-indexed source lines and a passage hash. Behavioral tests assert decisions,
disclosure ceilings, tone constraints, and prohibited traits rather than exact prose.

## Alternatives

- Keep only the latest prompt: rejected because provenance and history would be lost.
- Duplicate editable prompt copies: rejected because it creates competing sources of truth.

## Consequences

Persona edits require a new source identity, hashes, specification revision, and
behavioral review. Runtime policy can use selected persona rules without loading
the full prompt into every decision.
