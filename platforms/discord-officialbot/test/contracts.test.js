"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createExternalReceipt,
  normalizeDiscordMessage,
} = require("../src/contracts");

test("official Discord message maps to platform discord", () => {
  const envelope = normalizeDiscordMessage(
    {
      id: "message-1",
      channelId: "channel-1",
      guildId: "guild-1",
      content: "hello",
      createdAt: new Date("2026-07-30T00:00:00Z"),
      author: { id: "user-1" },
      channel: { send() {} },
      reply() {},
      react() {},
      mentions: { users: new Map([["bot-1", {}]]) },
      attachments: new Map(),
    },
    {
      adapterId: "discord-officialbot-v2",
      selfUserId: "bot-1",
      receivedAt: "2026-07-30T00:00:01Z",
    },
  );

  assert.equal(envelope.event.platform, "discord");
  assert.equal(envelope.event.event_id, "discord:message-1");
  assert.deepEqual(envelope.event.permissions.scopes, ["explicit_mention"]);
});

test("official Discord external receipt uses platform discord", () => {
  const receipt = createExternalReceipt({
    command: { command_id: "command-1", idempotency_key: "key-1" },
    connectorId: "discord-officialbot-v2",
    status: "sent",
    platformMessageId: "message-2",
  });

  assert.equal(receipt.platform, "discord");
  assert.equal(receipt.side_effect_performed, true);
});

test("official Discord preserves the referenced reply actor", () => {
  const envelope = normalizeDiscordMessage(
    {
      id: "message-2",
      channelId: "channel-1",
      guildId: "guild-1",
      content: "follow-up",
      author: { id: "user-1" },
      channel: { send() {} },
      reply() {},
      react() {},
      reference: { messageId: "message-1" },
      mentions: { users: new Map() },
      attachments: new Map(),
    },
    {
      adapterId: "discord-officialbot-v2",
      selfUserId: "bot-1",
      replyToActorId: "bot-1",
    },
  );

  assert.equal(envelope.event.reply_to.actor_id, "bot-1");
});
