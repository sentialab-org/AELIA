"use strict";

const path = require("node:path");
const {
  loadTomlConfig,
  parseBoolean,
  parseIds,
  parseInteger,
  tomlGate,
  tomlRuntime,
  valueOr,
} = require("../../node-common/config");

const ALLOW_ALL_CHANNELS = "-1";

function loadConfig(env = process.env) {
  const projectRoot = path.resolve(__dirname, "../../..");
  const useToml = env === process.env || env.AELIA_CONFIG_FILE;
  const projectConfig = useToml ? loadTomlConfig(projectRoot, env) : {};
  const gate = tomlGate(projectConfig, "discord_officialbot");
  const runtime = tomlRuntime(projectConfig);
  if (Object.keys(gate).length > 0 && gate.enabled !== true) {
    throw new Error("Discord official-bot gate is disabled in config.toml");
  }
  const allowedChannelIds = parseIds(
    valueOr(
      env,
      "AELIA_DISCORD_OFFICIAL_ALLOWED_CHANNEL_IDS",
      gate.allowed_conversation_ids,
    ),
  );
  if (allowedChannelIds.size === 0) {
    throw new Error("AELIA_DISCORD_OFFICIAL_ALLOWED_CHANNEL_IDS must not be empty");
  }
  const allowAllChannels = allowedChannelIds.has(ALLOW_ALL_CHANNELS);
  if (allowAllChannels && allowedChannelIds.size !== 1) {
    throw new Error(
      "AELIA_DISCORD_OFFICIAL_ALLOWED_CHANNEL_IDS wildcard -1 must be used alone",
    );
  }
  if (!env.DISCORD_BOT_TOKEN?.trim()) {
    throw new Error("DISCORD_BOT_TOKEN must not be empty");
  }

  return Object.freeze({
    adapterId: gate.adapter_id || "discord-officialbot-v2",
    connectorId: gate.adapter_id || "discord-officialbot-v2",
    token: env.DISCORD_BOT_TOKEN.trim(),
    projectRoot,
    statePath: path.resolve(
      projectRoot,
      valueOr(
        env,
        "AELIA_DISCORD_OFFICIAL_STATE_PATH",
        gate.state_path,
        "data/discord-officialbot-journal.jsonl",
      ),
    ),
    allowedChannelIds,
    allowedConversationIds: allowedChannelIds,
    allowAllChannels,
    allowedUserIds: parseIds(
      valueOr(env, "AELIA_DISCORD_OFFICIAL_ALLOWED_USER_IDS", gate.allowed_actor_ids),
    ),
    sendEnabled: parseBoolean(
      valueOr(env, "AELIA_DISCORD_OFFICIAL_SEND_ENABLED", gate.send_enabled),
      false,
    ),
    adapterMode: valueOr(
      env,
      "AELIA_DISCORD_OFFICIAL_ADAPTER_MODE",
      gate.mode,
      "shadow",
    ),
    runtimeUrl: valueOr(
      env,
      "AELIA_RUNTIME_URL",
      runtime.public_url,
      `http://${runtime.host || "127.0.0.1"}:${runtime.port || 8787}`,
    ),
    runtimeGateToken: env.AELIA_RUNTIME_GATE_TOKEN?.trim() || null,
    maxSendsPerHour: parseInteger(
      valueOr(
        env,
        "AELIA_DISCORD_OFFICIAL_MAX_SENDS_PER_HOUR",
        gate.max_sends_per_hour,
        5,
      ),
      5,
      1,
      1000,
      "AELIA_DISCORD_OFFICIAL_MAX_SENDS_PER_HOUR",
    ),
    kernelTimeoutMs: parseInteger(
      valueOr(
        env,
        "AELIA_DISCORD_OFFICIAL_KERNEL_TIMEOUT_MS",
        gate.request_timeout_ms,
        180000,
      ),
      180000,
      1000,
      600000,
      "AELIA_DISCORD_OFFICIAL_KERNEL_TIMEOUT_MS",
    ),
    secretEnvKeys: ["DISCORD_BOT_TOKEN"],
    requestTimeoutMs: parseInteger(
      valueOr(
        env,
        "AELIA_DISCORD_OFFICIAL_KERNEL_TIMEOUT_MS",
        gate.request_timeout_ms,
        180000,
      ),
      180000,
      1000,
      600000,
      "AELIA_DISCORD_OFFICIAL_KERNEL_TIMEOUT_MS",
    ),
    connectorEnvPrefixes: ["AELIA_DISCORD_OFFICIAL_"],
  });
}

module.exports = { ALLOW_ALL_CHANNELS, loadConfig };
