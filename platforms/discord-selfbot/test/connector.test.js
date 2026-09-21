"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { DiscordSelfbotConnector } = require("../src/connector");
const { DeliveryJournal } = require("../src/journal");

function fixture({ allowAllChannels = false, allowedChannelIds } = {}) {
  const ingests = [];
  const sent = [];
  const receipts = [];
  const command = {
    schema_version: "1.1.0",
    command_id: "command-1",
    action_id: "action-1",
    cycle_id: "cycle-1",
    platform: "discord_selfbot",
    action_type: "reply",
    target_conversation_id: "channel-1",
    reply_to_event_id: "discord-selfbot:message-1",
    content: "A short persona reply.",
    constraints: [],
    risk_class: "low",
    idempotency_key: "send-key-1",
    created_at: "2026-07-30T00:00:00Z",
  };
  const sourceMessage = {
    id: "message-1",
    channelId: "channel-1",
    guildId: "guild-1",
    content: "hello",
    createdAt: new Date("2026-07-30T00:00:00Z"),
    author: { id: "user-1" },
    channel: { send() {} },
    reply() {},
    react() {},
    mentions: { users: new Map() },
    attachments: new Map(),
  };
  const target = {
    reply(payload) {
      sent.push(payload);
      return Promise.resolve({ id: "sent-message-1" });
    },
  };
  const client = {
    user: { id: "self-1" },
    channels: {
      fetch: async () => ({ messages: { fetch: async () => target }, send() {} }),
    },
  };
  const kernel = {
    async ingest(envelope) {
      ingests.push(envelope);
      return {
        trace: { status: "completed" },
        dispatch: {
          decision: { outcome: "queue_external_canary" },
          command,
        },
      };
    },
    async recordExternalReceipt(receipt) {
      receipts.push(receipt);
      return { receipt };
    },
  };
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "polyverse-connector-"));
  const config = {
    adapterId: "discord-selfbot-v2",
    connectorId: "discord-selfbot-v2",
    sendEnabled: true,
    allowAllChannels,
    allowedChannelIds: allowedChannelIds || new Set(["channel-1"]),
    allowedUserIds: new Set(),
  };
  const logger = { error() {} };
  const connector = new DiscordSelfbotConnector({
    client,
    config,
    journal: new DeliveryJournal(path.join(directory, "journal.jsonl")),
    kernel,
    logger,
  });
  return { command, connector, ingests, receipts, sent, sourceMessage };
}

test("connector sends once and reconciles duplicate delivery from its journal", async () => {
  const { connector, receipts, sent, sourceMessage } = fixture();

  const first = await connector.handleMessage(sourceMessage);
  const repeated = await connector.handleMessage(sourceMessage);

  assert.equal(first.outcome, "sent");
  assert.equal(first.cycleStatus, "completed");
  assert.equal(repeated.outcome, "reconciled");
  assert.equal(repeated.cycleStatus, "completed");
  assert.equal(sent.length, 1);
  assert.equal(receipts.length, 2);
  assert.equal(receipts[0].platform_message_id, "sent-message-1");
  assert.deepEqual(receipts[1], receipts[0]);
});

test("connector reports an ignored non-allowlisted conversation before kernel ingestion", async () => {
  const { connector, ingests, sourceMessage } = fixture();
  sourceMessage.channelId = "other-channel";

  const result = await connector.handleMessage(sourceMessage);

  assert.deepEqual(result, { outcome: "ignored", reason: "channel_not_allowed" });
  assert.equal(ingests.length, 0);
});

test("connector reports self-authored messages as ignored without kernel ingestion", async () => {
  const { connector, ingests, sourceMessage } = fixture();
  sourceMessage.author.id = "self-1";

  const result = await connector.handleMessage(sourceMessage);

  assert.deepEqual(result, { outcome: "ignored", reason: "self_author" });
  assert.equal(ingests.length, 0);
});

test("connector reports messages before client readiness without kernel ingestion", async () => {
  const { connector, ingests, sourceMessage } = fixture();
  connector.client.user = null;

  const result = await connector.handleMessage(sourceMessage);

  assert.deepEqual(result, { outcome: "ignored", reason: "client_not_ready" });
  assert.equal(ingests.length, 0);
});

test("connector reports a non-allowlisted actor before kernel ingestion", async () => {
  const { connector, ingests, sourceMessage } = fixture();
  connector.config.allowedUserIds = new Set(["allowed-user"]);

  const result = await connector.handleMessage(sourceMessage);

  assert.deepEqual(result, { outcome: "ignored", reason: "actor_not_allowed" });
  assert.equal(ingests.length, 0);
});

test("connector reports completed no-action cycles as successful processing", async () => {
  const { connector, sourceMessage } = fixture();
  connector.kernel.ingest = async () => ({ trace: { status: "completed" }, dispatch: null });

  const result = await connector.handleMessage(sourceMessage);

  assert.deepEqual(result, { outcome: "no_action", cycleStatus: "completed" });
});

test("connector indicates when a channel already has queued work", async () => {
  const { connector, sourceMessage } = fixture();
  let release;
  let markStarted;
  const started = new Promise((resolve) => {
    markStarted = resolve;
  });
  let firstCall = true;
  connector.kernel.ingest = () => {
    if (!firstCall) return Promise.resolve({ trace: { status: "completed" }, dispatch: null });
    firstCall = false;
    markStarted();
    return new Promise((resolve) => {
      release = () => resolve({ trace: { status: "completed" }, dispatch: null });
    });
  };

  const first = connector.enqueueWithStatus(sourceMessage);
  const second = connector.enqueueWithStatus({ ...sourceMessage, id: "message-2" });

  assert.equal(first.queued, false);
  assert.equal(second.queued, true);
  await started;
  release();
  await Promise.all([first.completion, second.completion]);
});

test("connector accepts and validates any channel when wildcard is enabled", async () => {
  const { command, connector, sent, sourceMessage } = fixture({
    allowAllChannels: true,
    allowedChannelIds: new Set(["-1"]),
  });
  sourceMessage.channelId = "other-channel";
  command.target_conversation_id = "other-channel";

  const result = await connector.handleMessage(sourceMessage);

  assert.equal(result.outcome, "sent");
  assert.equal(sent.length, 1);
});

test("connector resolves reply-to-agent identity before runtime ingestion", async () => {
  const { connector, sourceMessage } = fixture();
  let receivedEnvelope = null;
  connector.kernel.ingest = async (envelope) => {
    receivedEnvelope = envelope;
    return { trace: { status: "completed" }, dispatch: null };
  };
  sourceMessage.reference = { messageId: "prior-message" };
  sourceMessage.fetchReference = async () => ({ author: { id: "self-1" } });

  await connector.handleMessage(sourceMessage);

  assert.equal(receivedEnvelope.event.reply_to.actor_id, "self-1");
});
