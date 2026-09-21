"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { DeliveryJournal } = require("../src/journal");

test("journal persists an attempt before a send and reloads its receipt", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "aelia-journal-"));
  const filePath = path.join(directory, "journal.jsonl");
  const command = { command_id: "command-1", idempotency_key: "key-1" };
  const journal = new DeliveryJournal(filePath);

  journal.begin(command);
  assert.equal(journal.lookup("key-1").state, "attempting");

  const receipt = {
    command_id: "command-1",
    idempotency_key: "key-1",
    status: "sent",
  };
  journal.recordReceipt(receipt);

  const reloaded = new DeliveryJournal(filePath);
  assert.deepEqual(reloaded.lookup("key-1").receipt, receipt);
  assert.equal(fs.statSync(filePath).mode & 0o777, 0o600);
});
