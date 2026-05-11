"""Repository-wide source scope policy helpers.

Responsibilities
----------------
- Define repository trees that should not participate in normal Codira
  source discovery, indexing, retrieval, or audit workflows.
- Provide small deterministic predicates shared by scanner and backend audit
  policy code.

Design principles
-----------------
Repository-scope exclusions are structural project policy, not user runtime
configuration. Future configuration work may extend this baseline, but the
default policy must remain centralized.

Architectural role
------------------
This module belongs to the repository traversal policy layer shared by
scanner, indexing, and audit components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_EXCLUDED_TREE_NAMES: frozenset[str] = frozenset(
    {
        ".codira",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "fixtures",
    }
)


def _relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    """
    Return path parts relative to a repository root when possible.

    Parameters
    ----------
    path : pathlib.Path
        Candidate path.
    root : pathlib.Path
        Repository root.

    Returns
    -------
    tuple[str, ...]
        Relative path parts when ``path`` is below ``root``; otherwise the
        original path parts.
    """
    try:
        return path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return path.parts


def path_has_excluded_tree_name(path: Path) -> bool:
    """
    Return whether a path contains a default excluded tree name.

    Parameters
    ----------
    path : pathlib.Path
        Candidate path.

    Returns
    -------
    bool
        ``True`` when any path component is a repository-scope excluded tree.
    """
    return any(part in DEFAULT_EXCLUDED_TREE_NAMES for part in path.parts)


def is_repository_scope_excluded(path: Path, root: Path) -> bool:
    """
    Return whether a path is excluded by repository-scope policy.

    Parameters
    ----------
    path : pathlib.Path
        Candidate path.
    root : pathlib.Path
        Repository root used to evaluate relative path components.

    Returns
    -------
    bool
        ``True`` when the path is inside a default excluded repository tree.
    """
    return any(
        part in DEFAULT_EXCLUDED_TREE_NAMES for part in _relative_parts(path, root)
    )
