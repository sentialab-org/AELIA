"use strict";

const path = require("node:path");
const dotenv = require("dotenv");
const { loadConfig, redactedConfigStatus } = require("./config");

function resolveEnvFile(env, projectRoot) {
  return (
    env.AELIA_DISCORD_ENV_FILE ||
    path.join(projectRoot, "platforms/discord-selfbot/.env")
  );
}

function loadEffectiveConfigStatus(env = process.env) {
  const projectRoot = path.resolve(__dirname, "../../..");
  dotenv.config({
    path: resolveEnvFile(env, projectRoot),
    processEnv: env,
    quiet: true,
  });
  return redactedConfigStatus(loadConfig(env));
}

if (require.main === module) {
  console.info(
    JSON.stringify({
      event: "discord_selfbot_config",
      config: loadEffectiveConfigStatus(),
    }),
  );
}

module.exports = { loadEffectiveConfigStatus, resolveEnvFile };
