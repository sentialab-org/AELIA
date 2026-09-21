# Discord official bot connector

Node.js connector for a Discord application bot account. It uses `discord.js`
v14, receives Gateway `messageCreate` events, and sends only through the V2
`external_canary` outbox.

## Configure

Enable the Message Content intent in the Discord Developer Portal, copy
`.env.example` to the ignored `.env`, then set only the bot token. Put the
allowlist and delivery policy in root `config.toml`. Delivery remains disabled
until the gate is configured for:

```text
mode = "external_canary"
send_enabled = true
```

## Verify and run

```bash
npm --prefix platforms/discord-officialbot ci
npm --prefix platforms/discord-officialbot run check
npm --prefix platforms/discord-officialbot test
uv run aelia adapter connector-preflight \
  platforms/discord-officialbot/capabilities.json
make backend
make discord-officialbot-run
```

The connector ignores other bot accounts, checks channel permissions, uses a
deterministic Discord nonce with `enforceNonce`, persists delivery attempts
before sending, and finalizes command receipt `2.0.0`.
