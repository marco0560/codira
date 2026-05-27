"""Fixture for DuckDB persistence anti-pattern guardrails."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class BadDuckDBConnection:
    """Small fake connection for Semgrep fixture matching."""

    def executemany(
        self,
        query: str,
        rows: Sequence[Sequence[object]],
    ) -> None:
        """Pretend to execute row-wise statements."""


def persist_bad_rows(conn: BadDuckDBConnection) -> None:
    """
    Trigger DuckDB persistence anti-pattern rules.

    Parameters
    ----------
    conn : BadDuckDBConnection
        Fake DuckDB connection.

    Returns
    -------
    None
        The fixture intentionally violates repository Semgrep rules.
    """
    conn.executemany(
        "INSERT INTO modules(file_id, name, has_docstring) VALUES (?, ?, ?)",
        ((1, "pkg.bad", 0),),
    )
    conn.executemany(
        "INSERT INTO symbol_index(name, stable_id, type, module_name, file_id, lineno) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (("bad", "pkg.bad:bad", "function", "pkg.bad", 1, 1),),
    )
