"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { DeliveryJournal } = require("../../node-common/journal");
const { TelegramOfficialbotConnector } = require("../src/connector");

function fixture() {
  const sends = [];
  const receipts = [];
  const update = {
    update_id: 10,
    message: {
      message_id: 20,
      message_thread_id: 3,
      date: 1785369600,
      chat: { id: -1001, type: "supergroup" },
      from: { id: 30, is_bot: false },
      text: "hello",
    },
  };
  const command = {
    command_id: "command-1",
    idempotency_key: "key-1",
    platform: "telegram",
    action_type: "reply",
    target_conversation_id: "-1001",
    reply_to_event_id: "telegram:-1001:20",
    content: "reply",
  };
  const api = {
    async canSend() {
      return true;
    },
    async sendMessage(payload) {
      sends.push(payload);
      return { message_id: 21 };
    },
  };
  const kernel = {
    async ingest() {
      return {
        dispatch: {
          decision: { outcome: "queue_external_canary" },
          command,
        },
      };
    },
    async recordExternalReceipt(receipt) {
      receipts.push(receipt);
    },
  };
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "telegram-bot-test-"));
  const connector = new TelegramOfficialbotConnector({
    api,
    bot: { id: 99, username: "PolyverseBot" },
    config: {
      adapterId: "telegram-officialbot-v2",
      connectorId: "telegram-officialbot-v2",
      sendEnabled: true,
      allowedChatIds: new Set(["-1001"]),
      allowedUserIds: new Set(),
    },
    journal: new DeliveryJournal(path.join(directory, "journal.jsonl")),
    kernel,
    logger: { error() {} },
  });
  return { connector, receipts, sends, update };
}

test("Telegram connector sends once and preserves reply/thread targeting", async () => {
  const { connector, receipts, sends, update } = fixture();

  const first = await connector.handleUpdate(update);
  const duplicate = await connector.handleUpdate(update);

  assert.equal(first.outcome, "sent");
  assert.equal(duplicate.outcome, "reconciled");
  assert.equal(sends.length, 1);
  assert.equal(sends[0].message_thread_id, 3);
  assert.deepEqual(sends[0].reply_parameters, {
    message_id: 20,
    allow_sending_without_reply: false,
  });
  assert.equal(receipts.length, 2);
});

test("Telegram connector ignores non-allowlisted chats", async () => {
  const { connector, update } = fixture();
  update.message.chat.id = 999;

  assert.deepEqual(await connector.handleUpdate(update), { outcome: "ignored" });
});
