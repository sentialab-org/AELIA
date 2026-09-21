# Web Retrieve Fast — Technical Implementation Report (2026-04-08)

## 1) Context and current objective

This workstream is focused on improving MCP web retrieval quality and speed for the agent runtime.

Current objective:
- Add a **single-call, high-speed web retrieval tool** (`web.retrieve_fast`) that combines:
  1. web search,
  2. bounded content retrieval from top URLs,
  3. deterministic response metadata for degraded/partial cases.
- Keep backward compatibility with existing tools:
  - `search.web`
  - `web.fetch`
- Prepare optional integration with dialogue tool-loop (strict allowlist and hard limits).

Primary design goals:
- Professional, deterministic contracts.
- Extreme speed optimization under strict budget.
- Safe outbound web behavior (public URL only, SSRF protections already established in `web.fetch` path).

---

## 2) Scope (at current time)

### In scope
- MCP provider implementation for `web.retrieve_fast` in `services/mcp/src/provider.rs`.
- Tool registration and export wiring in `services/mcp`.
- Contract tests for MCP HTTP/stdio/tools/integration.
- Optional dialogue tool-loop wiring in `libs/cognitive/src/dialogue_engine.rs`.

### Out of scope (for now)
- Replacing/removing `search.web` or `web.fetch`.
- New external dependencies for cache/search orchestration.
- Large architectural rewrites outside MCP/cognitive tool-loop boundaries.

---

## 3) Current progress snapshot

### 3.1 Completed implementation work

#### A. Core provider for `web.retrieve_fast` (implemented)
File: `services/mcp/src/provider.rs`

Implemented components:
- New tool constant: `WEB_RETRIEVE_FAST_TOOL = "web.retrieve_fast"`.
- New fast profile constants and bounds (budget/timeouts/fetch fanout/cache sizing).
- New config type:
  - `WebRetrieveFastProviderConfig`
- New provider type:
  - `WebRetrieveFastToolProvider`
- New input schema + parser:
  - `web_retrieve_fast_input_schema()`
  - `WebRetrieveFastInput`
- New execution path:
  - `execute_retrieve_fast(...)`
- New helper primitives:
  - budget accounting (`remaining_budget_ms`)
  - cache helpers (key/trim/meta override)
  - degraded deterministic response constructor
  - bounded page evidence fetch helper (`fetch_web_fast_evidence`)

Behavior currently implemented:
- Query validation (`query` required).
- Safe search normalization (`off|moderate|strict`).
- Search request with strict timeout and budget-aware fallback.
- Bounded fan-out fetch from top results (`fetch_k`).
- Per-page truncation (`max_chars_per_page`).
- Deterministic `meta` with degradation fields:
  - `partial`
  - `degraded_reason`
  - timings and fetch counters.
- In-memory TTL cache with bounded entry count.

#### B. Provider registration (implemented)
File: `services/mcp/src/provider.rs`
- `default_providers()` now includes `WebRetrieveFastToolProvider`.
- Search provider config is shared for `search.web` and `web.retrieve_fast` registration flow.

#### C. Public exports (implemented)
File: `services/mcp/src/lib.rs`
- Exported:
  - `WebRetrieveFastProviderConfig`
  - `WebRetrieveFastToolProvider`

---

### 3.2 Work started but not finished

#### Test updates (partial)
- File touched: `services/mcp/tests/tools.rs`
- Current state:
  - imports for fast provider were started.
  - full test cases are not yet complete.

---

### 3.3 Not started / pending

1. Dialogue tool-loop integration (`libs/cognitive/src/dialogue_engine.rs`)
- Current tool-loop allowlist only permits `social.get_dialogue_summary`.
- `web.retrieve_fast` is not yet added to tool definitions or execution branch.

2. Full MCP contract tests:
- `services/mcp/tests/http_contract.rs`
- `services/mcp/tests/stdio.rs`
- `testing/integration-tests/tests/web_tools_mcp_roundtrip.rs`

3. Verification runs:
- Targeted `cargo test` for changed crates/tests not yet executed after all new edits.

---

## 4) Technical design details (current plan)

### 4.1 Tool contract proposal (current implementation intent)

`web.retrieve_fast` input:
- `query` (required)
- `safesearch` (optional: off/moderate/strict)
- `fetch_k` (optional, bounded)
- `max_chars_per_page` (optional, bounded)

`web.retrieve_fast` output top-level:
- `query`
- `results[]` (search results)
- `evidence[]` (fetched page excerpts)
- `citations[]` (minimal source references)
- `meta` (strict deterministic telemetry/degradation)

`meta` fields (planned/implemented shape):
- `source`: `web_retrieve_fast`
- `response_ms`
- `search_ms`
- `fetch_ms`
- `partial`
- `degraded_reason`
- `cache_hit`
- `budget_ms`
- `fetch_attempted`
- `fetch_succeeded`

### 4.2 Latency strategy
- Enforce strict total budget (`total_budget_ms`).
- Split into search stage + bounded parallel fetch stage.
- Return deterministic degraded payload instead of hard failing whenever possible.
- Keep response payload bounded by per-page truncation and fetch fan-out limit.

### 4.3 Safety strategy
- Reuse existing URL safety controls already established in provider:
  - scheme restrictions,
  - credentialed URL rejection,
  - blocked hosts/suffixes,
  - private IP rejection,
  - redirect bounds,
  - content-type allowlist,
  - bounded body reads.

---

## 5) Detailed execution plan from current state

### Phase 1 — Complete MCP tests for new tool
1. `services/mcp/tests/tools.rs`
   - Add registry helper for fast provider.
   - Add enabled/disabled registration tests.
   - Add validation tests (`query` missing/empty, invalid safesearch, unknown fields).
2. `services/mcp/tests/http_contract.rs`
   - Add `tools/list` coverage for `web.retrieve_fast`.
   - Add `tools/call` success shape with stub executor.
   - Add deterministic bad-request error mapping tests.
3. `services/mcp/tests/stdio.rs`
   - Add stdio list/get/call paths for `web.retrieve_fast`.
   - Add validation and unknown-tool error code assertions.
4. `testing/integration-tests/tests/web_tools_mcp_roundtrip.rs`
   - Extend web tools registry and roundtrip assertions to include `web.retrieve_fast`.

### Phase 2 — Dialogue loop optional integration
File: `libs/cognitive/src/dialogue_engine.rs`
- Extend `default_tool_definitions()` to include `web.retrieve_fast` function definition (bounded schema).
- Extend `execute_dialogue_tool_loop(...)` dispatch:
  - keep strict allowlist,
  - add explicit branch for `web.retrieve_fast`,
  - maintain hard call limits/timeouts,
  - preserve deterministic tool-result envelope shape.
- Add targeted tests for:
  - allowed call,
  - invalid args,
  - unsupported fallback remains rejected.

### Phase 3 — Verify and harden
- Run focused test sets:
  - `cargo test -p mcp`
  - targeted cognitive tests for tool loop
  - integration roundtrip tests.
- Fix contract/test mismatches.
- Re-check that `search.web`/`web.fetch` remain unchanged in behavior.

---

## 6) Risks and mitigations

### Risk A: Contract drift across HTTP vs stdio vs registry
Mitigation:
- Add parallel contract tests in all three surfaces.
- Keep shared schema as single source in provider.

### Risk B: Latency regressions under slow endpoints
Mitigation:
- strict total budget and stage timeouts,
- deterministic degraded response instead of hanging.

### Risk C: Unsafe URL fetch path
Mitigation:
- only use existing validated URL pipeline and bounded reads.

### Risk D: Tool-loop overreach in cognitive worker
Mitigation:
- strict allowlist,
- cap calls per turn,
- timeout and explicit fallback behavior.

---

## 7) Operational status note

During this session, there were intermittent timeout/response interruptions in the interactive loop. This affected workflow continuity but does not change the technical target architecture above.

Current source state should be treated as:
- core provider implementation in progress and present,
- test and cognitive wiring pending completion.

---

## 8) Immediate next action (if resuming implementation)

Next concrete step:
- finish `services/mcp/tests/tools.rs` for `web.retrieve_fast` first,
- then move to `http_contract.rs`, `stdio.rs`, and integration tests in that order.
