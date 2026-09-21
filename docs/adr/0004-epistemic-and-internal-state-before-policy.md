# ADR 0004: Separate epistemic state and update internal dynamics before policy

- Status: Accepted
- Date: 2026-07-30

## Context

V1 could treat model interpretations as state and evaluate affect after response
generation. That makes unsupported claims look factual and makes emotion
descriptive rather than causally relevant.

## Decision

Perception distinguishes observed events from inferred or hypothesized claims.
Self-reports enter the belief store as provisional hypotheses with evidence,
confidence, contradiction links, and provenance. Rule-first appraisal updates
drive and affect state before participation scoring. Affect uses bounded
inertia, and its policy contribution is recorded separately from persona and
attention contributions.

## Alternatives

- Store extracted claims directly as facts: rejected because observation does not establish truth.
- Generate a reply before appraisal: rejected because internal state cannot affect the current action.
- Keep affect only in prompts: rejected because removing wording would remove causal behavior.

## Consequences

Traces and transactions are larger, but epistemic mistakes, appraisal decisions,
and internal-state effects can be inspected independently. Repeated evidence may
raise belief confidence; contradictory evidence remains explicit.
