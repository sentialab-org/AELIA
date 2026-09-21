# ADR 0011: Use a versioned, module-owned prompt registry

- Status: Accepted
- Date: 2026-07-30

## Context

The V2 report identifies prompts as a second codebase when their inputs,
outputs, ownership, and composition are implicit. Persona source prompts were
already byte-preserved, but the running language boundary only carried a
content plan. It did not identify a reviewable module prompt or trace its parts.

No live LLM is enabled, so adding a provider client would be premature. The
kernel still needs a stable contract now so later provider work cannot quietly
absorb policy authority.

## Decision

Create a dependency-light `llm` boundary with:

- strict `PromptDefinition` and `PromptComposition` schema `1.0.0`;
- immutable prompt ID, semantic version, module, explicit owner, and declared
  input/output schemas;
- named system/developer parts whose exact text and SHA-256 hashes are recorded;
- a hash of dynamic structured input rather than duplicated private event text;
- a deterministic composition hash stored inside each new content plan; and
- a snapshot test for the complete language-realization definition.

The language-realization prompt may only realize an already selected outbound
action. Its instructions explicitly forbid changing action type, target,
permissions, goals, policy, or tool state.

Action schema `2.2.0` requires prompt composition metadata. Action `2.1.0`
remains readable and replayable for compatibility. Event, trace, and adapter
contract versions do not change.

## Alternatives considered

- Wait until a provider is chosen. Rejected because prompt ownership and trace
  shape would then be dictated by provider integration.
- Use the preserved persona prompt as one system prompt. Rejected because it
  would collapse persona evidence, policy, and language realization back into
  hidden prompt code.
- Store fully rendered event text again in prompt metadata. Rejected because the
  canonical event already contains it and trace export must minimize private
  duplication.

## Consequences

Prompt changes now require a visible version/snapshot change. Exact prompt parts
and structured-input hashes are inspectable in the selected action trace. The
registry adds no model SDK, network call, or new source of policy authority.
