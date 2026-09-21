# AELIA — Requirement-to-Evidence Matrix

Updated: 2026-08-24

This matrix treats the implementation plan as the delivery contract and the V2
report as the architecture source. A green test alone is not counted unless it
exercises the named invariant.

| Requirement | Status | Authoritative evidence |
|---|---|---|
| V1 is frozen, preserved, and isolated from V2 | Pass | ADR 0001/0013; 205/205 tracked files byte-match the source commit; archive separation and persona-integrity tests |
| Persona sources are byte-preserved | Pass | `config doctor`; persona hash manifest; source-integrity tests |
| Persona rules have source provenance | Pass | 43 rules validated by `PersonaSourceLoader`; behavioral suite |
| Strict, independently versioned contracts | Pass | event `2.0.0`, action `2.2.0`, trace `2.3.0`, adapter ingress `1.0.0`, command/receipt `1.1.0`; contract tests |
| Event ingest and idempotency | Pass | event contract and idempotency tests; duplicate integration tests |
| Deterministic replay | Pass | foundation, observation, persona, cognition, action, memory, autonomy, and group-join replay tests |
| Trace inspect/compare/export/redact | Pass | CLI observability commands and replay export/redaction tests |
| Observation loop and bounded context | Pass | 100-message group fixture, buffer pruning, reply-graph tests |
| Silence and wait are explicit | Pass | persisted-silence and recent-participation wait tests |
| Group participation without a tag | Pass | open-invitation Conversation Model and end-to-end `join` integration test |
| Questions owned by another person are not answered | Pass | conversation projection and action-cycle ownership tests |
| Anti-spam affects policy before output | Pass | recent reply/join penalties, turn-taking saturation, adapter rate tests |
| Self and Social Models affect policy | Pass | identity-inertia, trust-inertia, disclosure, and persona participation tests |
| World and Conversation Models are explicit | Pass | typed, provenance-bearing trace artifacts and context-model tests |
| Observations do not automatically become facts | Pass | epistemic perception and provisional/contested belief tests |
| Appraisal and internal dynamics precede policy | Pass | causal tests cover attention, memory retrieval, goal priority, action score, learning strength, participation, and turn-taking |
| Goal lifecycle, merge, and failed execution semantics | Pass | lifecycle/merge tests; failed execution leaves goal active and persists a failed trace plus structured outcome |
| LLM cannot directly execute or mutate state | Pass | proposal/language/execution ports; selected-action invariants and replay |
| OpenAI-compatible model boundary | Pass locally | Async Chat Completions client, typed/redacted config, structured output, retry/failure/replay tests; authenticated `/models` probe and full backend HTTP completion for `uai/claude-sonnet-4-6` pass |
| Prompt registry is versioned, owned, tested, and traced | Pass | ADR 0011; prompt definition/composition schemas; snapshot/hash tests; action-cycle trace assertion |
| Memory has one canonical source per concept | Pass | SQLite memory metadata, canonical references, duplicate/restart tests |
| Model-derived memory requires validation | Pass | validation-gated memory and learning tests |
| Initiative cannot bypass guardrails | Pass | shadow-only type invariants, opt-out/quiet-hour/rate/budget/privacy/risk tests |
| Adapter is independent of kernel/platform SDKs | Pass | AST dependency-direction, cycle, and SDK-import conformance tests |
| Independent runtime backend with N platform gates | Pass locally | ADR 0017; `aelia-backend`; `/health`, `/ready`, `/runtime/status`, ingress/receipt HTTP contracts; Node gates use `RuntimeClient` and contain no process launcher; live synthetic Discord-envelope smoke |
| Adapter reconnect/crash/outbox recovery | Pass | adapter runtime crash-window and concurrency integration tests |
| Transaction rollback and retry history | Pass | ADR 0010; atomic repository integration tests; recovered state-conflict trace/replay test |
| CLI test-canary is operable without live delivery | Pass | explicit fixed-content injector test; receipt remains `simulated` with `side_effect=false` |
| V2 quality gate runs in CI | Pass | `.github/workflows/quality.yml` reproduces locked format, lint, strict type-check, and test gates with read-only permissions |
| V2 is the documented default development path | Pass | root `README.md`, `.env.example`, and `make` entrypoints; V1 entrypoints live only under `legacy/v1-rust/` |
| Resolved config and privacy-bounded structured logging | Pass | `config doctor`; JSON logging unit test and CLI cycle-ID/no-content integration assertion |
| Architecture governance and Definition of Done | Pass | ADR set 0001–0017; `DEFINITION_OF_DONE.md`; dependency, runtime-boundary, and contract gates |
| External connector acceptance semantics are implemented | Pass offline | ADR 0012/0015/0016; external-canary outbox, receipt command, shared Node journal, duplicate-send/cursor tests, connector preflights |
| Rollback is documented | Pass | `P8_CUTOVER_RUNBOOK.md` |
| Real platform canary and live cutover | Pending execution | Three connectors are implemented; one credential/conversation activation and bounded live evidence remain |

The remaining external gate is one owner-authorized bounded platform canary. The
exact model route has passed the isolated provider probe and backend HTTP smoke.
Each Node connector's explicit send switch and conversation allowlist prevent
implicit platform delivery.
