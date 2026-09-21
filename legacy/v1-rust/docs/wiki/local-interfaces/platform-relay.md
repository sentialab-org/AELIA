---
title: Platform Relay
summary: Unix-domain socket bridge between the core runtime and platform runners.
order: 31
---

# Platform Relay

The platform relay is the local Unix-domain socket boundary that keeps platform-specific SDKs and process models out of the core runtime.

It lives in `libs/sensory::relay::PlatformRelayWorker` and is used by the platform binaries under `platforms/` through `sensory::relay::RelayClient`.

## Socket and framing

By default the relay listens on:

```text
/tmp/polyverse-agent-relay.sock
```

You can override the socket path with `PLATFORM_RELAY_SOCKET`.

The wire format is length-prefixed JSON:

1. `u32` little-endian payload length
2. JSON bytes

### Messages from platform to agent

- `PlatformMessage::Ping` keeps the socket alive.
- `PlatformMessage::Ingest { event }` forwards a `RawEvent` into the runtime event bus.

### Messages from agent to platform

- `AgentMessage::Ack` confirms receipt of an ingest frame.
- `AgentMessage::Pong` replies to a ping.
- `AgentMessage::Response { event }` forwards a `ResponseEvent` back to the platform runner.

## Routing behavior

The relay accepts multiple connections, but each connection is bound to the platform detected from its first ingest frame.

That means:

- the relay only forwards responses whose `ResponseEvent.platform` matches the platform for that connection
- `Discord`, `DiscordSelfbot`, and `Telegram` traffic stay isolated from one another
- the socket can be restarted independently of the core runtime

On startup the relay removes any stale socket file before binding.

## Who uses it

- `platforms/discord`
- `platforms/telegram`
- `platforms/discord-selfbot`

The same client can also be used by any future local platform runner that wants to exchange `RawEvent` and `ResponseEvent` frames with the agent.

## Why it exists

The relay gives the platform layer a stable contract:

- platform SDKs stay in their own binaries
- the core runtime only sees normalized events
- response delivery remains platform-aware without coupling the runtime to Discord or Telegram APIs

