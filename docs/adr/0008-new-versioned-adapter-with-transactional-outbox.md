# ADR 0008: Use a new versioned adapter with a transactional outbox

- Status: Accepted
- Date: 2026-07-30

## Context

V1 relay behavior and runtime data are not migration requirements. Reusing the
Rust relay would preserve coupling to a draft architecture. The V2 kernel still
needs a language-neutral boundary, reconnect idempotency, bounded outbound
routing, and recoverability across process crashes.

## Decision

Build a new Python/CLI adapter around strict JSON schemas. An ingress envelope
contains a stable delivery id, idempotency key, adapter identity, receive time,
and V2 inbound event. The adapter records delivery hashes and delegates only the
normalized event to the kernel.

Selected kernel actions become versioned outbound commands. The adapter reserves
each command in a SQLite outbox before transport, keyed by the kernel action
idempotency key. Recovery replays pending reservations. The transport contract
must honor the same key, covering a crash after transport but before receipt
finalization.

Routing exposes only:

- shadow suppression; and
- allowlisted, rate-limited test-canary simulation through a mock transport.

There is no live mode, external SDK, or side-effecting receipt in this contract
version.

## Alternatives

- Translate through the V1 relay: rejected because no V1 compatibility or data
  constraint justifies keeping that dependency.
- Couple Discord/Telegram SDK objects to the kernel: rejected because contracts,
  replay, and platform replacement would become adapter-specific.
- Call transport before reserving an outbox row: rejected because crashes could
  create untraceable duplicate delivery.
- Enable live delivery behind an environment flag: rejected because a flag alone
  does not supply account authorization, security review, or rollback evidence.

## Consequences

The CLI is the first concrete adapter and a portable contract reference for
future platform processes. Shadow/reconnect/recovery behavior is testable now.
External platform selection and real canary delivery remain explicit later
decisions rather than hidden configuration.
