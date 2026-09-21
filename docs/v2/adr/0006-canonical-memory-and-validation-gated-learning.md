# ADR 0006: Store canonical memory references and gate learning by validation

- Status: Accepted
- Date: 2026-07-30

## Context

V1 spread related information across message, short-term, vector, graph, and
social-tree stores. That made ownership, synchronization, provenance, and
correction ambiguous. V2 needs continuity without creating a second mutable
truth for beliefs, relationships, identity, or goals.

## Decision

Use one SQLite memory registry whose records contain category, scope, ranking
metadata, provenance, and a reference to the canonical source. Working memory is
a non-persisted projection of the conversation buffer. Semantic, social,
autobiographical, procedural, and commitment records reference the belief,
relationship, persona/self-model, policy version, and goal that own their state.
Episodic records reference immutable inbound events.

Retrieval is rule-based, records reason codes and provenance, and is modulated by
the prior internal state. Only observed or validated memories can contribute
positive support to action scoring; provisional semantic memories remain visible
but cannot act as facts. No vector index is enabled.

Outcome evaluation follows execution. A failed executor leaves its request goal
active with zero progress. Learning and reflection emit immutable proposals in
`pending_validation` state; they never mutate persona, policy, beliefs,
relationships, retrieval weights, or strategies directly.

## Alternatives

- Separate database per memory category: rejected because it recreates
  synchronization and source-of-truth ambiguity.
- Persist working memory independently: rejected because it duplicates the
  bounded conversation buffer.
- Promote model-derived summaries directly to facts: rejected because model
  output is not validation.
- Apply online policy updates automatically: rejected because important learning
  must remain reviewable and reversible.

## Consequences

Memory is simpler to inspect, replay, and restore after restart. Static and
canonical state remains owned by its domain model. Retrieval quality is limited
to deterministic metadata ranking until fixtures demonstrate a need for a
rebuildable vector projection.
