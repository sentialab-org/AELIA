"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { DeliveryJournal } = require("../../node-common/journal");
const { CURSOR_KEY, TelegramPollingRunner } = require("../src/polling");

test("Telegram polling persists update_id plus one only after processing", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "telegram-poll-test-"));
  const journal = new DeliveryJournal(path.join(directory, "journal.jsonl"));
  const offsets = [];
  const processed = [];
  const runner = new TelegramPollingRunner({
    api: {
      async getUpdates({ offset }) {
        offsets.push(offset);
        return [{ update_id: 10 }, { update_id: 11 }];
      },
    },
    connector: {
      async enqueue(update) {
        processed.push(update.update_id);
      },
    },
    journal,
    timeoutSeconds: 1,
    logger: { error() {} },
  });

  assert.equal(await runner.pollOnce(), 2);

  assert.deepEqual(offsets, [0]);
  assert.deepEqual(processed, [10, 11]);
  assert.equal(journal.getMetadata(CURSOR_KEY), 12);
});
