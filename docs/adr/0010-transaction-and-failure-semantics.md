# ADR 0010: Make transaction, failure, and retry semantics explicit

- Status: Accepted
- Date: 2026-07-30

## Context

The V2 report treats partial state, duplicate execution, and hidden retries as
architecture failures. The kernel already wrote a cycle atomically and the
adapter already used a transactional outbox, but recovered optimistic conflicts
were absent from the trace. A failed execution was structured yet the enclosing
cycle still appeared completed.

## Decision

Use the following failure model:

- A cognitive transition is computed before persistence. The inbound event,
  trace, canonical model updates, memory writes, goals, and selected action then
  commit in one SQLite transaction or all roll back.
- An expected executor failure is returned as `ExecutionResult(status=failed)`.
  The selected action is not rolled back; its goal remains unresolved, the
  outcome records failure, and trace schema `2.2.0` marks the cycle `failed`
  with the same structured error.
- Optimistic state conflicts are the only automatic kernel retry. They are
  bounded by `max_state_retries`. Every conflict recovered before a successful
  commit is persisted in contiguous `CycleRetry` history and included in exact
  replay.
- If all state retries are exhausted, no attempt is committed. The conflict is
  returned to the caller, which may safely redeliver the same event through the
  idempotent ingress boundary.
- An unexpected exception before the repository commit leaves no partial kernel
  state. Ports must return structured failures for expected errors and must not
  throw after performing an unreported side effect.
- Adapter delivery is separate from the kernel transaction. A command is
  reserved before transport use and finalized with a receipt; a crash leaves a
  recoverable reservation. The current transport is side-effect-free. A live
  transport requires a new receipt contract and connector-specific ADR.

Trace `2.1.0` remains readable and replayable. New traces use `2.2.0`; event,
action, and adapter contract versions do not change.

## Alternatives considered

- Roll back all cognitive state when execution fails. Rejected because the
  observation happened, the failure is itself evidence, and rerunning the full
  cycle risks duplicate action.
- Retry every exception automatically. Rejected because language, tool, and
  transport errors do not share safe retry semantics.
- Keep retries only in logs. Rejected because logs cannot support exact cycle
  inspection, comparison, and replay.

## Consequences

Failed execution is now queryable at both the action and cycle level. Recovered
contention is visible instead of silently disappearing. Kernel persistence has
one rollback rule, while external delivery retains its independent outbox and
recovery boundary.
