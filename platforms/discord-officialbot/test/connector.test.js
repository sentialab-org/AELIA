"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { DeliveryJournal } = require("../../node-common/journal");
const {
  DiscordOfficialbotConnector,
  commandNonce,
} = require("../src/connector");

function fixture() {
  const sends = [];
  const receipts = [];
  const sourceMessage = {
    id: "message-1",
    channelId: "channel-1",
    guildId: "guild-1",
    content: "hello",
    createdAt: new Date("2026-07-30T00:00:00Z"),
    author: { id: "user-1", bot: false },
    channel: { send() {} },
    mentions: { users: new Map() },
    attachments: new Map(),
    reply(payload) {
      sends.push(payload);
      return Promise.resolve({ id: "sent-1" });
    },
  };
  const command = {
    command_id: "command-1",
    idempotency_key: "key-1",
    platform: "discord",
    action_type: "reply",
    target_conversation_id: "channel-1",
    reply_to_event_id: "discord:message-1",
    content: "reply",
  };
  const client = {
    user: { id: "bot-1" },
    channels: {
      fetch: async () => ({
        send() {},
        permissionsFor: () => ({ has: () => true }),
      }),
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
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "discord-bot-test-"));
  const connector = new DiscordOfficialbotConnector({
    client,
    config: {
      adapterId: "discord-officialbot-v2",
      connectorId: "discord-officialbot-v2",
      sendEnabled: true,
      allowedChannelIds: new Set(["channel-1"]),
      allowedUserIds: new Set(),
    },
    journal: new DeliveryJournal(path.join(directory, "journal.jsonl")),
    kernel,
    logger: { error() {} },
  });
  return { command, connector, receipts, sends, sourceMessage };
}

test("official Discord connector sends once with a deterministic nonce", async () => {
  const { command, connector, receipts, sends, sourceMessage } = fixture();

  const first = await connector.handleMessage(sourceMessage);
  const duplicate = await connector.handleMessage(sourceMessage);

  assert.equal(first.outcome, "sent");
  assert.equal(duplicate.outcome, "reconciled");
  assert.equal(sends.length, 1);
  assert.equal(sends[0].nonce, commandNonce(command));
  assert.equal(sends[0].enforceNonce, true);
  assert.equal(receipts.length, 2);
});

test("official Discord connector ignores messages from bots", async () => {
  const { connector, sourceMessage } = fixture();
  sourceMessage.author.bot = true;

  assert.deepEqual(await connector.handleMessage(sourceMessage), {
    outcome: "ignored",
  });
});

test("official Discord connector resolves reply-to-agent identity", async () => {
  const { connector, sourceMessage } = fixture();
  let receivedEnvelope = null;
  connector.kernel.ingest = async (envelope) => {
    receivedEnvelope = envelope;
    return { dispatch: null };
  };
  sourceMessage.reference = { messageId: "prior-message" };
  sourceMessage.fetchReference = async () => ({ author: { id: "bot-1" } });

  await connector.handleMessage(sourceMessage);

  assert.equal(receivedEnvelope.event.reply_to.actor_id, "bot-1");
});

test("official Discord connector accepts any channel with wildcard", async () => {
  const { command, connector, sourceMessage } = fixture();
  connector.config.allowAllChannels = true;
  connector.config.allowedChannelIds = new Set(["-1"]);
  sourceMessage.channelId = "other-channel";
  command.target_conversation_id = "other-channel";

  const result = await connector.handleMessage(sourceMessage);

  assert.equal(result.outcome, "sent");
});
