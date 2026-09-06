"""DuckDB reusable-embedding state helpers owned by the backend package."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from codira.contracts import StoredEmbeddingRow
from codira.semantic.embeddings import EmbeddingBackendSpec

from .duckdb_query_primitives import _backend_bytes, _backend_int
from .duckdb_index_state import _count_indexed_files

if TYPE_CHECKING:
    from codira.contracts import BackendQueryValue

    from .duckdb_support import _DuckDBPersistenceConnection


def _load_previous_symbol_embeddings(
    conn: _DuckDBPersistenceConnection,
    file_path: str,
    *,
    backend: EmbeddingBackendSpec,
) -> dict[str, StoredEmbeddingRow]:
    """
    Load reusable stored embeddings for one indexed file.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    file_path : str
        Absolute file path whose stored embeddings should be loaded.
    backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.

    Returns
    -------
    dict[str, codira.contracts.StoredEmbeddingRow]
        Stored embeddings keyed by durable symbol identity.
    """
    rows = conn.execute(
        """
        SELECT s.stable_id, e.content_hash, e.dim, e.vector
        FROM embeddings e JOIN symbol_index s
          ON e.object_type = 'symbol' AND e.object_id = s.id
        JOIN files f ON s.file_id = f.id
        WHERE f.path = ? AND e.backend = ? AND e.version = ?
        ORDER BY s.stable_id
        """,
        (file_path, backend.name, backend.version),
    ).fetchall()
    rows.extend(
        conn.execute(
            """
            SELECT d.stable_id, e.content_hash, e.dim, e.vector
            FROM embeddings e JOIN documentation_artifacts d
              ON e.object_type = 'documentation' AND e.object_id = d.id
            JOIN files f ON d.file_id = f.id
            WHERE f.path = ? AND e.backend = ? AND e.version = ?
            ORDER BY d.stable_id
            """,
            (file_path, backend.name, backend.version),
        ).fetchall()
    )
    return {
        str(stable_id): StoredEmbeddingRow(
            stable_id=str(stable_id),
            content_hash=str(content_hash),
            dim=_backend_int(cast("BackendQueryValue", dim)),
            vector=_backend_bytes(cast("BackendQueryValue", vector)),
        )
        for stable_id, content_hash, dim, vector in rows
    }


def _load_previous_embeddings_by_path(
    conn: _DuckDBPersistenceConnection,
    paths: list[str],
    *,
    backend: EmbeddingBackendSpec,
) -> dict[str, dict[str, StoredEmbeddingRow]]:
    """Load reusable stored embeddings for the supplied replacement paths.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    paths : list[str]
        Absolute file paths that may be replaced during the current run.
    backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.

    Returns
    -------
    dict[str, dict[str, codira.contracts.StoredEmbeddingRow]]
        Stored embeddings grouped by absolute path and durable identity.
    """
    result: dict[str, dict[str, StoredEmbeddingRow]] = {path: {} for path in paths}
    if not paths:
        return result
    placeholders = ", ".join("?" for _ in paths)
    rows = conn.execute(
        f"""
        SELECT f.path, s.stable_id, e.content_hash, e.dim, e.vector
        FROM embeddings e JOIN symbol_index s
          ON e.object_type = 'symbol' AND e.object_id = s.id
        JOIN files f ON s.file_id = f.id
        WHERE f.path IN ({placeholders}) AND e.backend = ? AND e.version = ?
        ORDER BY f.path, s.stable_id
        """,
        (*paths, backend.name, backend.version),
    ).fetchall()
    rows.extend(
        conn.execute(
            f"""
        SELECT f.path, d.stable_id, e.content_hash, e.dim, e.vector
        FROM embeddings e JOIN documentation_artifacts d
          ON e.object_type = 'documentation' AND e.object_id = d.id
        JOIN files f ON d.file_id = f.id
        WHERE f.path IN ({placeholders}) AND e.backend = ? AND e.version = ?
        ORDER BY f.path, d.stable_id
        """,
            (*paths, backend.name, backend.version),
        ).fetchall()
    )
    for file_path, stable_id, content_hash, dim, vector in rows:
        result.setdefault(str(file_path), {})[str(stable_id)] = StoredEmbeddingRow(
            stable_id=str(stable_id),
            content_hash=str(content_hash),
            dim=_backend_int(cast("BackendQueryValue", dim)),
            vector=_backend_bytes(cast("BackendQueryValue", vector)),
        )
    return result


def _count_reused_embeddings(
    conn: _DuckDBPersistenceConnection,
    reused_paths: list[str],
) -> int:
    """Count preserved embeddings for unchanged indexed paths.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    reused_paths : list[str]
        Absolute file paths reused without reparsing.

    Returns
    -------
    int
        Number of preserved symbol and documentation embedding rows.
    """
    if not reused_paths:
        return 0
    if len(reused_paths) == _count_indexed_files(conn):
        row = conn.execute(
            "SELECT COUNT(*) FROM embeddings WHERE object_type IN ('symbol', 'documentation')"
        ).fetchone()
        assert row is not None
        return _backend_int(cast("BackendQueryValue", row[0]))
    row = conn.execute(
        """SELECT COUNT(*) FROM (
        SELECT e.id FROM embeddings e JOIN symbol_index s ON e.object_type = 'symbol' AND e.object_id = s.id JOIN files f ON s.file_id = f.id WHERE f.path IN (SELECT * FROM unnest(?))
        UNION ALL
        SELECT e.id FROM embeddings e JOIN documentation_artifacts d ON e.object_type = 'documentation' AND e.object_id = d.id JOIN files f ON d.file_id = f.id WHERE f.path IN (SELECT * FROM unnest(?)))""",
        (reused_paths, reused_paths),
    ).fetchone()
    assert row is not None
    return _backend_int(cast("BackendQueryValue", row[0]))
