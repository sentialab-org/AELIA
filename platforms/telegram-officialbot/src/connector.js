"use strict";

const {
  createExternalReceipt,
  messageFromUpdate,
  normalizeTelegramUpdate,
  parseTelegramEventId,
} = require("./contracts");

class TelegramOfficialbotConnector {
  constructor({ api, bot, config, journal, kernel, logger = console }) {
    this.api = api;
    this.bot = bot;
    this.config = config;
    this.journal = journal;
    this.kernel = kernel;
    this.logger = logger;
    this.chatChains = new Map();
  }

  enqueue(update) {
    const chatId = String(messageFromUpdate(update)?.chat?.id || "unsupported");
    const previous = this.chatChains.get(chatId) || Promise.resolve();
    const next = previous
      .catch(() => {})
      .then(() => this.handleUpdate(update))
      .finally(() => {
        if (this.chatChains.get(chatId) === next) this.chatChains.delete(chatId);
      });
    this.chatChains.set(chatId, next);
    return next;
  }

  async handleUpdate(update) {
    const message = messageFromUpdate(update);
    if (!this.#acceptInbound(message)) return { outcome: "ignored" };
    const envelope = normalizeTelegramUpdate(update, {
      adapterId: this.config.adapterId,
      bot: this.bot,
    });
    const result = await this.kernel.ingest(envelope);
    const dispatch = result.dispatch;
    if (!dispatch || dispatch.decision?.outcome !== "queue_external_canary") {
      return { outcome: dispatch?.decision?.outcome || "no_action" };
    }

    const command = dispatch.command;
    this.#validateCommand(command, message);
    const prior = this.journal.lookup(command.idempotency_key);
    if (prior?.receipt) return this.#acknowledge(prior.receipt, "reconciled");
    if (prior?.state === "attempting") {
      return this.#recordAndAcknowledge(
        createExternalReceipt({
          command,
          connectorId: this.config.connectorId,
          status: "unknown",
          errorCode: "unreconciled_prior_send_attempt",
        }),
      );
    }

    let send;
    try {
      send = await this.#prepareSend(command, message);
    } catch (error) {
      this.#logError("telegram_officialbot_preflight_failed", command, error);
      return this.#recordAndAcknowledge(
        createExternalReceipt({
          command,
          connectorId: this.config.connectorId,
          status: "not_sent",
          errorCode: "telegram_preflight_failed",
        }),
      );
    }

    this.journal.begin(command);
    try {
      const sent = await send();
      return this.#recordAndAcknowledge(
        createExternalReceipt({
          command,
          connectorId: this.config.connectorId,
          status: "sent",
          platformMessageId: String(sent.message_id),
        }),
      );
    } catch (error) {
      const status = error?.deliveryStatus === "not_sent" ? "not_sent" : "unknown";
      this.#logError("telegram_officialbot_send_failed", command, error);
      return this.#recordAndAcknowledge(
        createExternalReceipt({
          command,
          connectorId: this.config.connectorId,
          status,
          errorCode:
            status === "not_sent"
              ? "telegram_api_rejected_send"
              : "telegram_send_failed_after_attempt",
        }),
      );
    }
  }

  #acceptInbound(message) {
    if (!message?.chat || !message.from && !message.sender_chat) return false;
    if (message.from?.is_bot) return false;
    const chatId = String(message.chat.id);
    if (!this.config.allowedChatIds.has(chatId)) return false;
    const actorId = String((message.from || message.sender_chat).id);
    return (
      this.config.allowedUserIds.size === 0 ||
      this.config.allowedUserIds.has(actorId)
    );
  }

  #validateCommand(command, message) {
    if (!this.config.sendEnabled) throw new Error("Telegram send kill switch is off");
    if (command.platform !== "telegram") {
      throw new Error("Kernel command targets a different platform");
    }
    if (String(command.target_conversation_id) !== String(message.chat.id)) {
      throw new Error("Kernel command targets a different chat");
    }
    if (!this.config.allowedChatIds.has(String(command.target_conversation_id))) {
      throw new Error("Kernel command chat is not allowlisted");
    }
    if (!command.content?.trim()) throw new Error("Kernel command has no content");
  }

  async #prepareSend(command, sourceMessage) {
    const chatId = String(command.target_conversation_id);
    const canSend = await this.api.canSend({
      chatId,
      chatType: sourceMessage.chat.type,
      botId: this.bot.id,
    });
    if (!canSend) throw new Error("Telegram bot lacks send permission");

    const payload = {
      chat_id: chatId,
      text: command.content,
    };
    if (sourceMessage.message_thread_id) {
      payload.message_thread_id = sourceMessage.message_thread_id;
    }
    if (command.action_type === "reply" && command.reply_to_event_id) {
      const target = parseTelegramEventId(command.reply_to_event_id);
      if (
        target.chatId !== chatId ||
        target.messageId !== String(sourceMessage.message_id)
      ) {
        throw new Error("Telegram reply target does not match source message");
      }
      payload.reply_parameters = {
        message_id: Number(target.messageId),
        allow_sending_without_reply: false,
      };
    }
    return () => this.api.sendMessage(payload);
  }

  async #recordAndAcknowledge(receipt) {
    this.journal.recordReceipt(receipt);
    return this.#acknowledge(receipt, receipt.status);
  }

  async #acknowledge(receipt, outcome) {
    await this.kernel.recordExternalReceipt(receipt);
    this.journal.markAcknowledged(receipt);
    return { outcome, receipt };
  }

  #logError(event, command, error) {
    this.logger.error(event, {
      commandId: command.command_id,
      errorType: error?.constructor?.name || "Error",
    });
  }
}

module.exports = { TelegramOfficialbotConnector };
