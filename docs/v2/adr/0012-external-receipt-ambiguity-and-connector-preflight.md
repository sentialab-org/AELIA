# ADR 0012: Model live-delivery ambiguity and require connector preflight

- Status: Accepted
- Date: 2026-07-30

## Context

The side-effect-free adapter receipt intentionally fixes
`side_effect_performed=false`. A live connector cannot reuse that contract:
after a network timeout, the platform may have accepted a message even though
the connector did not receive its response. Treating that state as an ordinary
retryable failure can duplicate output.

The platform is not selected and no external-send authorization exists. The
shared safety semantics can still be specified and tested before SDK work.

## Decision

Keep the active mock receipt at `1.1.0` and define a separate, non-operational
external receipt contract `2.0.0`:

- `sent` requires a confirmed side effect and platform message ID;
- `not_sent` requires proof that no side effect occurred plus an error code;
- `unknown` represents ambiguous delivery, has no retry permission, and must be
  reconciled by idempotency lookup before any retry.

Define connector capability schema `1.0.0` and an executable static preflight
covering:

- idempotency lookup;
- explicit canary allowlist;
- independent kill switch;
- reconnect cursor;
- current permission probe;
- platform rate-limit observation; and
- secret redaction.

The CLI exposes the schemas through `adapter schema` and validates a manifest
with `adapter connector-preflight`. Static preflight is necessary but not
sufficient: an authorized connector must also pass the behavioral suite in
`CONNECTOR_ACCEPTANCE.md`.

## Alternatives considered

- Reuse `failed/retryable` from the mock receipt. Rejected because it cannot
  represent an unknown post-request side effect.
- Enable a generic live mode before choosing a platform. Rejected because
  account, permission, SDK, and reconciliation semantics are platform-specific.
- Rely on platform rate limits to prevent duplicates. Rejected because rate
  limits do not provide command idempotency or receipt reconciliation.

## Consequences

Future Discord or Telegram work begins with explicit failure semantics rather
than retrofitting them after a send path exists. No current configuration can
construct or dispatch an external receipt, and the runtime still has only
`shadow` and side-effect-free `test_canary` modes.
