"""Regression characterization for the host-target runtime migration boundary."""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PRODUCTION_HOST_AST_INVENTORY: dict[str, tuple[int, ...]] = {}


def _production_source_roots() -> tuple[Path, ...]:
    """
    Return all tracked production Python source roots.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[pathlib.Path, ...]
        Core and first-party package ``src`` directories.
    """
    package_roots = tuple(sorted((REPOSITORY_ROOT / "packages").glob("*/src")))
    return (REPOSITORY_ROOT / "src", *package_roots)


def _host_ast_consumer_lines(path: Path) -> tuple[int, ...]:
    """
    Locate host-AST imports and references in one production module.

    Parameters
    ----------
    path : pathlib.Path
        Python source module to inspect.

    Returns
    -------
    tuple[int, ...]
        Source lines that import or reference the host ``ast`` module.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        sorted(
            {
                node.lineno
                for node in ast.walk(tree)
                if (
                    isinstance(node, ast.Import)
                    and any(alias.name == "ast" for alias in node.names)
                )
                or (isinstance(node, ast.ImportFrom) and node.module == "ast")
                or (isinstance(node, ast.Name) and node.id == "ast")
            }
        )
    )


def _production_host_ast_inventory() -> dict[str, tuple[int, ...]]:
    """
    Build the deterministic inventory of production host-AST consumers.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, tuple[int, ...]]
        Repository-relative module paths and their host-AST consumer lines.
    """
    inventory: dict[str, tuple[int, ...]] = {}
    for root in _production_source_roots():
        for path in sorted(root.rglob("*.py")):
            lines = _host_ast_consumer_lines(path)
            if lines:
                inventory[str(path.relative_to(REPOSITORY_ROOT))] = lines
    return inventory


def test_production_host_ast_inventory_is_empty() -> None:
    """
    Prohibit production host-AST consumers after the parser migration.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts production code neither imports nor references the
        host ``ast`` module.

    Notes
    -----
        Slice 14 requires this inventory to remain empty after target-language
        parsing migrated out of core production modules.
    """
    assert _production_host_ast_inventory() == EXPECTED_PRODUCTION_HOST_AST_INVENTORY


def test_core_has_no_direct_python_analyzer_import() -> None:
    """Keep the core importable without the optional Python analyzer package.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts core source does not directly import the optional
        analyzer implementation package.
    """
    core_root = REPOSITORY_ROOT / "src" / "codira"
    direct_imports = [
        str(path.relative_to(REPOSITORY_ROOT))
        for path in sorted(core_root.rglob("*.py"))
        if "codira_analyzer_python" in path.read_text(encoding="utf-8")
    ]

    assert direct_imports == []
