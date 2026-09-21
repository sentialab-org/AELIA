# ADR 0016: Official Discord and Telegram Node connectors

- Status: Accepted
- Date: 2026-07-30

## Context

The platform layer must support both the owner-selected Discord self-bot and
official platform account models without importing SDK types into the Python
kernel. All connectors must produce the same V2 inbound envelope, consume the
same outbound command, and finalize the same external receipt contract.

## Decision

Add two isolated Node.js processes:

- `platforms/discord-officialbot` uses a Discord application bot account and
  `discord.js` v14;
- `platforms/telegram-officialbot` uses Telegram's HTTPS Bot API directly.

All three Node connectors share platform-neutral journal, kernel-client, config
parsing, and receipt helpers under `platforms/node-common`. Each connector still
owns its platform SDK/API mapping and credential.

Discord official bot:

- requests Guild, GuildMessages, DirectMessages, and MessageContent intents;
- ignores messages authored by bots;
- checks current channel send permission;
- supplies a deterministic nonce with `enforceNonce`; and
- observes Discord REST rate-limit events.

Telegram official bot:

- uses `getUpdates` long polling and persists `update_id + 1` only after the
  update has been processed;
- preserves reply and message-thread targets;
- checks current bot membership/send permission;
- uses `sendMessage` without implicit formatting;
- classifies explicit Bot API rejections as `not_sent`; and
- classifies transport ambiguity after invocation as `unknown`.

Every connector requires a conversation allowlist, optional actor allowlist,
bounded send rate, default-off kill switch, fsynced attempt journal, and
external receipt `2.0.0`.

## Consequences

The Python adapter boundary remains unchanged and platform-neutral. Operators
can choose one account model without enabling another. Credentials and local
state remain in separate ignored files. No connector is started by the kernel
or enabled by repository defaults.
