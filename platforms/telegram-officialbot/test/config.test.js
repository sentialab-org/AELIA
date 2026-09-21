"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadConfig, validateApiBase } = require("../src/config");

test("Telegram bot config defaults to dry-run and HTTPS Bot API", () => {
  const config = loadConfig({
    TELEGRAM_BOT_TOKEN: "test-token",
    POLYVERSE_TELEGRAM_ALLOWED_CHAT_IDS: "-1001,42",
  });

  assert.equal(config.sendEnabled, false);
  assert.equal(config.apiBase, "https://api.telegram.org");
  assert.deepEqual([...config.allowedConversationIds], ["-1001", "42"]);
});

test("Telegram Bot API base rejects credentials and plain HTTP", () => {
  assert.throws(() => validateApiBase("http://api.telegram.org"), /HTTPS origin/);
  assert.throws(
    () => validateApiBase("https://user:pass@api.telegram.org"),
    /HTTPS origin/,
  );
});
