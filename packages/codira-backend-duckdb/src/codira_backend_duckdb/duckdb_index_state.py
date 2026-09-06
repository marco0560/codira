"""DuckDB index-state inspection helpers owned by the backend package."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from codira.semantic.embeddings import EmbeddingBackendSpec

from .duckdb_query_primitives import _backend_int

if TYPE_CHECKING:
    from codira.contracts import BackendQueryValue

    from .duckdb_support import _DuckDBPersistenceConnection


def _current_embedding_state_matches(
    conn: _DuckDBPersistenceConnection,
    backend: EmbeddingBackendSpec,
) -> bool:
    """
    Check whether stored embeddings already match the active backend state.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.

    Returns
    -------
    bool
        ``True`` when all stored embeddings use the active backend and version.
    """
    rows = conn.execute(
        "SELECT DISTINCT backend, version, dim "
        "FROM embeddings ORDER BY backend, version, dim"
    ).fetchall()
    if not rows:
        return True
    return rows == [(backend.name, backend.version, backend.dim)]


def _load_existing_file_hashes(conn: _DuckDBPersistenceConnection) -> dict[str, str]:
    """
    Load indexed file hashes keyed by path.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    dict[str, str]
        Indexed file hashes keyed by absolute path.
    """
    rows = conn.execute("SELECT path, hash FROM files ORDER BY path").fetchall()
    return {str(path): str(file_hash) for path, file_hash in rows}


def _count_indexed_files(conn: _DuckDBPersistenceConnection) -> int:
    """
    Count files currently persisted in the DuckDB index.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    int
        Number of rows in the indexed files table.
    """
    row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
    assert row is not None
    return _backend_int(cast("BackendQueryValue", row[0]))


def _load_existing_file_ownership(
    conn: _DuckDBPersistenceConnection,
) -> dict[str, tuple[str, str]]:
    """
    Load persisted analyzer ownership keyed by path.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    dict[str, tuple[str, str]]
        Indexed analyzer ownership keyed by absolute path.
    """
    rows = conn.execute("""
        SELECT path, analyzer_name, analyzer_version
        FROM files
        ORDER BY path
        """).fetchall()
    return {
        str(path): (str(analyzer_name), str(analyzer_version))
        for path, analyzer_name, analyzer_version in rows
    }
