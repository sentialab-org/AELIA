"use strict";

const path = require("node:path");
const {
  loadTomlConfig,
  parseBoolean,
  parseCsv,
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
  const gate = tomlGate(projectConfig, "discord_selfbot");
  const runtime = tomlRuntime(projectConfig);
  if (Object.keys(gate).length > 0 && gate.enabled !== true) {
    throw new Error("Discord selfbot gate is disabled in config.toml");
  }
  const allowedChannelIds = parseIds(
    valueOr(env, "AELIA_DISCORD_ALLOWED_CHANNEL_IDS", gate.allowed_conversation_ids),
  );
  const allowAllChannels = allowedChannelIds.has(ALLOW_ALL_CHANNELS);
  const sendEnabled = parseBoolean(
    valueOr(env, "AELIA_DISCORD_SEND_ENABLED", gate.send_enabled),
    false,
  );

  if (allowedChannelIds.size === 0) {
    throw new Error("AELIA_DISCORD_ALLOWED_CHANNEL_IDS must not be empty");
  }
  if (allowAllChannels && allowedChannelIds.size !== 1) {
    throw new Error(
      "AELIA_DISCORD_ALLOWED_CHANNEL_IDS wildcard -1 must be used alone",
    );
  }
  if (!env.DISCORD_SELFBOT_TOKEN || !env.DISCORD_SELFBOT_TOKEN.trim()) {
    throw new Error("DISCORD_SELFBOT_TOKEN must not be empty");
  }

  const statePath = path.resolve(
    projectRoot,
    valueOr(
      env,
      "AELIA_DISCORD_STATE_PATH",
      gate.state_path,
      "data/discord-selfbot-journal.jsonl",
    ),
  );
  const requestTimeoutMs = parseInteger(
    valueOr(
      env,
      "AELIA_DISCORD_KERNEL_TIMEOUT_MS",
      gate.request_timeout_ms,
      180000,
    ),
    180000,
    1000,
    600000,
    "AELIA_DISCORD_KERNEL_TIMEOUT_MS",
  );
  const adapterMode = valueOr(
    env,
    "AELIA_DISCORD_ADAPTER_MODE",
    gate.mode,
    "shadow",
  );
  if (sendEnabled && adapterMode !== "external_canary") {
    throw new Error("Discord send-enabled gate requires external_canary mode");
  }

  return Object.freeze({
    adapterId: gate.adapter_id || "discord-selfbot-v2",
    connectorId: gate.adapter_id || "discord-selfbot-v2",
    token: env.DISCORD_SELFBOT_TOKEN.trim(),
    projectRoot,
    statePath,
    allowedChannelIds,
    allowedConversationIds: allowedChannelIds,
    allowAllChannels,
    allowedUserIds: parseIds(
      valueOr(env, "AELIA_DISCORD_ALLOWED_USER_IDS", gate.allowed_actor_ids),
    ),
    sendEnabled,
    adapterMode,
    runtimeUrl: valueOr(
      env,
      "AELIA_RUNTIME_URL",
      runtime.public_url,
      `http://${runtime.host || "127.0.0.1"}:${runtime.port || 8787}`,
    ),
    runtimeGateToken: env.AELIA_RUNTIME_GATE_TOKEN?.trim() || null,
    secretEnvKeys: ["DISCORD_SELFBOT_TOKEN"],
    connectorEnvPrefixes: ["AELIA_DISCORD_"],
    maxSendsPerHour: parseInteger(
      valueOr(env, "AELIA_DISCORD_MAX_SENDS_PER_HOUR", gate.max_sends_per_hour, 5),
      5,
      1,
      1000,
      "AELIA_DISCORD_MAX_SENDS_PER_HOUR",
    ),
    kernelTimeoutMs: requestTimeoutMs,
    requestTimeoutMs,
  });
}

function redactedConfigStatus(config) {
  return {
    adapter_id: config.adapterId,
    adapter_mode: config.adapterMode,
    runtime_url: config.runtimeUrl,
    allow_all_channels: config.allowAllChannels,
    allowed_channel_count: config.allowedChannelIds.size,
    allowed_user_count: config.allowedUserIds.size,
    send_enabled: config.sendEnabled,
    max_sends_per_hour: config.maxSendsPerHour,
    request_timeout_ms: config.requestTimeoutMs,
    discord_token_configured: Boolean(config.token),
    runtime_gate_token_configured: Boolean(config.runtimeGateToken),
  };
}

module.exports = {
  ALLOW_ALL_CHANNELS,
  loadConfig,
  parseBoolean,
  parseCsv,
  redactedConfigStatus,
};
