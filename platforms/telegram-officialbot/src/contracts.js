"use strict";

const { createExternalReceipt: createReceipt } = require("../../node-common/receipts");

const EVENT_PREFIX = "telegram:";

function messageFromUpdate(update) {
  return update.message || update.channel_post || null;
}

function channelType(chatType) {
  if (chatType === "private") return "dm";
  if (chatType === "group" || chatType === "supergroup") return "group";
  if (chatType === "channel") return "channel";
  return "unknown";
}

function extractMentions(message, bot) {
  const text = message.text || message.caption || "";
  const entities = message.entities || message.caption_entities || [];
  const mentions = [];
  for (const entity of entities) {
    if (entity.type === "text_mention" && entity.user?.id !== undefined) {
      mentions.push(String(entity.user.id));
    }
    if (entity.type === "mention" && bot.username) {
      const value = text.slice(entity.offset, entity.offset + entity.length);
      if (value.toLowerCase() === `@${bot.username}`.toLowerCase()) {
        mentions.push(String(bot.id));
      }
    }
  }
  return [...new Set(mentions)];
}

function normalizeAttachments(message) {
  const attachments = [];
  const photo = message.photo?.at?.(-1);
  if (photo) {
    attachments.push({
      attachment_id: String(photo.file_unique_id || photo.file_id),
      kind: "image",
      mime_type: "image/jpeg",
      filename: null,
      source_url: null,
      size_bytes: Number.isSafeInteger(photo.file_size) ? photo.file_size : null,
    });
  }
  const candidates = [
    ["audio", message.audio],
    ["audio", message.voice],
    ["video", message.video],
    ["video", message.video_note],
    ["file", message.document],
    ["video", message.animation],
  ];
  for (const [kind, item] of candidates) {
    if (!item) continue;
    attachments.push({
      attachment_id: String(item.file_unique_id || item.file_id),
      kind,
      mime_type: item.mime_type || null,
      filename: item.file_name || null,
      source_url: null,
      size_bytes: Number.isSafeInteger(item.file_size) ? item.file_size : null,
    });
  }
  return attachments.slice(0, 10);
}

function normalizeTelegramUpdate(update, { adapterId, bot, receivedAt }) {
  const message = messageFromUpdate(update);
  if (!message) throw new Error("Telegram update has no supported message");
  const chatId = String(message.chat.id);
  const messageId = String(message.message_id);
  const actor = message.from || message.sender_chat;
  if (!actor?.id) throw new Error("Telegram message has no actor identity");
  const eventId = `${EVENT_PREFIX}${chatId}:${messageId}`;

  return {
    schema_version: "1.0.0",
    delivery_id: `telegram-delivery:${update.update_id}`,
    idempotency_key: `telegram-ingress:${update.update_id}`,
    adapter_id: adapterId,
    received_at: receivedAt || new Date().toISOString(),
    event: {
      schema_version: "2.0.0",
      event_id: eventId,
      platform: "telegram",
      conversation_id: chatId,
      channel_type: channelType(message.chat.type),
      actor_id: String(actor.id),
      occurred_at: new Date(Number(message.date) * 1000).toISOString(),
      event_type: "message_created",
      content: message.text || message.caption || null,
      reply_to: message.reply_to_message
        ? {
            event_id: `${EVENT_PREFIX}${chatId}:${message.reply_to_message.message_id}`,
            actor_id: message.reply_to_message.from?.id
              ? String(message.reply_to_message.from.id)
              : null,
          }
        : null,
      mentions: extractMentions(message, bot),
      attachments: normalizeAttachments(message),
      permissions: {
        can_send_message: true,
        can_reply: true,
        can_react: false,
        is_private: message.chat.type === "private",
        scopes: message.message_thread_id ? ["message_thread"] : [],
      },
      source_reference: {
        adapter: adapterId,
        raw_event_id: String(update.update_id),
        trace_id: null,
      },
    },
  };
}

function parseTelegramEventId(eventId) {
  if (typeof eventId !== "string" || !eventId.startsWith(EVENT_PREFIX)) {
    throw new Error("Unsupported Telegram event id");
  }
  const [chatId, messageId, ...extra] = eventId.slice(EVENT_PREFIX.length).split(":");
  if (!chatId || !messageId || extra.length > 0) {
    throw new Error("Invalid Telegram event id");
  }
  return { chatId, messageId };
}

function createExternalReceipt(values) {
  return createReceipt({ ...values, platform: "telegram" });
}

module.exports = {
  createExternalReceipt,
  messageFromUpdate,
  normalizeTelegramUpdate,
  parseTelegramEventId,
};
