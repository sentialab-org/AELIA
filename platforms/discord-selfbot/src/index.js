"use strict";

const path = require("node:path");
const dotenv = require("dotenv");
const { Client } = require("discord.js-selfbot-v13");
const { loadConfig } = require("./config");
const { DiscordSelfbotConnector } = require("./connector");
const { DeliveryJournal } = require("./journal");
const { RuntimeClient } = require("../../node-common/runtime-client");

const projectRoot = path.resolve(__dirname, "../../..");
const envFile =
  process.env.AELIA_DISCORD_ENV_FILE ||
  path.join(projectRoot, "platforms/discord-selfbot/.env");
dotenv.config({ path: envFile, quiet: true });

const config = loadConfig();
const client = new Client({ checkUpdate: false });
const runtime = new RuntimeClient(config);
const connector = new DiscordSelfbotConnector({
  client,
  config,
  journal: new DeliveryJournal(config.statePath),
  kernel: runtime,
});

client.on("ready", () => {
  console.info(
    JSON.stringify({
      event: "discord_selfbot_ready",
      account_id: client.user.id,
      send_enabled: config.sendEnabled,
      allowlisted_channels: config.allowedChannelIds.size,
      allow_all_channels: config.allowAllChannels,
    }),
  );
});

client.on("messageCreate", (message) => {
  const eventContext = {
    message_id: String(message.id),
    channel_id: String(message.channelId),
    author_id: message.author?.id ? String(message.author.id) : null,
  };
  const { queued, completion } = connector.enqueueWithStatus(message);
  console.info(
    JSON.stringify({
      event: "discord_selfbot_message_received",
      ...eventContext,
      queued,
    }),
  );
  completion
    .then((result) => {
      console.info(
        JSON.stringify({
          event: "discord_selfbot_message_processed",
          ...eventContext,
          outcome: result.outcome,
          reason: result.reason || null,
          cycle_status: result.cycleStatus || null,
        }),
      );
    })
    .catch((error) => {
      console.error(
        JSON.stringify({
          event: "discord_selfbot_message_failed",
          ...eventContext,
          error_type: error?.constructor?.name || "Error",
          error_code: error?.code || null,
        }),
      );
    });
});

client.on("error", (error) => {
  console.error(
    JSON.stringify({
      event: "discord_selfbot_client_error",
      error_type: error?.constructor?.name || "Error",
    }),
  );
});

async function shutdown(signal) {
  console.info(JSON.stringify({ event: "discord_selfbot_shutdown", signal }));
  client.destroy();
  process.exit(0);
}

process.once("SIGINT", () => void shutdown("SIGINT"));
process.once("SIGTERM", () => void shutdown("SIGTERM"));

async function start() {
  await runtime.health();
  console.info(
    JSON.stringify({
      event: "discord_selfbot_runtime_connected",
      runtime_url: config.runtimeUrl,
    }),
  );
  await client.login(config.token);
}

start().catch((error) => {
  console.error(
    JSON.stringify({
      event: "discord_selfbot_start_failed",
      error_type: error?.constructor?.name || "Error",
      error_code: error?.code || null,
    }),
  );
  process.exit(1);
});
