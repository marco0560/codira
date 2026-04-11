"""SQLite backend support helpers shared during the packaging migration.

Responsibilities
----------------
- Hold SQLite-specific persistence helpers that do not belong to the index-planning flow.
- Provide reusable embedding-row models for SQLite backend persistence.
- Isolate low-level SQLite mutation helpers so the concrete backend can move behind a package boundary incrementally.

Design principles
-----------------
Support helpers stay deterministic and narrowly scoped to SQLite persistence so
the indexing layer can depend on one stable utility module during the Phase 2
package extraction.

Architectural role
------------------
This module belongs to the **SQLite backend support layer** used by core
indexing orchestration and the first-party SQLite backend package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

    from codira.semantic.embeddings import EmbeddingBackendSpec


@dataclass(frozen=True)
class PendingEmbeddingRow:
    """
    Pending symbol embedding payload collected during persistence.

    Parameters
    ----------
    object_type : str
        Persisted embedding owner kind.
    object_id : int
        Persisted embedding owner identifier.
    stable_id : str
        Durable analyzer-owned symbol identity.
    text : str
        Exact semantic payload that will be hashed and embedded.
    """

    object_type: str
    object_id: int
    stable_id: str
    text: str


@dataclass(frozen=True)
class StoredEmbeddingRow:
    """
    Persisted embedding row captured before file-owned rows are replaced.

    Parameters
    ----------
    stable_id : str
        Durable analyzer-owned symbol identity.
    content_hash : str
        Hash of the exact semantic payload embedded previously.
    dim : int
        Stored embedding dimensionality.
    vector : bytes
        Serialized float32 vector payload.
    """

    stable_id: str
    content_hash: str
    dim: int
    vector: bytes


def _placeholders(values: list[int]) -> str:
    """
    Build a positional placeholder string for SQL ``IN`` clauses.

    Parameters
    ----------
    values : list[int]
        Integer values that will populate the clause.

    Returns
    -------
    str
        Comma-separated ``?`` placeholders sized to ``values``.
    """
    return ",".join("?" for _ in values)


def _delete_indexed_file_data(conn: sqlite3.Connection, file_path: str) -> None:
    """
    Remove all indexed data owned by one file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    file_path : str
        Absolute file path whose indexed rows should be removed.

    Returns
    -------
    None
        The rows are deleted in place on ``conn``.
    """
    file_row = conn.execute(
        "SELECT id FROM files WHERE path = ?",
        (file_path,),
    ).fetchone()
    if file_row is None:
        return

    file_id = int(file_row[0])

    module_ids = [
        int(row[0])
        for row in conn.execute(
            """
            SELECT id
            FROM modules
            WHERE file_id = ?
            """,
            (file_id,),
        ).fetchall()
    ]
    symbol_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM symbol_index WHERE file_id = ?",
            (file_id,),
        ).fetchall()
    ]

    if module_ids:
        if symbol_ids:
            conn.execute(
                f"DELETE FROM embeddings WHERE object_type = 'symbol' "
                f"AND object_id IN ({_placeholders(symbol_ids)})",
                tuple(symbol_ids),
            )

        conn.execute(
            "DELETE FROM docstring_issues WHERE file_id = ?",
            (file_id,),
        )
        conn.execute(
            f"DELETE FROM imports WHERE module_id IN ({_placeholders(module_ids)})",
            tuple(module_ids),
        )
        conn.execute(
            f"DELETE FROM functions WHERE module_id IN ({_placeholders(module_ids)})",
            tuple(module_ids),
        )
        conn.execute(
            f"DELETE FROM classes WHERE module_id IN ({_placeholders(module_ids)})",
            tuple(module_ids),
        )
        conn.execute(
            f"DELETE FROM modules WHERE id IN ({_placeholders(module_ids)})",
            tuple(module_ids),
        )
    elif symbol_ids:
        conn.execute(
            f"DELETE FROM embeddings WHERE object_type = 'symbol' "
            f"AND object_id IN ({_placeholders(symbol_ids)})",
            tuple(symbol_ids),
        )
        conn.execute("DELETE FROM docstring_issues WHERE file_id = ?", (file_id,))

    conn.execute("DELETE FROM symbol_index WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM call_records WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM callable_ref_records WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM files WHERE path = ?", (file_path,))


def _load_previous_symbol_embeddings(
    conn: sqlite3.Connection,
    file_path: str,
    *,
    backend: EmbeddingBackendSpec,
) -> dict[str, StoredEmbeddingRow]:
    """
    Load reusable stored symbol embeddings for one indexed file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    file_path : str
        Absolute file path whose stored symbol embeddings should be loaded.
    backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.

    Returns
    -------
    dict[str, StoredEmbeddingRow]
        Stored symbol embeddings keyed by durable symbol identity.
    """
    rows = conn.execute(
        """
        SELECT
            s.stable_id,
            e.content_hash,
            e.dim,
            e.vector
        FROM embeddings e
        JOIN symbol_index s
          ON e.object_type = 'symbol'
         AND e.object_id = s.id
        JOIN files f
          ON s.file_id = f.id
        WHERE f.path = ?
          AND e.backend = ?
          AND e.version = ?
        ORDER BY s.stable_id
        """,
        (file_path, backend.name, backend.version),
    ).fetchall()
    return {
        str(stable_id): StoredEmbeddingRow(
            stable_id=str(stable_id),
            content_hash=str(content_hash),
            dim=int(dim),
            vector=bytes(vector),
        )
        for stable_id, content_hash, dim, vector in rows
    }


def _current_embedding_state_matches(
    conn: sqlite3.Connection,
    backend: EmbeddingBackendSpec,
) -> bool:
    """
    Check whether stored embeddings already match the active backend state.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.

    Returns
    -------
    bool
        ``True`` when all stored embeddings use the active backend and version.
    """
    rows = conn.execute(
        "SELECT DISTINCT backend, version FROM embeddings ORDER BY backend, version"
    ).fetchall()
    if not rows:
        return True
    return rows == [(backend.name, backend.version)]


def _prune_orphaned_embeddings(conn: sqlite3.Connection) -> None:
    """
    Remove embedding rows whose indexed symbol owner no longer exists.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.

    Returns
    -------
    None
        Orphaned embedding rows are deleted in place.
    """
    conn.execute("""
        DELETE FROM embeddings
        WHERE object_type = 'symbol'
          AND object_id NOT IN (SELECT id FROM symbol_index)
        """)


def _load_existing_file_hashes(conn: sqlite3.Connection) -> dict[str, str]:
    """
    Load indexed file hashes keyed by path.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.

    Returns
    -------
    dict[str, str]
        Indexed file hashes keyed by absolute path.
    """
    rows = conn.execute("SELECT path, hash FROM files ORDER BY path").fetchall()
    return {str(path): str(file_hash) for path, file_hash in rows}


def _load_previous_embeddings_by_path(
    conn: sqlite3.Connection,
    paths: list[str],
    *,
    backend: EmbeddingBackendSpec,
) -> dict[str, dict[str, StoredEmbeddingRow]]:
    """
    Load reusable stored symbol embeddings for the supplied file paths.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    paths : list[str]
        Absolute file paths that may be replaced during the current run.
    backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.

    Returns
    -------
    dict[str, dict[str, StoredEmbeddingRow]]
        Stored embeddings grouped by absolute file path and stable symbol
        identity.
    """
    return {
        path: _load_previous_symbol_embeddings(conn, path, backend=backend)
        for path in paths
    }


def _load_existing_file_ownership(
    conn: sqlite3.Connection,
) -> dict[str, tuple[str, str]]:
    """
    Load persisted analyzer ownership keyed by path.

    Parameters
    ----------
    conn : sqlite3.Connection
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


def _count_reused_embeddings(
    conn: sqlite3.Connection,
    reused_paths: list[str],
) -> int:
    """
    Count preserved embedding rows for unchanged files.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    reused_paths : list[str]
        Absolute file paths reused without reparsing.

    Returns
    -------
    int
        Number of embedding rows preserved for the reused files.
    """
    if not reused_paths:
        return 0

    placeholders = ",".join("?" for _ in reused_paths)
    row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM embeddings e
        JOIN symbol_index s
          ON e.object_type = 'symbol'
         AND e.object_id = s.id
        JOIN files f
          ON s.file_id = f.id
        WHERE f.path IN ({placeholders})
        """,
        tuple(reused_paths),
    ).fetchone()
    assert row is not None
    return int(row[0])
