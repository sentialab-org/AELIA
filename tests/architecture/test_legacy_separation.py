from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = PROJECT_ROOT / "legacy/v1-rust"


def test_v1_runtime_is_isolated_from_the_v2_root() -> None:
    assert not (PROJECT_ROOT / "Cargo.toml").exists()
    assert not (PROJECT_ROOT / "Cargo.lock").exists()
    assert not (PROJECT_ROOT / "apps").exists()
    assert not (PROJECT_ROOT / "libs").exists()
    active_platforms = PROJECT_ROOT / "platforms"
    assert {path.name for path in active_platforms.iterdir() if path.is_dir()} == {
        "discord-officialbot",
        "discord-selfbot",
        "node-common",
        "telegram-officialbot",
    }
    assert not tuple(active_platforms.rglob("Cargo.toml"))
    assert not tuple(active_platforms.rglob("*.rs"))

    assert (LEGACY_ROOT / "Cargo.toml").is_file()
    assert (LEGACY_ROOT / "Cargo.lock").is_file()
    assert (LEGACY_ROOT / "apps/agent").is_dir()
    assert (LEGACY_ROOT / "libs/kernel").is_dir()
    assert (LEGACY_ROOT / "platforms/discord").is_dir()
    assert (LEGACY_ROOT / "settings.json").is_file()
    assert (LEGACY_ROOT / "config").is_dir()
    assert (LEGACY_ROOT / "prompts/persona/base.v3.txt").is_file()


def test_v2_python_source_has_no_legacy_runtime_dependency() -> None:
    violations = []
    for source_path in (PROJECT_ROOT / "src/aelia").rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        if "legacy/v1-rust" in source or "legacy.v1_rust" in source:
            violations.append(str(source_path.relative_to(PROJECT_ROOT)))

    assert violations == []
