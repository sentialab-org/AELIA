# AELIA

**Work in progress.**

This repository is under active construction. It is not ready for use,
evaluation, deployment, or contribution.

Nothing here is stable. Interfaces, contracts, schemas, storage layout, prompts
and documentation all change without notice, and anything may be rewritten or
removed. The target architecture is not settled.

## Status

- Not production-ready. No release exists.
- No live platform is enabled by default. Every connector ships with its send
  switch off.
- The test suite passes locally. That is a statement about the tests, not about
  the system.
- Documentation is being standardised and is incomplete. Treat every document
  under `docs/` as describing an earlier state of the working tree.

## What is here

A Python cognitive kernel, and an archived Rust V1 that it replaces.

`legacy/v1-rust/` is a frozen, byte-preserved archive kept for reference. It is
not a production fallback, not a behavioural oracle, and must not be repaired,
extended or migrated. Do not use its data.

## Where the real state lives

`.aelia/coordination/` holds the current, honest picture:

- `CURRENT_STATE.md` — what actually runs today, with measured figures;
- `ARCHITECTURE_GAP.md` — every place the code falls short of what the
  documentation claims, and of what the target architecture requires;
- `HANDOFF.md` — open questions and the recommended next boundaries.

Read those before believing anything else, including this file.

## Documents

- [Architecture status report](docs/ARCHITECTURE_STATUS_REPORT.md)
- [Implementation status](docs/IMPLEMENTATION_STATUS.md)
- [Requirement evidence](docs/REQUIREMENT_EVIDENCE.md)
- [Final local audit](docs/FINAL_AUDIT.md)
- [Definition of Done](docs/DEFINITION_OF_DONE.md)
- [ADR index](docs/adr/)
- [V1 archive inventory](legacy/v1-rust/ARCHIVE_INVENTORY.md)
