"""Safe graph-identifier validation for DuckDB query construction.

Only repository-owned graph tables and columns may be interpolated into the
DuckDB graph query templates.
"""

from __future__ import annotations

import re


_SAFE_GRAPH_IDENTIFIER_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$", re.IGNORECASE)
_ALLOWED_GRAPH_TABLES = frozenset({"call_edges", "callable_refs"})
_ALLOWED_GRAPH_COLUMNS = frozenset(
    {
        "caller_module",
        "caller_name",
        "callee_module",
        "callee_name",
        "owner_module",
        "owner_name",
        "target_module",
        "target_name",
    }
)


def _validated_graph_identifier(identifier: str, *, kind: str) -> str:
    """
    Validate one internal DuckDB graph identifier before SQL interpolation.

    Parameters
    ----------
    identifier : str
        Internal table or column identifier interpolated into SQL text.
    kind : str
        Human-readable identifier class used in error messages.

    Returns
    -------
    str
        The validated identifier.

    Raises
    ------
    ValueError
        Raised when ``identifier`` is not one of the repository-owned graph
        identifiers expected by the backend query helpers.
    """
    if not _SAFE_GRAPH_IDENTIFIER_PATTERN.fullmatch(identifier):
        msg = f"Unsafe DuckDB graph {kind} identifier: {identifier!r}"
        raise ValueError(msg)
    if kind == "table" and identifier not in _ALLOWED_GRAPH_TABLES:
        msg = f"Unsupported DuckDB graph table identifier: {identifier!r}"
        raise ValueError(msg)
    if kind == "column" and identifier not in _ALLOWED_GRAPH_COLUMNS:
        msg = f"Unsupported DuckDB graph column identifier: {identifier!r}"
        raise ValueError(msg)
    return identifier
