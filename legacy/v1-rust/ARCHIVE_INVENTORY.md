# V1 Archive Inventory

Archived: 2026-07-30  
Source commit used for byte comparison: `b217a6c6a3c7d2f115e575b34cce75ea3f987278`

## Preserved

- 205 Git-tracked V1 files were compared byte-for-byte with the source commit:
  205 matched, 0 missing, 0 mismatched.
- The complete 13-package Cargo workspace and `Cargo.lock`.
- Rust, Node relay, wiki, test, script, configuration, prompt, and V1
  documentation sources.
- `.env` and `.claude/settings.local.json` locally, still ignored by Git.
- `settings.json`, `.env.example`, `config/`, and original persona prompt files.
- Nine local V1 data files under `data/polyverse-agent/`, still ignored by Git.
- The three removed Claude worktree branches remain in Git at commit `42af0f4`:
  `claude/busy-chatelet-a484c1`,
  `claude/flamboyant-williams-01f3e4`, and
  `claude/gallant-mendel-15ebe8`.

## Not archived

The following generated artifacts were moved to macOS Trash and are
reproducible from the preserved locks and source:

- root Cargo `target/` (approximately 16 GB);
- V1 Node `node_modules/` and Next.js `.next/` directories;
- generated `apps/cockpit/` cache-only directory;
- FastEmbed model cache.

## Verification

From the repository root:

```bash
make v2-doctor
make v2-quality
cargo metadata --no-deps --format-version 1 \
  --manifest-path legacy/v1-rust/Cargo.toml
```

Do not run an archived platform service without explicit authorization: the
preserved `.env` may contain real credentials.
