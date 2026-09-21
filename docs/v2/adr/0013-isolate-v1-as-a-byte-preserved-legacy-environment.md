# ADR 0013: Isolate V1 as a byte-preserved legacy environment

- Status: Accepted
- Date: 2026-07-30

## Context

V2 became the active Python codebase, but V1 Rust source, services, prompts,
wiki, configuration, runtime data, and root entrypoints still occupied the same
top-level namespace. That made the repository appear to have two active
architectures and kept Rust commands visible beside V2.

V1 is still useful as historical evidence, especially for persona comparison.
Deleting it outright would remove that evidence and local configuration needed
for later inspection.

## Decision

Move the complete V1 environment to `legacy/v1-rust/`:

- preserve every Git-tracked V1 file byte-for-byte;
- retain `.env`, `settings.json`, config, prompts, and local V1 data;
- keep V1 Cargo and Make entrypoints usable from within the archive;
- keep V2 Python, tests, CI, docs, and Make entrypoints at repository root;
- update persona integrity tests to compare the V2 archive with the relocated
  original prompts; and
- remove only generated build, dependency, and model caches.

V1 auxiliary worktree checkouts are removed only after confirming they are
clean. Their branches and commits remain in Git.

## Alternatives considered

- Store V1 only as a ZIP. Rejected because source comparison and Cargo metadata
  inspection would require repeated extraction.
- Delete V1 after copying persona files. Rejected because configuration and
  implementation evidence remain useful during the controlled rewrite.
- Leave V1 at root with legacy labels. Rejected because it still presents two
  competing development paths and encourages accidental V1 edits.

## Consequences

The root is now an unambiguous V2 codebase. V1 remains locally runnable and
reviewable inside one isolated directory, but no root build command depends on
it. Persona continuity stays byte-verifiable after relocation.
