# Telegram official bot connector

Node.js connector that talks directly to Telegram's HTTPS Bot API. It uses
`getUpdates` long polling, persists `update_id + 1` only after processing, and
sends text through `sendMessage`.

## Configure

Create a bot with BotFather, copy `.env.example` to the ignored `.env`, then set
only the bot token. Put the chat allowlist and delivery policy in root
`config.toml`. Delivery stays disabled until the gate is configured for:

```text
mode = "external_canary"
send_enabled = true
```

## Verify and run

```bash
npm --prefix platforms/telegram-officialbot ci
npm --prefix platforms/telegram-officialbot run check
npm --prefix platforms/telegram-officialbot test
uv run polyverse adapter connector-preflight \
  platforms/telegram-officialbot/capabilities.json
make backend
make telegram-officialbot-run
```

The connector preserves topic and reply targeting, checks current bot
membership/permissions, records Bot API rejections as `not_sent`, records
ambiguous transport failures as `unknown`, and never logs its token.
