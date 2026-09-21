"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadConfig } = require("../src/config");

test("official Discord bot config defaults to dry-run", () => {
  const config = loadConfig({
    DISCORD_BOT_TOKEN: "test-token",
    POLYVERSE_DISCORD_OFFICIAL_ALLOWED_CHANNEL_IDS: "channel-1",
  });

  assert.equal(config.sendEnabled, false);
  assert.deepEqual([...config.allowedConversationIds], ["channel-1"]);
  assert.deepEqual(config.secretEnvKeys, ["DISCORD_BOT_TOKEN"]);
});

test("official Discord bot config requires a token and allowlist", () => {
  assert.throws(
    () => loadConfig({ DISCORD_BOT_TOKEN: "test-token" }),
    /ALLOWED_CHANNEL_IDS/,
  );
  assert.throws(
    () =>
      loadConfig({
        POLYVERSE_DISCORD_OFFICIAL_ALLOWED_CHANNEL_IDS: "channel-1",
      }),
    /DISCORD_BOT_TOKEN/,
  );
});

test("official Discord bot config accepts an exclusive all-channel wildcard", () => {
  const config = loadConfig({
    DISCORD_BOT_TOKEN: "test-token",
    POLYVERSE_DISCORD_OFFICIAL_ALLOWED_CHANNEL_IDS: "-1",
  });

  assert.equal(config.allowAllChannels, true);
  assert.throws(
    () =>
      loadConfig({
        DISCORD_BOT_TOKEN: "test-token",
        POLYVERSE_DISCORD_OFFICIAL_ALLOWED_CHANNEL_IDS: "-1,channel-1",
      }),
    /wildcard -1 must be used alone/,
  );
});
