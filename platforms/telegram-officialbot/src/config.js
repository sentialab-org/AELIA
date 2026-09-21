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

function validateApiBase(value) {
  const parsed = new URL(value);
  if (parsed.protocol !== "https:" || parsed.username || parsed.password) {
    throw new Error("AELIA_TELEGRAM_API_BASE must be an HTTPS origin");
  }
  if (parsed.search || parsed.hash) {
    throw new Error("AELIA_TELEGRAM_API_BASE cannot include query or fragment");
  }
  return value.replace(/\/+$/, "");
}

function loadConfig(env = process.env) {
  const projectRoot = path.resolve(__dirname, "../../..");
  const useToml = env === process.env || env.AELIA_CONFIG_FILE;
  const projectConfig = useToml ? loadTomlConfig(projectRoot, env) : {};
  const gate = tomlGate(projectConfig, "telegram_officialbot");
  const runtime = tomlRuntime(projectConfig);
  if (Object.keys(gate).length > 0 && gate.enabled !== true) {
    throw new Error("Telegram official-bot gate is disabled in config.toml");
  }
  const allowedChatIds = parseIds(
    valueOr(env, "AELIA_TELEGRAM_ALLOWED_CHAT_IDS", gate.allowed_conversation_ids),
  );
  if (allowedChatIds.size === 0) {
    throw new Error("AELIA_TELEGRAM_ALLOWED_CHAT_IDS must not be empty");
  }
  if (!env.TELEGRAM_BOT_TOKEN?.trim()) {
    throw new Error("TELEGRAM_BOT_TOKEN must not be empty");
  }

  return Object.freeze({
    adapterId: gate.adapter_id || "telegram-officialbot-v2",
    connectorId: gate.adapter_id || "telegram-officialbot-v2",
    token: env.TELEGRAM_BOT_TOKEN.trim(),
    apiBase: validateApiBase(
      valueOr(
        env,
        "AELIA_TELEGRAM_API_BASE",
        gate.api_base,
        "https://api.telegram.org",
      ),
    ),
    projectRoot,
    statePath: path.resolve(
      projectRoot,
      valueOr(
        env,
        "AELIA_TELEGRAM_STATE_PATH",
        gate.state_path,
        "data/telegram-officialbot-journal.jsonl",
      ),
    ),
    allowedChatIds,
    allowedConversationIds: allowedChatIds,
    allowedUserIds: parseIds(
      valueOr(env, "AELIA_TELEGRAM_ALLOWED_USER_IDS", gate.allowed_actor_ids),
    ),
    sendEnabled: parseBoolean(
      valueOr(env, "AELIA_TELEGRAM_SEND_ENABLED", gate.send_enabled),
      false,
    ),
    adapterMode: valueOr(env, "AELIA_TELEGRAM_ADAPTER_MODE", gate.mode, "shadow"),
    runtimeUrl: valueOr(
      env,
      "AELIA_RUNTIME_URL",
      runtime.public_url,
      `http://${runtime.host || "127.0.0.1"}:${runtime.port || 8787}`,
    ),
    runtimeGateToken: env.AELIA_RUNTIME_GATE_TOKEN?.trim() || null,
    maxSendsPerHour: parseInteger(
      valueOr(env, "AELIA_TELEGRAM_MAX_SENDS_PER_HOUR", gate.max_sends_per_hour, 5),
      5,
      1,
      1000,
      "AELIA_TELEGRAM_MAX_SENDS_PER_HOUR",
    ),
    kernelTimeoutMs: parseInteger(
      valueOr(
        env,
        "AELIA_TELEGRAM_KERNEL_TIMEOUT_MS",
        gate.request_timeout_ms,
        180000,
      ),
      180000,
      1000,
      600000,
      "AELIA_TELEGRAM_KERNEL_TIMEOUT_MS",
    ),
    requestTimeoutMs: parseInteger(
      valueOr(
        env,
        "AELIA_TELEGRAM_KERNEL_TIMEOUT_MS",
        gate.request_timeout_ms,
        180000,
      ),
      180000,
      1000,
      600000,
      "AELIA_TELEGRAM_KERNEL_TIMEOUT_MS",
    ),
    pollTimeoutSeconds: parseInteger(
      valueOr(
        env,
        "AELIA_TELEGRAM_POLL_TIMEOUT_SECONDS",
        gate.poll_timeout_seconds,
        30,
      ),
      30,
      1,
      50,
      "AELIA_TELEGRAM_POLL_TIMEOUT_SECONDS",
    ),
    secretEnvKeys: ["TELEGRAM_BOT_TOKEN"],
    connectorEnvPrefixes: ["AELIA_TELEGRAM_"],
  });
}

module.exports = { loadConfig, validateApiBase };
