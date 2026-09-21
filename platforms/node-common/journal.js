"use strict";

const fs = require("node:fs");
const path = require("node:path");

class DeliveryJournal {
  constructor(filePath) {
    this.filePath = filePath;
    this.records = new Map();
    this.metadata = new Map();
    this.#load();
  }

  #load() {
    if (!fs.existsSync(this.filePath)) return;
    const raw = fs.readFileSync(this.filePath, "utf8");
    for (const line of raw.split("\n")) {
      if (!line.trim()) continue;
      const record = JSON.parse(line);
      if (record.idempotency_key) {
        this.records.set(record.idempotency_key, record);
      }
      if (record.metadata_key) {
        this.metadata.set(record.metadata_key, record.value);
      }
    }
  }

  lookup(idempotencyKey) {
    return this.records.get(idempotencyKey) || null;
  }

  begin(command, extra = {}) {
    const existing = this.lookup(command.idempotency_key);
    if (existing) return existing;
    const record = {
      state: "attempting",
      command_id: command.command_id,
      idempotency_key: command.idempotency_key,
      started_at: new Date().toISOString(),
      ...extra,
    };
    this.#append(record);
    return record;
  }

  recordReceipt(receipt) {
    const record = {
      state: "receipt_ready",
      command_id: receipt.command_id,
      idempotency_key: receipt.idempotency_key,
      receipt,
      recorded_at: new Date().toISOString(),
    };
    this.#append(record);
    return record;
  }

  markAcknowledged(receipt) {
    const record = {
      state: "acknowledged",
      command_id: receipt.command_id,
      idempotency_key: receipt.idempotency_key,
      receipt,
      acknowledged_at: new Date().toISOString(),
    };
    this.#append(record);
    return record;
  }

  getMetadata(key, fallback = null) {
    return this.metadata.has(key) ? this.metadata.get(key) : fallback;
  }

  setMetadata(key, value) {
    const record = {
      metadata_key: key,
      value,
      recorded_at: new Date().toISOString(),
    };
    this.#append(record);
    return value;
  }

  #append(record) {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true, mode: 0o700 });
    const descriptor = fs.openSync(this.filePath, "a", 0o600);
    try {
      fs.writeSync(descriptor, `${JSON.stringify(record)}\n`, null, "utf8");
      fs.fsyncSync(descriptor);
    } finally {
      fs.closeSync(descriptor);
    }
    fs.chmodSync(this.filePath, 0o600);
    if (record.idempotency_key) {
      this.records.set(record.idempotency_key, record);
    }
    if (record.metadata_key) {
      this.metadata.set(record.metadata_key, record.value);
    }
  }
}

module.exports = { DeliveryJournal };
