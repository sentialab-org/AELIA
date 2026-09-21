from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
PACKAGE_ROOT = SOURCE_ROOT / "aelia"

FORBIDDEN_PREFIXES = {
    "contracts": (
        "aelia.adapters",
        "aelia.cognition",
        "aelia.runtime",
        "aelia.storage",
    ),
    "models": (
        "aelia.adapters",
        "aelia.autonomy",
        "aelia.cognition",
        "aelia.runtime",
        "aelia.storage",
    ),
    "persona": (
        "aelia.adapters",
        "aelia.cognition",
        "aelia.runtime",
        "aelia.storage",
    ),
    "cognition": (
        "aelia.adapters",
        "aelia.runtime",
        "aelia.storage",
    ),
    "autonomy": (
        "aelia.adapters",
        "aelia.runtime",
        "aelia.storage",
    ),
    "llm": (
        "aelia.adapters",
        "aelia.cognition",
        "aelia.runtime",
        "aelia.storage",
    ),
    "runtime": ("aelia.adapters",),
}

PLATFORM_SDK_PREFIXES = (
    "discord",
    "telegram",
    "telethon",
    "aiogram",
    "nextcord",
)

# Floor for the whole package, deliberately below the current count so ordinary
# churn does not trip it while a renamed or emptied package root does.
MINIMUM_PACKAGE_SOURCES = 70


def _sources(directory: Path) -> tuple[Path, ...]:
    """Sources under a layer, refusing to hand back an empty gate.

    Every check below is a universal over the files it walks, so a missing or
    relocated directory would make it pass while enforcing nothing. Fail loudly
    instead.
    """
    assert directory.is_dir(), f"expected layer directory: {directory}"
    sources = tuple(directory.rglob("*.py"))
    assert sources, f"no Python sources under {directory}"
    return sources


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


def test_package_layout_still_exists_so_the_import_gates_are_not_vacuous() -> None:
    assert PACKAGE_ROOT.is_dir()
    assert (PACKAGE_ROOT / "__init__.py").is_file()
    for layer in FORBIDDEN_PREFIXES:
        assert _sources(PACKAGE_ROOT / layer)
    assert len(tuple(PACKAGE_ROOT.rglob("*.py"))) >= MINIMUM_PACKAGE_SOURCES


def test_dependency_direction_is_enforced_by_source_imports() -> None:
    violations = []
    for layer, forbidden in FORBIDDEN_PREFIXES.items():
        for path in _sources(PACKAGE_ROOT / layer):
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
        for path in _sources(PACKAGE_ROOT / layer):
            for imported in _imports(path):
                if imported.startswith(PLATFORM_SDK_PREFIXES):
                    violations.append(f"{path.relative_to(SOURCE_ROOT)} -> {imported}")

    assert violations == []


def test_internal_module_import_graph_is_acyclic() -> None:
    source_paths = tuple(PACKAGE_ROOT.rglob("*.py"))
    assert len(source_paths) >= MINIMUM_PACKAGE_SOURCES
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
