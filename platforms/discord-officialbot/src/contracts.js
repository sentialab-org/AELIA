"use strict";

const { createExternalReceipt: createReceipt } = require("../../node-common/receipts");

const EVENT_PREFIX = "discord:";

function attachmentKind(contentType) {
  if (contentType?.startsWith("image/")) return "image";
  if (contentType?.startsWith("audio/")) return "audio";
  if (contentType?.startsWith("video/")) return "video";
  return "file";
}

function normalizeDiscordMessage(
  message,
  { adapterId, selfUserId, receivedAt, replyToActorId = null },
) {
  const rawMessageId = String(message.id);
  const mentionIds = Array.from(message.mentions?.users?.keys?.() || [], String);
  const isDm = !message.guildId;
  return {
    schema_version: "1.0.0",
    delivery_id: `discord-delivery:${rawMessageId}`,
    idempotency_key: `discord-ingress:${rawMessageId}`,
    adapter_id: adapterId,
    received_at: receivedAt || new Date().toISOString(),
    event: {
      schema_version: "2.0.0",
      event_id: `${EVENT_PREFIX}${rawMessageId}`,
      platform: "discord",
      conversation_id: String(message.channelId),
      channel_type: isDm ? "dm" : message.channel?.isThread?.() ? "thread" : "channel",
      actor_id: String(message.author.id),
      occurred_at:
        message.createdAt?.toISOString?.() ||
        new Date(Number(message.createdTimestamp) || Date.now()).toISOString(),
      event_type: "message_created",
      content: message.content || null,
      reply_to: message.reference?.messageId
        ? {
            event_id: `${EVENT_PREFIX}${message.reference.messageId}`,
            actor_id: replyToActorId ? String(replyToActorId) : null,
          }
        : null,
      mentions: mentionIds,
      attachments: Array.from(message.attachments?.values?.() || [])
        .slice(0, 10)
        .map((attachment) => ({
          attachment_id: String(attachment.id),
          kind: attachmentKind(attachment.contentType),
          mime_type: attachment.contentType || null,
          filename: attachment.name || null,
          source_url: attachment.url || null,
          size_bytes: Number.isSafeInteger(attachment.size) ? attachment.size : null,
        })),
      permissions: {
        can_send_message: typeof message.channel?.send === "function",
        can_reply: typeof message.reply === "function",
        can_react: typeof message.react === "function",
        is_private: isDm,
        scopes: mentionIds.includes(selfUserId) ? ["explicit_mention"] : [],
      },
      source_reference: {
        adapter: adapterId,
        raw_event_id: rawMessageId,
        trace_id: null,
      },
    },
  };
}

function rawDiscordMessageId(eventId) {
  if (typeof eventId !== "string" || !eventId.startsWith(EVENT_PREFIX)) {
    throw new Error("Unsupported Discord event id");
  }
  return eventId.slice(EVENT_PREFIX.length);
}

function createExternalReceipt(values) {
  return createReceipt({ ...values, platform: "discord" });
}

module.exports = {
  createExternalReceipt,
  normalizeDiscordMessage,
  rawDiscordMessageId,
};
