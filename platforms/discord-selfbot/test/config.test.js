"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadConfig, redactedConfigStatus } = require("../src/config");

test("configuration is dry-run by default and requires a channel allowlist", () => {
  const config = loadConfig({
    DISCORD_SELFBOT_TOKEN: "test-token",
    AELIA_DISCORD_ALLOWED_CHANNEL_IDS: "channel-1, channel-2",
  });

  assert.equal(config.sendEnabled, false);
  assert.equal(config.allowAllChannels, false);
  assert.deepEqual([...config.allowedChannelIds], ["channel-1", "channel-2"]);
  assert.throws(
    () => loadConfig({ DISCORD_SELFBOT_TOKEN: "test-token" }),
    /ALLOWED_CHANNEL_IDS/,
  );
});

test("channel allowlist accepts -1 as an exclusive all-channel wildcard", () => {
  const config = loadConfig({
    DISCORD_SELFBOT_TOKEN: "test-token",
    AELIA_DISCORD_ALLOWED_CHANNEL_IDS: "-1",
  });

  assert.equal(config.allowAllChannels, true);
  assert.deepEqual([...config.allowedChannelIds], ["-1"]);
  assert.throws(
    () =>
      loadConfig({
        DISCORD_SELFBOT_TOKEN: "test-token",
        AELIA_DISCORD_ALLOWED_CHANNEL_IDS: "-1,channel-1",
      }),
    /wildcard -1 must be used alone/,
  );
});

test("send kill switch accepts only explicit booleans", () => {
  assert.throws(
    () =>
      loadConfig({
        DISCORD_SELFBOT_TOKEN: "test-token",
        AELIA_DISCORD_ALLOWED_CHANNEL_IDS: "channel-1",
        AELIA_DISCORD_SEND_ENABLED: "yes",
      }),
    /Expected true or false/,
  );
});

test("redacted configuration status reports operational settings without secrets", () => {
  const token = "test-discord-token";
  const runtimeToken = "test-runtime-token";
  const config = loadConfig({
    DISCORD_SELFBOT_TOKEN: token,
    AELIA_RUNTIME_GATE_TOKEN: runtimeToken,
    AELIA_DISCORD_ALLOWED_CHANNEL_IDS: "channel-1",
    AELIA_DISCORD_SEND_ENABLED: "true",
    AELIA_DISCORD_ADAPTER_MODE: "external_canary",
  });

  const status = redactedConfigStatus(config);

  assert.deepEqual(status, {
    adapter_id: "discord-selfbot-v2",
    adapter_mode: "external_canary",
    runtime_url: "http://127.0.0.1:8787",
    allow_all_channels: false,
    allowed_channel_count: 1,
    allowed_user_count: 0,
    send_enabled: true,
    max_sends_per_hour: 5,
    request_timeout_ms: 180000,
    discord_token_configured: true,
    runtime_gate_token_configured: true,
  });
  assert.equal(JSON.stringify(status).includes(token), false);
  assert.equal(JSON.stringify(status).includes(runtimeToken), false);
});
