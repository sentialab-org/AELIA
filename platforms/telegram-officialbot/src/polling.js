"use strict";

const CURSOR_KEY = "telegram_update_offset";

class TelegramPollingRunner {
  constructor({ api, connector, journal, timeoutSeconds, logger = console }) {
    this.api = api;
    this.connector = connector;
    this.journal = journal;
    this.timeoutSeconds = timeoutSeconds;
    this.logger = logger;
    this.running = false;
  }

  stop() {
    this.running = false;
  }

  async run() {
    this.running = true;
    while (this.running) {
      try {
        await this.pollOnce();
      } catch (error) {
        this.logger.error("telegram_poll_failed", {
          errorType: error?.constructor?.name || "Error",
        });
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    }
  }

  async pollOnce() {
    let offset = Number(this.journal.getMetadata(CURSOR_KEY, 0));
    const updates = await this.api.getUpdates({
      offset,
      timeoutSeconds: this.timeoutSeconds,
    });
    for (const update of updates) {
      await this.connector.enqueue(update);
      offset = Number(update.update_id) + 1;
      this.journal.setMetadata(CURSOR_KEY, offset);
    }
    return updates.length;
  }
}

module.exports = { CURSOR_KEY, TelegramPollingRunner };
