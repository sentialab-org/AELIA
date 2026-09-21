"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  TelegramApiError,
  TelegramBotApiClient,
} = require("../src/api-client");

function response(body, status = 200) {
  const raw = Buffer.from(JSON.stringify(body));
  return {
    ok: status >= 200 && status < 300,
    status,
    async arrayBuffer() {
      return raw;
    },
  };
}

test("Telegram API client returns sendMessage result", async () => {
  let seenUrl = "";
  let seenBody = null;
  const api = new TelegramBotApiClient({
    token: "secret-token",
    apiBase: "https://api.telegram.test",
    fetchImpl: async (url, options) => {
      seenUrl = url;
      seenBody = JSON.parse(options.body);
      return response({ ok: true, result: { message_id: 7 } });
    },
  });

  const result = await api.sendMessage({ chat_id: "42", text: "hello" });

  assert.equal(result.message_id, 7);
  assert.match(seenUrl, /sendMessage$/);
  assert.deepEqual(seenBody, { chat_id: "42", text: "hello" });
});

test("Telegram API rejection is classified as definitely not sent", async () => {
  const api = new TelegramBotApiClient({
    token: "secret-token",
    apiBase: "https://api.telegram.test",
    fetchImpl: async () =>
      response({ ok: false, error_code: 403, description: "forbidden" }, 403),
  });

  await assert.rejects(
    () => api.sendMessage({ chat_id: "42", text: "hello" }),
    (error) =>
      error instanceof TelegramApiError &&
      error.code === "telegram_api_403" &&
      error.deliveryStatus === "not_sent",
  );
});
