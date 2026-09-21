"use strict";

const {
  createExternalReceipt,
  normalizeDiscordMessage,
  rawDiscordMessageId,
} = require("./contracts");

class DiscordSelfbotConnector {
  constructor({ client, config, journal, kernel, logger = console }) {
    this.client = client;
    this.config = config;
    this.journal = journal;
    this.kernel = kernel;
    this.logger = logger;
    this.channelChains = new Map();
  }

  enqueue(message) {
    return this.enqueueWithStatus(message).completion;
  }

  enqueueWithStatus(message) {
    const channelId = String(message.channelId);
    const queued = this.channelChains.has(channelId);
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
    return { queued, completion: next };
  }

  async handleMessage(message) {
    const inbound = this.#inboundDisposition(message);
    if (!inbound.accepted) return { outcome: "ignored", reason: inbound.reason };

    const replyToActorId = await this.#replyToActorId(message);
    const envelope = normalizeDiscordMessage(message, {
      adapterId: this.config.adapterId,
      selfUserId: String(this.client.user.id),
      replyToActorId,
    });
    const result = await this.kernel.ingest(envelope);
    const cycleStatus = result.trace?.status || null;
    const dispatch = result.dispatch;
    if (!dispatch || dispatch.decision?.outcome !== "queue_external_canary") {
      return {
        outcome: dispatch?.decision?.outcome || "no_action",
        cycleStatus,
      };
    }

    const command = dispatch.command;
    this.#validateCommand(command, message);
    const prior = this.journal.lookup(command.idempotency_key);
    if (prior?.receipt) {
      await this.kernel.recordExternalReceipt(prior.receipt);
      this.journal.markAcknowledged(prior.receipt);
      return { outcome: "reconciled", cycleStatus, receipt: prior.receipt };
    }
    if (prior?.state === "attempting") {
      const receipt = createExternalReceipt({
        command,
        connectorId: this.config.connectorId,
        status: "unknown",
        errorCode: "unreconciled_prior_send_attempt",
      });
      return this.#withCycleStatus(await this.#recordAndAcknowledge(receipt), cycleStatus);
    }

    let send;
    try {
      send = await this.#prepareSend(command);
    } catch (error) {
      const receipt = createExternalReceipt({
        command,
        connectorId: this.config.connectorId,
        status: "not_sent",
        errorCode: "discord_preflight_failed",
      });
      this.logger.error("discord_send_preflight_failed", {
        commandId: command.command_id,
        errorType: error?.constructor?.name || "Error",
      });
      return this.#withCycleStatus(await this.#recordAndAcknowledge(receipt), cycleStatus);
    }

    this.journal.begin(command);
    let receipt;
    try {
      const sent = await send();
      receipt = createExternalReceipt({
        command,
        connectorId: this.config.connectorId,
        status: "sent",
        platformMessageId: String(sent.id),
      });
    } catch (error) {
      receipt = createExternalReceipt({
        command,
        connectorId: this.config.connectorId,
        status: "unknown",
        errorCode: "discord_send_failed_after_attempt",
      });
      this.logger.error("discord_send_failed", {
        commandId: command.command_id,
        errorType: error?.constructor?.name || "Error",
      });
    }
    return this.#withCycleStatus(await this.#recordAndAcknowledge(receipt), cycleStatus);
  }

  #inboundDisposition(message) {
    if (!this.client.user) {
      return { accepted: false, reason: "client_not_ready" };
    }
    if (String(message.author?.id) === String(this.client.user.id)) {
      return { accepted: false, reason: "self_author" };
    }
    if (!this.#channelAllowed(message.channelId)) {
      return { accepted: false, reason: "channel_not_allowed" };
    }
    if (
      this.config.allowedUserIds.size > 0 &&
      !this.config.allowedUserIds.has(String(message.author?.id))
    ) {
      return { accepted: false, reason: "actor_not_allowed" };
    }
    return { accepted: true, reason: null };
  }

  #validateCommand(command, sourceMessage) {
    if (!this.config.sendEnabled) {
      throw new Error("Discord send kill switch is off");
    }
    if (command.platform !== "discord_selfbot") {
      throw new Error("Kernel command targets a different platform");
    }
    if (String(command.target_conversation_id) !== String(sourceMessage.channelId)) {
      throw new Error("Kernel command targets a different conversation");
    }
    if (!this.#channelAllowed(command.target_conversation_id)) {
      throw new Error("Kernel command target is not allowlisted");
    }
    if (!command.content || !command.content.trim()) {
      throw new Error("Kernel command has no deliverable content");
    }
  }

  #channelAllowed(channelId) {
    return (
      this.config.allowAllChannels === true ||
      this.config.allowedChannelIds.has(String(channelId))
    );
  }

  async #replyToActorId(message) {
    if (!message.reference?.messageId) return null;
    try {
      const referenced = await message.fetchReference?.();
      return referenced?.author?.id ? String(referenced.author.id) : null;
    } catch (error) {
      this.logger.warn?.("discord_reply_reference_unavailable", {
        messageId: String(message.id),
        errorType: error?.constructor?.name || "Error",
      });
      return null;
    }
  }

  async #prepareSend(command) {
    const channel = await this.client.channels
      .fetch(String(command.target_conversation_id))
      .catch(() => null);
    if (!channel || typeof channel.send !== "function") {
      throw new Error("Discord channel is unavailable or not sendable");
    }
    const permissions = channel.permissionsFor?.(this.client.user);
    const requiredPermission = channel.isThread?.()
      ? "SEND_MESSAGES_IN_THREADS"
      : "SEND_MESSAGES";
    if (permissions && !permissions.has(requiredPermission)) {
      throw new Error("Discord account lacks send permission");
    }
    if (command.action_type === "reply" && command.reply_to_event_id) {
      const rawMessageId = rawDiscordMessageId(command.reply_to_event_id);
      const target = await channel.messages?.fetch?.(rawMessageId);
      if (!target || typeof target.reply !== "function") {
        throw new Error("Discord reply target is unavailable");
      }
      return () => target.reply({ content: command.content });
    }
    return () => channel.send({ content: command.content });
  }

  #withCycleStatus(result, cycleStatus) {
    return { ...result, cycleStatus };
  }

  async #recordAndAcknowledge(receipt) {
    this.journal.recordReceipt(receipt);
    await this.kernel.recordExternalReceipt(receipt);
    this.journal.markAcknowledged(receipt);
    return { outcome: receipt.status, receipt };
  }
}

module.exports = { DiscordSelfbotConnector };
