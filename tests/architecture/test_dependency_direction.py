from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
PACKAGE_ROOT = SOURCE_ROOT / "polyverse"

FORBIDDEN_PREFIXES = {
    "contracts": (
        "polyverse.adapters",
        "polyverse.cognition",
        "polyverse.runtime",
        "polyverse.storage",
    ),
    "models": (
        "polyverse.adapters",
        "polyverse.autonomy",
        "polyverse.cognition",
        "polyverse.runtime",
        "polyverse.storage",
    ),
    "persona": (
        "polyverse.adapters",
        "polyverse.cognition",
        "polyverse.runtime",
        "polyverse.storage",
    ),
    "cognition": (
        "polyverse.adapters",
        "polyverse.runtime",
        "polyverse.storage",
    ),
    "autonomy": (
        "polyverse.adapters",
        "polyverse.runtime",
        "polyverse.storage",
    ),
    "llm": (
        "polyverse.adapters",
        "polyverse.cognition",
        "polyverse.runtime",
        "polyverse.storage",
    ),
    "runtime": ("polyverse.adapters",),
}

PLATFORM_SDK_PREFIXES = (
    "discord",
    "telegram",
    "telethon",
    "aiogram",
    "nextcord",
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT).with_suffix("")
    parts = relative.parts
    return ".".join(parts[:-1]) if parts[-1] == "__init__" else ".".join(parts)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    return tuple(imported)


def test_dependency_direction_is_enforced_by_source_imports() -> None:
    violations = []
    for layer, forbidden in FORBIDDEN_PREFIXES.items():
        for path in (PACKAGE_ROOT / layer).rglob("*.py"):
            for imported in _imports(path):
                if imported.startswith(forbidden):
                    violations.append(f"{path.relative_to(SOURCE_ROOT)} -> {imported}")

    assert violations == []


def test_kernel_layers_do_not_import_platform_sdks() -> None:
    violations = []
    core_layers = (
        "contracts",
        "models",
        "persona",
        "cognition",
        "autonomy",
        "llm",
        "runtime",
    )
    for layer in core_layers:
        for path in (PACKAGE_ROOT / layer).rglob("*.py"):
            for imported in _imports(path):
                if imported.startswith(PLATFORM_SDK_PREFIXES):
                    violations.append(f"{path.relative_to(SOURCE_ROOT)} -> {imported}")

    assert violations == []


def test_internal_module_import_graph_is_acyclic() -> None:
    source_paths = tuple(PACKAGE_ROOT.rglob("*.py"))
    modules = {_module_name(path): path for path in source_paths}
    graph = {
        module: {
            imported for imported in _imports(path) if imported in modules and imported != module
        }
        for module, path in modules.items()
    }
    visiting: list[str] = []
    visited: set[str] = set()
    cycles: list[str] = []

    def visit(module: str) -> None:
        if module in visited:
            return
        if module in visiting:
            start = visiting.index(module)
            cycles.append(" -> ".join((*visiting[start:], module)))
            return
        visiting.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        visiting.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)

    assert cycles == []
