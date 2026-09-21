"use strict";

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

class TelegramApiError extends Error {
  constructor(code, { deliveryStatus, retryAfter = null } = {}) {
    super(code);
    this.name = "TelegramApiError";
    this.code = code;
    this.deliveryStatus = deliveryStatus;
    this.retryAfter = retryAfter;
  }
}

class TelegramBotApiClient {
  constructor({ token, apiBase, fetchImpl = fetch }) {
    this.token = token;
    this.apiBase = apiBase;
    this.fetchImpl = fetchImpl;
  }

  getMe() {
    return this.#call("getMe", {}, { deliverySensitive: false, timeoutMs: 15000 });
  }

  getUpdates({ offset, timeoutSeconds }) {
    return this.#call(
      "getUpdates",
      {
        offset,
        timeout: timeoutSeconds,
        allowed_updates: ["message", "channel_post"],
      },
      {
        deliverySensitive: false,
        timeoutMs: (timeoutSeconds + 10) * 1000,
      },
    );
  }

  sendMessage(payload) {
    return this.#call("sendMessage", payload, {
      deliverySensitive: true,
      timeoutMs: 30000,
    });
  }

  async canSend({ chatId, chatType, botId }) {
    if (chatType === "private") return true;
    const member = await this.#call(
      "getChatMember",
      { chat_id: chatId, user_id: botId },
      { deliverySensitive: false, timeoutMs: 15000 },
    );
    if (member.status === "left" || member.status === "kicked") return false;
    if (member.status === "restricted") return member.can_send_messages === true;
    if (chatType === "channel" && member.status === "administrator") {
      return member.can_post_messages === true;
    }
    return true;
  }

  async #call(method, payload, { deliverySensitive, timeoutMs }) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    timer.unref?.();
    let response;
    try {
      response = await this.fetchImpl(`${this.apiBase}/bot${this.token}/${method}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch (error) {
      throw new TelegramApiError("telegram_transport_failure", {
        deliveryStatus: deliverySensitive ? "unknown" : "not_sent",
      });
    } finally {
      clearTimeout(timer);
    }

    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length > MAX_RESPONSE_BYTES) {
      throw new TelegramApiError("telegram_response_too_large", {
        deliveryStatus: deliverySensitive ? "unknown" : "not_sent",
      });
    }
    let body;
    try {
      body = JSON.parse(buffer.toString("utf8"));
    } catch {
      throw new TelegramApiError("telegram_invalid_response_json", {
        deliveryStatus: deliverySensitive ? "unknown" : "not_sent",
      });
    }
    if (!response.ok || body.ok !== true) {
      throw new TelegramApiError(`telegram_api_${body.error_code || response.status}`, {
        deliveryStatus: "not_sent",
        retryAfter: body.parameters?.retry_after || null,
      });
    }
    return body.result;
  }
}

module.exports = { TelegramApiError, TelegramBotApiClient };
