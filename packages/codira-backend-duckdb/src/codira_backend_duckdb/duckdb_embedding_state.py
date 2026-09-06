"""DuckDB reusable-embedding state helpers owned by the backend package."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from codira.contracts import StoredEmbeddingRow
from codira.semantic.embeddings import EmbeddingBackendSpec

from .duckdb_query_primitives import _backend_bytes, _backend_int

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
