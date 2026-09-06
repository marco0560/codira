"""Source-path policy helpers for SQLite docstring issue persistence."""

from __future__ import annotations

from pathlib import Path

from codira.repository_scope import path_has_excluded_tree_name


def _should_audit_docstrings(source_path: Path) -> bool:
    """
    Decide whether one source file participates in docstring auditing.

    Parameters
    ----------
    source_path : pathlib.Path
        Source file path whose indexed artifacts are being audited.

    Returns
    -------
    bool
        ``True`` when docstring issues should be emitted for the file.

    Notes
    -----
    Shell artifacts do not follow the project's NumPy-style docstring contract.
    """
    return source_path.suffix not in {
        ".sh",
        ".bash",
    } and not path_has_excluded_tree_name(source_path)


def _should_require_raises_section(source_path: Path, function_name: str) -> bool:
    """
    Decide whether a callable should require a ``Raises`` docstring section.

    Parameters
    ----------
    source_path : pathlib.Path
        Source file path owning the callable.
    function_name : str
        Callable name as stored in the index.

    Returns
    -------
    bool
        ``True`` when explicit raises should require a ``Raises`` section.

    Notes
    -----
    Pytest-style test callables use local raises as assertion fallbacks.
    """
    return not (
        "tests" in source_path.parts
        and source_path.suffix == ".py"
        and function_name.startswith("test_")
    )
