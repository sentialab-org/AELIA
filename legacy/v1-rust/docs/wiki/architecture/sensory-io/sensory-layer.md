---
title: Sensory Layer
summary: How platform adapters ingest messages and bridge external APIs to the event bus.
order: 21
---

# Sensory Layer

The sensory layer (`libs/sensory`) is the outer boundary of the agent. It converts platform-specific traffic into normalized `RawEvent`s, and it sends `ResponseEvent`s back through the platform relay when responses need to leave the runtime.

It contains no cognitive logic. It does not decide what the agent should think or say; it only knows how to move data between the runtime and the outside world.

## Platform adapters

The current platform adapters are split across the workspace so each surface can evolve independently:

### `DiscordWorker`

`platforms/discord` uses the `serenity` crate to connect to Discord as an official bot account.

- it filters out messages from other bots to avoid feedback loops
- it detects bot mentions from the message mention list
- it downloads image attachments and forwards them as `ImageAttachment`s when possible

### `TelegramWorker`

`platforms/telegram` uses `teloxide` to connect to the Telegram Bot API.

- it maps Telegram chat IDs into the shared `channel_id` field
- it treats direct messages as mentions so the dialogue layer can prioritize them
- it resolves image and document attachments into the same shared attachment format

### Discord selfbot runner

`platforms/discord-selfbot` is a separate runner that starts the Node.js selfbot helper under `platforms/discord-selfbot/nodejs-selfbot/`.

- the Rust wrapper handles process lifecycle and shutdown
- the Node.js helper talks to Discord as a user account
- both sides use the same platform relay socket as the other platform binaries

## The platform relay

The sensory layer now uses a Unix-domain socket relay for platform ingress and egress. For the wire format and socket behavior, see [Platform Relay](../../local-interfaces/platform-relay.md).

At runtime:

- platform binaries connect through `RelayClient`
- inbound platform messages are normalized into `RawEvent`
- outbound responses are routed by `ResponseEvent.platform`
- the relay keeps Discord, Discord selfbot, and Telegram responses isolated from one another

The default socket path is `/tmp/polyverse-agent-relay.sock`, and it can be overridden with `PLATFORM_RELAY_SOCKET`.

## The `SensoryBuffer`

When a message arrives from any adapter, it passes through `SensoryBuffer` before it reaches the main event bus.

Historically this layer managed rate-limiting and typing indicators. In the current implementation, typing detection is intentionally removed and the buffer forwards `RawEvent`s immediately. That keeps the coordinator and dialogue engine responsive when messages arrive in bursts.

## Egress routing

All platform runners subscribe to the shared broadcast stream and look for `Event::Response`.

When a response arrives, the runner checks the `platform` field and only forwards events that match its own platform.

That means a Discord response is not accidentally sent to Telegram, and vice versa.

