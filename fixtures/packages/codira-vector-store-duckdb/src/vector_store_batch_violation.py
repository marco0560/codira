"""Fixture for DuckDB vector-store persistence anti-pattern guardrails."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class BadDuckDBVectorConnection:
    """Small fake vector-store connection for Semgrep fixture matching."""

    def executemany(
        self,
        query: str,
        rows: Sequence[Sequence[object]],
    ) -> None:
        """Pretend to execute row-wise statements."""


def persist_bad_vector_rows(conn: BadDuckDBVectorConnection) -> None:
    """
    Trigger DuckDB vector-store persistence anti-pattern rules.

    Parameters
    ----------
    conn : BadDuckDBVectorConnection
        Fake DuckDB vector-store connection.

    Returns
    -------
    None
        The fixture intentionally violates repository Semgrep rules.
    """
    conn.executemany(
        "INSERT INTO vectors(vector_set_id, object_type, stable_id) VALUES (?, ?, ?)",
        ((1, "symbol", "pkg.bad:bad"),),
    )
