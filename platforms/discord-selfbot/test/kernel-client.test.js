"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { KernelClient } = require("../src/kernel-client");

function jsonResponse(payload, { status = 200 } = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("compatibility KernelClient sends ingress through the runtime HTTP protocol", async () => {
  const calls = [];
  const client = new KernelClient(
    {
      requestTimeoutMs: 1_000,
      runtimeGateToken: "test-runtime-token",
      runtimeUrl: "http://127.0.0.1:8787/",
    },
    {
      idImpl: () => "request-001",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return jsonResponse({ api_version: "1.0.0", dispatch: null });
      },
    },
  );
  const envelope = { event: { conversation_id: "channel-42" } };

  const result = await client.ingest(envelope);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://127.0.0.1:8787/v1/gates/ingress");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers.Authorization, "Bearer test-runtime-token");
  assert.equal(calls[0].options.headers["X-Request-ID"], "gate-request:request-001");
  assert.deepEqual(JSON.parse(calls[0].options.body), envelope);
  assert.equal(result.api_version, "1.0.0");
});

test("external receipts use the dedicated runtime endpoint", async () => {
  const calls = [];
  const client = new KernelClient(
    {
      requestTimeoutMs: 1_000,
      runtimeGateToken: null,
      runtimeUrl: "http://runtime.test",
    },
    {
      idImpl: () => "request-002",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return jsonResponse({ api_version: "1.0.0", dispatch: { state: "finalized" } });
      },
    },
  );

  await client.recordExternalReceipt({ receipt_id: "receipt-001" });

  assert.equal(calls[0].url, "http://runtime.test/v1/gates/receipts");
  assert.equal(calls[0].options.headers.Authorization, undefined);
});

test("structured backend errors are surfaced without leaking response bodies", async () => {
  const client = new KernelClient(
    {
      requestTimeoutMs: 1_000,
      runtimeUrl: "http://runtime.test",
    },
    {
      fetchImpl: async () =>
        jsonResponse(
          {
            error: "conversation_not_allowed",
            message: "inbound conversation is not allowlisted",
          },
          { status: 403 },
        ),
    },
  );

  await assert.rejects(
    () => client.ingest({}),
    (error) =>
      error.code === "conversation_not_allowed" &&
      error.status === 403 &&
      /not allowlisted/.test(error.message),
  );
});

test("incompatible runtime API versions fail explicitly", async () => {
  const client = new KernelClient(
    {
      requestTimeoutMs: 1_000,
      runtimeUrl: "http://runtime.test",
    },
    {
      fetchImpl: async () => jsonResponse({ api_version: "2.0.0" }),
    },
  );

  await assert.rejects(
    () => client.health(),
    (error) => error.code === "runtime_api_version_mismatch" && error.status === 200,
  );
});
