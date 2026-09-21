# ADR 0015: Isolated Node Discord self-bot external canary

- Status: Accepted by owner
- Date: 2026-07-30

## Context

The owner selected the V1 Discord self-bot behavior as the first V2 platform
integration and explicitly accepted the account-level platform risk. V1 coupled
an unofficial Discord client to a Rust relay. V2 already had language-neutral
inbound/outbound contracts and a simulated canary, but it did not yet accept a
real external delivery receipt.

Sending directly from a connector while preserving the old simulated receipt
would make the audit record false. Importing the Discord SDK into the Python
kernel would also violate the platform boundary.

## Decision

Create `platforms/discord-selfbot` as an independent Node.js process using
the same self-bot library version referenced by V1. The connector:

- owns all Discord SDK types and user-account authentication;
- normalizes Discord messages into inbound envelope `1.0.0` and event `2.0.0`;
- invokes the V2 CLI adapter over stdin/stdout JSON;
- requires a channel allowlist and defaults its send kill switch to off;
- queues real commands through the new `external_canary` adapter mode;
- records an fsynced attempt journal before transport invocation;
- never blindly retries an ambiguous send;
- finalizes the Python outbox with external receipt `2.0.0`;
- redacts the Discord token from child-process environment and logs; and
- keeps the connector dependency graph outside the Python kernel.

`shadow` and `test_canary` retain their previous behavior. `external_canary`
never calls the Python mock transport; its dispatch remains reserved until the
connector submits a matching external receipt.

## Consequences

The database can now distinguish `sent`, `not_sent`, and `unknown` external
delivery results. Replaying an inbound Discord delivery cannot create a second
send when the connector journal contains the prior receipt. An unresolved
post-attempt crash is finalized as `unknown` for manual reconciliation.

The connector is not enabled by repository defaults. Discord account policy
risk remains an explicit operator responsibility, independent of the V2
technical authorization and receipt model.
