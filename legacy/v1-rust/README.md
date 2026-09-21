# Polyverse Agent V1 — Frozen Rust Archive

This directory is the complete V1 reference environment, separated from the V2
Python codebase. V1 is frozen: use it only for source comparison or historical
runtime inspection.

Preserved local/runtime material:

- `.env` (ignored by Git, retained locally);
- `.env.example`;
- `settings.json`;
- `config/`;
- `prompts/`, including the original persona sources;
- `data/polyverse-agent/` (ignored by Git, retained locally);
- Cargo workspace source and lockfile;
- V1 wiki and development notes.

Generated `target/`, `node_modules/`, `.next/`, and model caches are intentionally
not archived because they are reproducible.

## Use

```bash
cd legacy/v1-rust
make help
cargo metadata --no-deps
```

Running a platform service may use real credentials from `.env`. Do not start
one unless the intended external side effect is explicitly authorized.
