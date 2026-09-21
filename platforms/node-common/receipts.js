"use strict";

const { createHash } = require("node:crypto");

function receiptId(commandId, status) {
  const digest = createHash("sha256")
    .update(`${commandId}\u001f${status}`)
    .digest("hex")
    .slice(0, 24);
  return `external-receipt:${digest}`;
}

function createExternalReceipt({
  command,
  connectorId,
  platform,
  status,
  platformMessageId = null,
  errorCode = null,
  completedAt = new Date().toISOString(),
}) {
  const sideEffect = status === "sent" ? true : status === "not_sent" ? false : null;
  return {
    schema_version: "2.0.0",
    receipt_id: receiptId(command.command_id, status),
    command_id: command.command_id,
    idempotency_key: command.idempotency_key,
    platform,
    connector_id: connectorId,
    status,
    side_effect_performed: sideEffect,
    platform_message_id: platformMessageId,
    error_code: errorCode,
    retryable: false,
    completed_at: completedAt,
  };
}

module.exports = { createExternalReceipt };
