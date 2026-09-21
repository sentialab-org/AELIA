# ADR 0014: OpenAI-compatible async language provider

- Status: Accepted
- Date: 2026-07-30

## Context

V2 selected actions and composed versioned language prompts, but its language
generator was still a deterministic mock. The first real model boundary must
work with an owner-provided OpenAI-compatible API base, key, and model without
granting the model policy or execution authority.

The existing V1 dialogue configuration already contains those three local
values. The API key must not be copied into tracked files, logs, traces, error
messages, or resolved configuration output.

## Decision

Implement an asynchronous Chat Completions provider with:

- typed `openai_compatible` provider configuration;
- `POST {api_base}/chat/completions` with bearer authentication;
- `json_object` output by default and optional strict `json_schema` output;
- Pydantic validation of a single model-controlled `content` field;
- compatibility unwrapping for one outer `json` Markdown fence when a provider
  ignores JSON mode, followed by the same strict validation;
- the source event and selected persona view supplied only as ephemeral request
  input;
- bounded timeout, output tokens, response bytes, and retry attempts;
- retry only for connection establishment failures, HTTP 408/409/429, and
  server failures; ambiguous read/write transport failures are not retried;
- redirect following disabled so credentials cannot cross origins;
- redacted provider diagnostics and an optional authenticated `/models` probe;
- async model I/O outside platform delivery; and
- structured failed cycles when generation fails before execution.

The selected action, target, participation, permission, goal, and tool state
remain kernel-owned. The model can only realize text for the already-selected
action.

The prompt definition moves to `1.1.0`. New traces use schema `2.3.0`, which
records generation status, provider/model metadata, request ID, attempts, and a
redacted failure code. Trace `2.1.0` and `2.2.0` remain readable and replayable.

The local `config.toml` owns the non-secret API base, model route, timeout,
structured-output mode, and output budget. The root `.env` contains only the API
key and remains Git-ignored with owner-only file permissions. The checked-in
example stays `provider=mock`, so a fresh checkout cannot make a model request
implicitly.

## Alternatives considered

- Use the OpenAI SDK directly. Rejected for the first provider because the
  project needs a small language-neutral HTTP boundary and compatible providers
  may not implement SDK-specific surfaces uniformly.
- Use the Responses API. Deferred because the inherited endpoint is explicitly
  Chat Completions compatible and V1 already used that route.
- Keep a synchronous generator. Rejected because network model I/O would block
  the async runtime.
- Retry or downgrade structured-output modes automatically. Rejected because it
  can duplicate cost and silently change output guarantees.

## Consequences

Offline request, retry, validation, failure, replay, and secret-redaction tests
pass. A real `/models` probe is available through:

```bash
uv run polyverse llm doctor --probe
```

The current endpoint passes TLS and authenticated `/models` probing. On
August 24, 2026, `uai/claude-sonnet-4-6` was listed and the full runtime prompt
completed successfully through the backend HTTP path with
`thinking_mode = "disabled"` and `max_output_tokens = 4096`. Adaptive thinking
can consume a whole output budget before producing visible content: the earlier
512-token and 1,024-token requests ended with `finish_reason=max_tokens` and
empty content. The provider reports that condition as `output_truncated` instead
of the misleading `invalid_structured_output`. The application does not silently
substitute another model ID.
