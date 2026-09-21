"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createExternalReceipt,
  normalizeTelegramUpdate,
  parseTelegramEventId,
} = require("../src/contracts");

test("Telegram update maps to a versioned V2 envelope", () => {
  const envelope = normalizeTelegramUpdate(
    {
      update_id: 10,
      message: {
        message_id: 20,
        date: 1785369600,
        chat: { id: -1001, type: "supergroup" },
        from: { id: 30, is_bot: false },
        text: "hello @AeliaBot",
        entities: [{ type: "mention", offset: 6, length: 9 }],
      },
    },
    {
      adapterId: "telegram-officialbot-v2",
      bot: { id: 99, username: "AeliaBot" },
      receivedAt: "2026-07-30T00:00:01Z",
    },
  );

  assert.equal(envelope.event.platform, "telegram");
  assert.equal(envelope.event.conversation_id, "-1001");
  assert.equal(envelope.event.event_id, "telegram:-1001:20");
  assert.deepEqual(envelope.event.mentions, ["99"]);
  assert.deepEqual(parseTelegramEventId(envelope.event.event_id), {
    chatId: "-1001",
    messageId: "20",
  });
});

test("Telegram external receipt uses platform telegram", () => {
  const receipt = createExternalReceipt({
    command: { command_id: "command-1", idempotency_key: "key-1" },
    connectorId: "telegram-officialbot-v2",
    status: "sent",
    platformMessageId: "21",
  });

  assert.equal(receipt.platform, "telegram");
  assert.equal(receipt.status, "sent");
});
