"""Helpers for repo-root-relative prefix filtering.

Responsibilities
----------------
- Normalize prefix strings supplied by CLI arguments or retrieval plans.
- Build SQL clauses and predicate logic to restrict symbols to a filesystem prefix.

Design principles
-----------------
Prefix helpers keep normalization deterministic while guarding invalid inputs through validation.

Architectural role
------------------
This module belongs to the **query filtering layer** and enforces prefix constraints across index and query surfaces.
"""

from __future__ import annotations

from pathlib import Path


def normalize_prefix(root: Path, prefix: str | None) -> str | None:
    """
    Normalize a repo-root-relative prefix to an absolute path string.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to anchor the relative prefix.
    prefix : str | None
        User-supplied repo-root-relative prefix.

    Returns
    -------
    str | None
        Absolute normalized prefix path, or ``None`` when no prefix is set.

    Raises
    ------
    ValueError
        If the prefix is absolute or escapes the repository root.
    """
    if prefix is None:
        return None

    raw = prefix.strip()
    root_path = root.resolve()

    if raw in {"", "."}:
        return str(root_path)

    relative = Path(raw)
    if relative.is_absolute():
        normalized = relative.resolve(strict=False)
    else:
        normalized = (root_path / relative).resolve(strict=False)

    try:
        normalized.relative_to(root_path)
    except ValueError as exc:
        msg = "Prefix must stay under the repository root."
        raise ValueError(msg) from exc

    return str(normalized)


def prefix_clause(prefix: str | None, column: str) -> tuple[str, list[str]]:
    """
    Build a SQL predicate that restricts rows to one rooted file prefix.

    Parameters
    ----------
    prefix : str | None
        Absolute normalized prefix path.
    column : str
        SQL column name containing an absolute file path string.

    Returns
    -------
    tuple[str, list[str]]
        SQL fragment and bound parameters for the prefix restriction.
    """
    if prefix is None:
        return "", []

    return (
        f" AND ({column} = ? OR {column} LIKE ?)",
        [prefix, f"{prefix}/%"],
    )


def path_has_prefix(path: str | Path, prefix: str | None) -> bool:
    """
    Check whether a path lies within a normalized prefix.

    Parameters
    ----------
    path : str | pathlib.Path
        Candidate absolute file path.
    prefix : str | None
        Absolute normalized prefix path.

    Returns
    -------
    bool
        ``True`` when the path is equal to or nested under ``prefix``.
    """
    if prefix is None:
        return True

    path_text = str(path)
    return path_text == prefix or path_text.startswith(f"{prefix}/")
