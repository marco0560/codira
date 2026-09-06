"""DuckDB index-maintenance helpers owned by the backend package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .duckdb_support import _DuckDBPersistenceConnection


def _clear_index_tables(conn: _DuckDBPersistenceConnection) -> None:
    """Remove all indexed rows from DuckDB storage.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection to clear in place.

    Returns
    -------
    None
        Indexed tables are cleared in dependency-safe order.
    """
    for table_name in (
        "docstring_issues",
        "call_edges",
        "callable_refs",
        "call_records",
        "callable_ref_records",
        "reference_scan_lines",
        "overloads",
        "enum_members",
        "embeddings",
        "documentation_artifacts",
        "symbol_index",
        "imports",
        "functions",
        "classes",
        "modules",
        "files",
        "analysis_status",
    ):
        conn.execute(f"DELETE FROM {table_name}")


def _purge_skipped_docstring_issues(conn: _DuckDBPersistenceConnection) -> None:
    """Remove docstring issues belonging to excluded shell artifacts.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection to clean in place.

    Returns
    -------
    None
        Stale shell-owned issue rows are deleted.
    """
    conn.execute("""
        DELETE FROM docstring_issues
        WHERE file_id IN (
            SELECT id FROM files
            WHERE analyzer_name = 'bash' OR path LIKE '%.sh' OR path LIKE '%.bash'
        )
        """)
