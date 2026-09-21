"use strict";

const { createHash } = require("node:crypto");
const {
  createExternalReceipt,
  normalizeDiscordMessage,
  rawDiscordMessageId,
} = require("./contracts");

function commandNonce(command) {
  return createHash("sha256")
    .update(command.idempotency_key)
    .digest("hex")
    .slice(0, 24);
}

class DiscordOfficialbotConnector {
  constructor({ client, config, journal, kernel, logger = console }) {
    this.client = client;
    this.config = config;
    this.journal = journal;
    this.kernel = kernel;
    this.logger = logger;
    this.channelChains = new Map();
  }

  enqueue(message) {
    const channelId = String(message.channelId);
    const previous = this.channelChains.get(channelId) || Promise.resolve();
    const next = previous
      .catch(() => {})
      .then(() => this.handleMessage(message))
      .finally(() => {
        if (this.channelChains.get(channelId) === next) {
          this.channelChains.delete(channelId);
        }
      });
    this.channelChains.set(channelId, next);
    return next;
  }

  async handleMessage(message) {
    if (!this.#acceptInbound(message)) return { outcome: "ignored" };
    const replyToActorId = await this.#replyToActorId(message);
    const envelope = normalizeDiscordMessage(message, {
      adapterId: this.config.adapterId,
      selfUserId: String(this.client.user.id),
      replyToActorId,
    });
    const result = await this.kernel.ingest(envelope);
    const dispatch = result.dispatch;
    if (!dispatch || dispatch.decision?.outcome !== "queue_external_canary") {
      return { outcome: dispatch?.decision?.outcome || "no_action" };
    }

    const command = dispatch.command;
    this.#validateCommand(command, message);
    const prior = this.journal.lookup(command.idempotency_key);
    if (prior?.receipt) {
      return this.#acknowledge(prior.receipt, "reconciled");
    }
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
      this.#logError("discord_officialbot_preflight_failed", command, error);
      return this.#recordAndAcknowledge(
        createExternalReceipt({
          command,
          connectorId: this.config.connectorId,
          status: "not_sent",
          errorCode: "discord_preflight_failed",
        }),
      );
    }

    const nonce = commandNonce(command);
    this.journal.begin(command, { nonce });
    try {
      const sent = await send(nonce);
      return this.#recordAndAcknowledge(
        createExternalReceipt({
          command,
          connectorId: this.config.connectorId,
          status: "sent",
          platformMessageId: String(sent.id),
        }),
      );
    } catch (error) {
      this.#logError("discord_officialbot_send_failed", command, error);
      return this.#recordAndAcknowledge(
        createExternalReceipt({
          command,
          connectorId: this.config.connectorId,
          status: "unknown",
          errorCode: "discord_send_failed_after_attempt",
        }),
      );
    }
  }

  #acceptInbound(message) {
    if (!this.client.user || message.author?.bot) return false;
    if (String(message.author?.id) === String(this.client.user.id)) return false;
    if (
      !this.config.allowAllChannels &&
      !this.config.allowedChannelIds.has(String(message.channelId))
    ) {
      return false;
    }
    return (
      this.config.allowedUserIds.size === 0 ||
      this.config.allowedUserIds.has(String(message.author?.id))
    );
  }

  #validateCommand(command, message) {
    if (!this.config.sendEnabled) throw new Error("Discord send kill switch is off");
    if (command.platform !== "discord") {
      throw new Error("Kernel command targets a different platform");
    }
    if (String(command.target_conversation_id) !== String(message.channelId)) {
      throw new Error("Kernel command targets a different conversation");
    }
    if (
      !this.config.allowAllChannels &&
      !this.config.allowedChannelIds.has(String(command.target_conversation_id))
    ) {
      throw new Error("Kernel command target is not allowlisted");
    }
    if (!command.content?.trim()) throw new Error("Kernel command has no content");
  }

  async #replyToActorId(message) {
    if (!message.reference?.messageId) return null;
    try {
      const referenced = await message.fetchReference?.();
      return referenced?.author?.id ? String(referenced.author.id) : null;
    } catch (error) {
      this.logger.warn?.("discord_officialbot_reply_reference_unavailable", {
        messageId: String(message.id),
        errorType: error?.constructor?.name || "Error",
      });
      return null;
    }
  }

  async #prepareSend(command, sourceMessage) {
    const channel = await this.client.channels
      .fetch(String(command.target_conversation_id))
      .catch(() => null);
    if (!channel || typeof channel.send !== "function") {
      throw new Error("Discord channel is unavailable or not sendable");
    }
    const permissions = channel.permissionsFor?.(this.client.user);
    const permission = channel.isThread?.() ? "SendMessagesInThreads" : "SendMessages";
    if (permissions && !permissions.has(permission)) {
      throw new Error("Discord bot lacks send permission");
    }
    if (command.action_type === "reply" && command.reply_to_event_id) {
      const rawMessageId = rawDiscordMessageId(command.reply_to_event_id);
      if (rawMessageId !== String(sourceMessage.id)) {
        throw new Error("Discord reply target does not match the source message");
      }
      return (nonce) =>
        sourceMessage.reply({
          content: command.content,
          allowedMentions: { repliedUser: false },
          nonce,
          enforceNonce: true,
        });
    }
    return (nonce) =>
      channel.send({
        content: command.content,
        nonce,
        enforceNonce: true,
      });
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

module.exports = { DiscordOfficialbotConnector, commandNonce };
