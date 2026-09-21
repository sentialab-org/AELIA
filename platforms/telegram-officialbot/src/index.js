"use strict";

const path = require("node:path");
const dotenv = require("dotenv");
const { DeliveryJournal } = require("../../node-common/journal");
const { RuntimeClient } = require("../../node-common/runtime-client");
const { TelegramBotApiClient } = require("./api-client");
const { loadConfig } = require("./config");
const { TelegramOfficialbotConnector } = require("./connector");
const { TelegramPollingRunner } = require("./polling");

const projectRoot = path.resolve(__dirname, "../../..");
dotenv.config({
  path:
    process.env.AELIA_TELEGRAM_ENV_FILE ||
    path.join(projectRoot, "platforms/telegram-officialbot/.env"),
  quiet: true,
});

async function main() {
  const config = loadConfig();
  const runtime = new RuntimeClient(config);
  await runtime.health();
  console.info(
    JSON.stringify({
      event: "telegram_officialbot_runtime_connected",
      runtime_url: config.runtimeUrl,
    }),
  );
  const api = new TelegramBotApiClient(config);
  const bot = await api.getMe();
  const journal = new DeliveryJournal(config.statePath);
  const connector = new TelegramOfficialbotConnector({
    api,
    bot,
    config,
    journal,
    kernel: runtime,
  });
  const runner = new TelegramPollingRunner({
    api,
    connector,
    journal,
    timeoutSeconds: config.pollTimeoutSeconds,
  });

  console.info(
    JSON.stringify({
      event: "telegram_officialbot_ready",
      account_id: bot.id,
      send_enabled: config.sendEnabled,
      allowlisted_chats: config.allowedChatIds.size,
    }),
  );

  const shutdown = (signal) => {
    console.info(JSON.stringify({ event: "telegram_officialbot_shutdown", signal }));
    runner.stop();
  };
  process.once("SIGINT", () => shutdown("SIGINT"));
  process.once("SIGTERM", () => shutdown("SIGTERM"));
  await runner.run();
}

main().catch((error) => {
  console.error(
    JSON.stringify({
      event: "telegram_officialbot_start_failed",
      error_type: error?.constructor?.name || "Error",
    }),
  );
  process.exit(1);
});
