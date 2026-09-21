from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = PROJECT_ROOT / "src" / "aelia"
PLATFORM_ROOT = PROJECT_ROOT / "platforms"


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    return tuple(imported)


def test_backend_does_not_import_platform_packages_or_sdks() -> None:
    forbidden = ("platforms.", "discord", "telegram", "telethon", "aiogram")
    violations = []
    backend_sources = tuple((PYTHON_ROOT / "backend").rglob("*.py"))
    assert backend_sources, "expected the backend package to hold Python sources"
    for path in backend_sources:
        for imported in _imports(path):
            if imported.startswith(forbidden):
                violations.append(f"{path.relative_to(PROJECT_ROOT)} -> {imported}")
    assert violations == []


def test_node_gate_production_code_has_no_runtime_process_launcher() -> None:
    forbidden = ("child_process", "spawn(", "exec(", "uv run", "aelia adapter")
    gate_sources = tuple(
        path
        for path in PLATFORM_ROOT.rglob("*.js")
        if path.is_file()
        and "node_modules" not in path.parts
        and "/test/" not in str(path)
        and not path.name.endswith(".test.js")
    )
    assert gate_sources, "expected production JavaScript under platforms/"
    violations = []
    for path in gate_sources:
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in source:
                violations.append(f"{path.relative_to(PROJECT_ROOT)} contains {marker!r}")
    assert violations == []


def test_gate_processes_use_the_explicit_runtime_client() -> None:
    for path in (
        PLATFORM_ROOT / "discord-selfbot/src/index.js",
        PLATFORM_ROOT / "discord-officialbot/src/index.js",
        PLATFORM_ROOT / "telegram-officialbot/src/index.js",
    ):
        source = path.read_text(encoding="utf-8")
        assert "runtime-client" in source
        assert "new RuntimeClient" in source
