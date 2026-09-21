from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
PACKAGE_ROOT = SOURCE_ROOT / "aelia"
MANIFEST_PATH = PACKAGE_ROOT / "persona/source/manifest.json"

# The pre-rename identity, in every casing the replacement pass had to handle.
# A casing-only mistake (`Aelia`) or a half-applied prefix (`POLYVERSE_`) shows
# up here rather than in production.
PRE_RENAME_MARKER = "polyverse"

SCANNED_ROOTS = (SOURCE_ROOT, PROJECT_ROOT / "tests", PROJECT_ROOT / "platforms")
SKIPPED_DIRECTORY_NAMES = frozenset({"node_modules", "__pycache__", ".venv"})
SCANNED_SUFFIXES = frozenset({".py", ".js", ".json", ".toml", ".yml", ".yaml", ".md", ".ts"})


def _scanned_files() -> tuple[Path, ...]:
    self_path = Path(__file__).resolve()
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
                continue
            if SKIPPED_DIRECTORY_NAMES.intersection(path.parts) or path.resolve() == self_path:
                # This guard has to spell the marker out to search for it.
                continue
            files.append(path)
    return tuple(files)


def test_python_package_is_the_aelia_package() -> None:
    assert PACKAGE_ROOT.is_dir()
    assert (PACKAGE_ROOT / "__init__.py").is_file()
    assert (PACKAGE_ROOT / "cli.py").is_file()
    assert (PACKAGE_ROOT / "backend/main.py").is_file()


def test_pre_rename_package_directory_is_gone() -> None:
    assert not (SOURCE_ROOT / PRE_RENAME_MARKER).exists()


def test_distribution_metadata_names_aelia() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "aelia"' in pyproject
    assert 'aelia = "aelia.cli:main"' in pyproject
    assert 'aelia-backend = "aelia.backend.main:main"' in pyproject
    assert 'packages = ["src/aelia"]' in pyproject
    assert PRE_RENAME_MARKER not in pyproject.lower()


def test_no_source_file_still_carries_the_pre_rename_identity() -> None:
    files = _scanned_files()
    assert files, "expected files to scan so this check is not vacuous"

    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in files
        if PRE_RENAME_MARKER in path.read_text(encoding="utf-8", errors="replace").lower()
    ]

    assert offenders == []


def test_persona_manifest_is_aelia_scoped_and_still_ryuuko() -> None:
    raw = MANIFEST_PATH.read_text(encoding="utf-8")
    manifest = json.loads(raw)

    assert manifest["persona_id"] == "ryuuko"
    assert PRE_RENAME_MARKER not in raw.lower()
    # Renaming the package directory must not silently orphan the manifest's
    # path values; they have to point at the package as it is now named.
    assert "src/aelia/" in raw
