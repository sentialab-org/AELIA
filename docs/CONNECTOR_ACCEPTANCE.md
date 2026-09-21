# AELIA — External Connector Acceptance Kit

Updated: 2026-08-24

This kit defines the evidence required before any connector is allowed to send
to a real platform. Discord self-bot, Discord official bot, and Telegram
official bot are implemented as isolated Node.js connectors; all live kill
switches remain off by default.

## 1. Inputs requiring owner authorization

- platform and account model;
- one test conversation and one later canary conversation;
- credential delivery mechanism outside the repository;
- named operator allowed to activate and stop the canary;
- permitted message/action types;
- canary start/end window and maximum sends.

## 2. Static contract preflight

The connector publishes a strict capability manifest using schema `1.0.0`.
Validate it without credentials or network access:

```bash
uv run aelia adapter connector-preflight path/to/capabilities.json
```

A passing report means only that required mechanisms are declared. It is not
evidence that they work. Machine-readable schemas are available through:

```bash
uv run aelia adapter schema
```

The implemented connector manifests are:

```bash
uv run aelia adapter connector-preflight \
  platforms/discord-selfbot/capabilities.json
uv run aelia adapter connector-preflight \
  platforms/discord-officialbot/capabilities.json
uv run aelia adapter connector-preflight \
  platforms/telegram-officialbot/capabilities.json
```

## 3. Mandatory offline contract evidence

- anonymized platform payloads normalize to inbound envelope `1.0.0`;
- unknown fields and contract versions fail deterministically;
- reconnecting the same platform event preserves the same event/idempotency key;
- command `1.1.0` maps reply and group-join targets correctly;
- secrets never occur in normalized events, exceptions, logs, or receipts;
- permission and channel identity mappings have fixtures;
- SDK imports exist only inside the connector package.

## 4. Mandatory authorized canary evidence

Run these only in the explicitly approved test conversation:

1. Kill switch defaults to off and prevents transport invocation.
2. Non-allowlisted conversation is blocked before an SDK send call.
3. Permission loss produces `not_sent`, never `unknown` or `sent`.
4. The same command/idempotency key dispatched twice creates one platform
   message and returns the same reconciled receipt.
5. A forced timeout before request transmission resolves to `not_sent`.
6. A forced timeout after request transmission resolves through platform lookup
   to either the original `sent` receipt or verified `not_sent`; it is never
   blindly retried.
7. Restart resumes the inbound cursor and pending outbox without duplicate send.
8. Connector and platform rate-limit evidence agree under concurrent commands.
9. Shadow rollback disables delivery without modifying kernel state or deleting
   audit records.

## 5. Evidence package

Promotion from test conversation to one canary conversation requires:

- exact connector commit and dependency lock;
- redacted resolved configuration;
- capability preflight report;
- offline contract-test output;
- authorized canary transcript with platform message IDs redacted or
  pseudonymized;
- outbox/receipt reconciliation report;
- zero unexplained `unknown` or pending delivery;
- operator, time window, send count, and rollback confirmation.

Production-primary status is not implied by one canary. The observation window
and explicit production approval remain separate gates.
