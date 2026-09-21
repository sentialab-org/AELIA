"use strict";

const { randomUUID } = require("node:crypto");

const MAX_RESPONSE_BYTES = 5 * 1024 * 1024;
const RUNTIME_API_VERSION = "1.0.0";

class RuntimeClientError extends Error {
  constructor(message, { status = null, code = "runtime_request_failed" } = {}) {
    super(message);
    this.name = "RuntimeClientError";
    this.status = status;
    this.code = code;
  }
}

class RuntimeClient {
  constructor(config, { fetchImpl = globalThis.fetch, idImpl = randomUUID } = {}) {
    if (typeof fetchImpl !== "function") {
      throw new Error("RuntimeClient requires a fetch implementation");
    }
    this.config = config;
    this.fetchImpl = fetchImpl;
    this.idImpl = idImpl;
    this.baseUrl = String(config.runtimeUrl || "").replace(/\/+$/, "");
    if (!this.baseUrl) throw new Error("runtimeUrl must not be empty");
    const parsedUrl = new URL(this.baseUrl);
    if (
      !["http:", "https:"].includes(parsedUrl.protocol) ||
      parsedUrl.username ||
      parsedUrl.password ||
      parsedUrl.search ||
      parsedUrl.hash
    ) {
      throw new Error("runtimeUrl must be a credential-free HTTP(S) URL");
    }
  }

  ingest(envelope) {
    return this.#request("/v1/gates/ingress", envelope);
  }

  recordExternalReceipt(receipt) {
    return this.#request("/v1/gates/receipts", receipt);
  }

  health() {
    return this.#request("/health", undefined, { method: "GET", authenticate: false });
  }

  async #request(path, payload, { method = "POST", authenticate = true } = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      Number(this.config.requestTimeoutMs || this.config.kernelTimeoutMs || 180000),
    );
    timeout.unref?.();
    const headers = {
      Accept: "application/json",
      "X-Request-ID": `gate-request:${this.idImpl()}`,
    };
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (authenticate && this.config.runtimeGateToken) {
      headers.Authorization = `Bearer ${this.config.runtimeGateToken}`;
    }
    let response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: payload === undefined ? undefined : JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new RuntimeClientError("runtime backend request timed out", {
          code: "runtime_timeout",
        });
      }
      throw new RuntimeClientError("runtime backend is unreachable", {
        code: "runtime_unreachable",
      });
    } finally {
      clearTimeout(timeout);
    }

    const raw = await response.text();
    if (Buffer.byteLength(raw, "utf8") > MAX_RESPONSE_BYTES) {
      throw new RuntimeClientError("runtime backend response exceeded the safety bound", {
        status: response.status,
        code: "runtime_response_too_large",
      });
    }
    let parsed = null;
    if (raw.trim()) {
      try {
        parsed = JSON.parse(raw);
      } catch {
        throw new RuntimeClientError("runtime backend returned invalid JSON", {
          status: response.status,
          code: "runtime_invalid_json",
        });
      }
    }
    if (!response.ok) {
      const code = parsed?.error || "runtime_request_failed";
      const message = parsed?.message || `runtime backend returned HTTP ${response.status}`;
      throw new RuntimeClientError(message, { status: response.status, code });
    }
    if (parsed?.api_version !== RUNTIME_API_VERSION) {
      throw new RuntimeClientError("runtime backend API version is incompatible", {
        status: response.status,
        code: "runtime_api_version_mismatch",
      });
    }
    return parsed;
  }
}

module.exports = { RUNTIME_API_VERSION, RuntimeClient, RuntimeClientError };
