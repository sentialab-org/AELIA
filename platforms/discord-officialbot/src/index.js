"use strict";

const path = require("node:path");
const dotenv = require("dotenv");
const {
  Client,
  GatewayIntentBits,
  Partials,
} = require("discord.js");
const { DeliveryJournal } = require("../../node-common/journal");
const { RuntimeClient } = require("../../node-common/runtime-client");
const { loadConfig } = require("./config");
const { DiscordOfficialbotConnector } = require("./connector");

const projectRoot = path.resolve(__dirname, "../../..");
dotenv.config({
  path:
    process.env.POLYVERSE_DISCORD_OFFICIAL_ENV_FILE ||
    path.join(projectRoot, "platforms/discord-officialbot/.env"),
  quiet: true,
});

const config = loadConfig();
const runtime = new RuntimeClient(config);
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.DirectMessages,
    GatewayIntentBits.MessageContent,
  ],
  partials: [Partials.Channel],
});
const connector = new DiscordOfficialbotConnector({
  client,
  config,
  journal: new DeliveryJournal(config.statePath),
  kernel: runtime,
});

client.on("clientReady", () => {
  console.info(
    JSON.stringify({
      event: "discord_officialbot_ready",
      account_id: client.user.id,
      send_enabled: config.sendEnabled,
      allowlisted_channels: config.allowedChannelIds.size,
    }),
  );
});
client.on("messageCreate", (message) => {
  connector
    .enqueue(message)
    .then((result) => {
      if (result.outcome !== "ignored") {
        console.info(
          JSON.stringify({
            event: "discord_officialbot_message_processed",
            outcome: result.outcome,
          }),
        );
      }
    })
    .catch((error) => {
      console.error(
        JSON.stringify({
          event: "discord_officialbot_message_failed",
          error_type: error?.constructor?.name || "Error",
          error_code: error?.code || null,
        }),
      );
    });
});
client.rest.on("rateLimited", (info) => {
  console.warn(
    JSON.stringify({
      event: "discord_officialbot_rate_limited",
      global: Boolean(info.global),
      time_to_reset_ms: info.timeToReset,
    }),
  );
});

function shutdown(signal) {
  console.info(JSON.stringify({ event: "discord_officialbot_shutdown", signal }));
  client.destroy();
  process.exit(0);
}
process.once("SIGINT", () => shutdown("SIGINT"));
process.once("SIGTERM", () => shutdown("SIGTERM"));

async function start() {
  await runtime.health();
  console.info(
    JSON.stringify({
      event: "discord_officialbot_runtime_connected",
      runtime_url: config.runtimeUrl,
    }),
  );
  await client.login(config.token);
}

start().catch((error) => {
  console.error(
    JSON.stringify({
      event: "discord_officialbot_start_failed",
      error_type: error?.constructor?.name || "Error",
      error_code: error?.code || null,
    }),
  );
  process.exit(1);
});
