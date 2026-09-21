# Discord self-bot connector

This is an isolated Node.js platform gate for Polyverse V2. It normalizes Discord
events and delivers Discord commands, while the independent Python runtime
backend owns cognition, memory, model calls, persistence, and the outbox.

The connector pins `discord.js-selfbot-v13` `3.7.1` and requires Node.js
`>=20.18`, matching the package's runtime requirement.

The connector authenticates a normal Discord user account. Discord prohibits
self-bots and may terminate that account. The repository therefore never starts
this process implicitly and never stores the credential in tracked files.

## Safety and delivery semantics

- inbound and outbound traffic require an explicit channel allowlist, or the
  explicit `-1` wildcard to accept every visible channel;
- an optional actor allowlist is applied before the kernel is invoked;
- `send_enabled = false` in `config.toml` is the default kill switch;
- dry-run uses the backend gate policy in `shadow` mode;
- enabled delivery uses the backend gate policy in `external_canary` mode;
- the Python outbox queues a command without claiming a side effect;
- the Node journal is fsynced before a send attempt and stores no message body;
- a completed Discord send is finalized with external receipt schema `2.0.0`;
- an interrupted attempt is marked `unknown` and is never blindly retried;
- duplicate inbound delivery reconciles the prior receipt instead of sending
  another message.

## Install and test

```bash
cd platforms/discord-selfbot
npm ci
npm run check
npm test
```

Print the effective gate settings without exposing either Discord or runtime-gate
credentials:

```bash
npm run config:doctor
```

The report includes only operational values and `*_configured` booleans. It uses
the same platform `.env` loading path as the running connector.

## Inbound lifecycle and replies

Each Discord `messageCreate` event emits a `discord_selfbot_message_received`
record immediately, followed by a `discord_selfbot_message_processed` or
`discord_selfbot_message_failed` record with the same message, channel, and
author identifiers. Message bodies and credentials are never written to these
records. `queued: true` means the message is waiting behind earlier work for
that Discord channel. A `queued: false` message can still wait later for the
backend’s single-persona processing lane.

Messages written by the logged-in Discord account are intentionally reported as
`ignored` with `reason: "self_author"`; the connector never sends them to the
backend because accepting its own sends would create a reply loop. An event that
arrives before the Discord client exposes its account is reported as
`client_not_ready`. Channel and actor filters are likewise reported as
`channel_not_allowed` and `actor_not_allowed`.

A processed inbound message is not necessarily a Discord reply. The runtime can
complete a cycle as `observe` or `wait`, which appears as `outcome: "no_action"`
in the gate log. An actual Discord send requires the runtime to select an action
and return `queue_external_canary`, after which the connector records its
external delivery receipt. The terminal connector record reports `cycle_status`
only; inspect the backend’s `runtime_gate_ingress_processed` record and
persisted cycle trace for the participation decision and reason codes.

To test the complete path, send from a different Discord account in an allowed
channel. A direct mention or reply to the persona is more likely to pass the
runtime’s participation threshold than ambient conversation, but the persona
policy remains the final decision-maker.


The capability manifest can be checked without a Discord credential:

```bash
uv run polyverse adapter connector-preflight \
  platforms/discord-selfbot/capabilities.json
```

## Configure

Keep normal LLM/backend/gate configuration in ignored root `config.toml` and
keep only the selfbot credential in the separate ignored platform file:

```bash
cp platforms/discord-selfbot/.env.example \
  platforms/discord-selfbot/.env
chmod 600 platforms/discord-selfbot/.env
```

At minimum set:

```text
DISCORD_SELFBOT_TOKEN=<user token>
```

Set the allowlist and send switch in `config.toml`, not this file.

To accept messages from every channel visible to the Discord account, use the
wildcard by itself:

```toml
[platforms.discord_selfbot]
allowed_conversation_ids = ["-1"]
```

`-1` cannot be combined with channel IDs. In wildcard mode, the backend scopes
the policy to the current inbound channel for each request. The optional user
allowlist remains active.

Start in dry-run:

```bash
make backend                         # terminal 1
make discord-selfbot-run             # terminal 2
```

Only change `send_enabled = true` together with `mode = "external_canary"` in
`config.toml` for an intentional external canary. Restart the backend and gate
after changing configuration.

## Rollback

Set `send_enabled = false` and `mode = "shadow"` in `config.toml`, then restart
the backend and Node gate. Existing kernel cycles, queued/finalized dispatches,
receipts, and the connector journal remain intact for inspection.
