"use strict";

// Compatibility name for older connector imports. This module intentionally
// contains no process launcher; all runtime work crosses the HTTP protocol.
const { RuntimeClient, RuntimeClientError } = require("./runtime-client");

module.exports = { KernelClient: RuntimeClient, RuntimeClient, RuntimeClientError };
