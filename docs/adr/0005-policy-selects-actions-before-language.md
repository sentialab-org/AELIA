# ADR 0005: Select and authorize actions before language generation

- Status: Accepted
- Date: 2026-07-30

## Context

A language model that can choose participation, mutate goals, and execute an
action in one step is difficult to constrain or audit. Communicative intent,
turn-taking, permission, and execution failure need separate semantics.

## Decision

The kernel creates schema-bound action candidates and scores utility, goal fit,
drive/value/relationship effects, risk, cost, reversibility, privacy, confidence,
interruption, and permission. Turn-taking runs only for a selected communicative
candidate. Language generation receives only the materialized outbound action
and cannot change participation or goals. Execution returns a structured result,
including failure without side effects. Outbound idempotency keys derive from the
source event.

## Alternatives

- Let an LLM directly execute its preferred action: rejected because policy and permission are bypassed.
- Generate prose before action selection: rejected because wording can implicitly choose behavior.
- Treat execution failure as an exception only: rejected because the outcome would disappear from traces.

## Consequences

Cycles contain more intermediate artifacts, but selection is explainable and
replayable. The language and executor ports can be replaced independently while
the action decision remains fixed.
