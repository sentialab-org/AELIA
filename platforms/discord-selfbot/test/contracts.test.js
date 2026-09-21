"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createExternalReceipt,
  normalizeDiscordMessage,
  rawDiscordMessageId,
} = require("../src/contracts");

test("Discord message normalizes to the strict V2 inbound envelope", () => {
  const message = {
    id: "message-1",
    channelId: "channel-1",
    guildId: "guild-1",
    content: "hello <@self-1>",
    createdAt: new Date("2026-07-30T00:00:00Z"),
    author: { id: "user-1" },
    channel: { send() {} },
    reply() {},
    react() {},
    reference: { messageId: "message-0" },
    mentions: { users: new Map([["self-1", {}]]) },
    attachments: new Map([
      [
        "attachment-1",
        {
          id: "attachment-1",
          contentType: "image/png",
          name: "sample.png",
          url: "https://cdn.example.test/sample.png",
          size: 123,
        },
      ],
    ]),
  };

  const envelope = normalizeDiscordMessage(message, {
    adapterId: "discord-selfbot-v2",
    selfUserId: "self-1",
    receivedAt: "2026-07-30T00:00:01Z",
  });

  assert.equal(envelope.schema_version, "1.0.0");
  assert.equal(envelope.event.schema_version, "2.0.0");
  assert.equal(envelope.event.platform, "discord_selfbot");
  assert.equal(envelope.event.event_id, "discord-selfbot:message-1");
  assert.deepEqual(envelope.event.mentions, ["self-1"]);
  assert.equal(envelope.event.attachments[0].kind, "image");
  assert.equal(rawDiscordMessageId(envelope.event.reply_to.event_id), "message-0");
});

test("Discord selfbot preserves the referenced reply actor", () => {
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
      adapterId: "discord-selfbot-v2",
      selfUserId: "self-1",
      replyToActorId: "self-1",
    },
  );

  assert.equal(envelope.event.reply_to.actor_id, "self-1");
});

test("external receipt captures unambiguous sent evidence", () => {
  const receipt = createExternalReceipt({
    command: {
      command_id: "command-1",
      idempotency_key: "idempotency-1",
    },
    connectorId: "discord-selfbot-v2",
    status: "sent",
    platformMessageId: "message-2",
    completedAt: "2026-07-30T00:00:02Z",
  });

  assert.equal(receipt.schema_version, "2.0.0");
  assert.equal(receipt.status, "sent");
  assert.equal(receipt.side_effect_performed, true);
  assert.equal(receipt.platform_message_id, "message-2");
  assert.equal(receipt.error_code, null);
});
