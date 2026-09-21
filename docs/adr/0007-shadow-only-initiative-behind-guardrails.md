# ADR 0007: Keep initiative shadow-only behind complete guardrails

- Status: Accepted
- Date: 2026-07-30

## Context

Endogenous behavior is necessary for commitments, deadlines, unresolved
questions, available results, and high drive pressure. Allowing those signals to
send messages directly would introduce spam, privacy, permission, budget, and
irreversibility risks before a production adapter and recovery path exist.

## Decision

Internal trigger detection creates causal, provenance-bearing trigger records.
The initiative manager converts each trigger into a proposal; it has no executor
dependency. Every proposal is evaluated against:

- autonomy mode;
- actor and conversation opt-out;
- timezone-aware quiet hours;
- explicit proactive permission;
- private-context permission;
- per-actor and per-conversation hourly limits;
- a global daily shadow-cost budget;
- minimum expected value;
- risk, reversibility, and explicit confirmation.

Blocked, confirmation-required, and shadow-approved results remain in the cycle
trace and append-only autonomy audit. U7 exposes only `disabled` and `shadow`
modes. Even a fully approved proposal records
`proactive_action_materialized=false`; no code path turns it into an outbound
action.

Rate and budget inputs are rechecked inside the SQLite write transaction so
concurrent cycles retry rather than exceeding a stale allowance.

## Alternatives

- Send immediately after initiative scoring: rejected because it bypasses
  participation, action policy, execution idempotency, and operational rollback.
- Rely only on a global rate limit: rejected because one actor or channel could
  still be spammed.
- Treat shadow decisions as unpersisted logs: rejected because rollout evidence
  and blocked decisions would be lost.

## Consequences

Initiative quality and guardrail behavior can be measured without contacting
users. Live proactive delivery remains unavailable until P8 supplies a versioned
adapter boundary, canary controls, recovery tests, and an explicit promotion
path through action policy and the executor.
