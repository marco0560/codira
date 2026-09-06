"""SQLite backend-owned persistence helpers for the first-party plugin.

Responsibilities
----------------
- Hold SQLite-specific persistence helpers that do not belong to the index-planning flow.
- Provide reusable embedding-row models for SQLite backend persistence.
- Keep low-level SQLite mutation helpers package-owned behind the plugin boundary.

Design principles
-----------------
Support helpers stay deterministic and narrowly scoped to SQLite persistence so
the backend plugin can own its storage implementation without exposing SQLite
details as core responsibilities.

Architectural role
------------------
This module belongs to the **SQLite backend plugin layer** and owns the
package-local helper implementation used by the first-party SQLite backend.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from codira.contracts import (
    EmbeddingIndexingMetrics,
    EmbeddingIndexingPolicy,
    PendingEmbeddingRow,
    PreparedVectorRow,
    StoredEmbeddingRow,
    filter_embedding_rows_for_policy,
)
from codira.plugin_config import analyzer_inventory_discovery_json
from codira.semantic.embeddings import (
    embed_texts as embed_texts,
    embedding_work_batch_size,
    embeddings_enabled,
    serialize_vector,
)
from .sqlite_query_batches import _path_batches, _placeholders
from .sqlite_artifact_persistence import (
    ArtifactPersistenceRequest,
    CallRow,
    CallResolutionRequest,
    EmbeddingTextRequest,
    RefRow,
    _flush_persisted_relationship_rows,
    _persist_class_artifacts,
    _persist_declaration_artifacts,
    _persist_documentation_artifacts,
    _persist_function_artifacts,
    _persist_import_artifacts,
    _persist_module_artifacts,
    _rebuild_graph_indexes,
)
from . import sqlite_embedding_payload as _embedding_payload

__all__ = [
    "CallResolutionRequest",
    "EmbeddingTextRequest",
    "_rebuild_graph_indexes",
]

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer, VectorSetIdentity, VectorStore
    from codira.models import (
        AnalysisResult,
        FileMetadataSnapshot,
    )
    from codira.semantic.embeddings import EmbeddingBackendSpec
    from codira.types import ReferenceSearchRow

_embedding_content_hash = _embedding_payload._embedding_content_hash


def _clear_index_tables(conn: sqlite3.Connection) -> None:
    """
    Remove all indexed rows from the database tables.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to clear in place.

    Returns
    -------
    None
        The tables are cleared in place on ``conn``.
    """
    conn.execute("DELETE FROM docstring_issues")
    conn.execute("DELETE FROM call_edges")
    conn.execute("DELETE FROM callable_refs")
    conn.execute("DELETE FROM call_records")
    conn.execute("DELETE FROM callable_ref_records")
    conn.execute("DELETE FROM reference_scan_lines")
    conn.execute("DELETE FROM overloads")
    conn.execute("DELETE FROM enum_members")
    conn.execute("DELETE FROM embeddings")
    conn.execute("DELETE FROM documentation_artifacts")
    conn.execute("DELETE FROM symbol_index")
    conn.execute("DELETE FROM imports")
    conn.execute("DELETE FROM functions")
    conn.execute("DELETE FROM classes")
    conn.execute("DELETE FROM modules")
    conn.execute("DELETE FROM files")
    conn.execute("DELETE FROM analysis_status")


def _purge_skipped_docstring_issues(conn: sqlite3.Connection) -> None:
    """
    Remove persisted docstring issues for files excluded from audit policy.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to clean in place.

    Returns
    -------
    None
        Rows owned by shell-analyzed files are deleted from ``docstring_issues``.

    Notes
    -----
    Existing indexes may already contain stale shell docstring findings from
    older codira versions. Purging those rows during normal indexing keeps
    audit output aligned with the current policy without requiring a full
    rebuild of unchanged shell files.
    """
    conn.execute("""
        DELETE FROM docstring_issues
        WHERE file_id IN (
            SELECT id
            FROM files
            WHERE analyzer_name = 'bash'
               OR path LIKE '%.sh'
               OR path LIKE '%.bash'
        )
        """)


def _flush_embedding_rows(
    conn: sqlite3.Connection,
    root: Path | None = None,
    *,
    embedding_rows: list[PendingEmbeddingRow],
    backend: EmbeddingBackendSpec,
    defer_embeddings: bool = False,
    previous_embeddings: dict[str, StoredEmbeddingRow] | None = None,
    pending_embedding_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]]
    | None = None,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
) -> tuple[int, int]:
    """
    Persist pending embedding payloads for one analyzed file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    root : pathlib.Path | None, optional
        Repository root used for embedding configuration and vector-store paths.
    embedding_rows : list[codira.indexer.PendingEmbeddingRow]
        Pending embedding payloads keyed by object type and identifier.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    defer_embeddings : bool, optional
        Whether rows should be queued instead of embedded immediately.
    previous_embeddings : dict[str, codira.indexer.StoredEmbeddingRow] | None, optional
        Stored symbol embeddings keyed by stable identity before the owner file
        was replaced.
    pending_embedding_rows : list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]] | None, optional
        Session-level embedding buffer. When supplied, prepared rows are
        appended for one later backend batch.
    vector_store : codira.contracts.VectorStore | None, optional
        Active separated vector-store plugin used for materialized vectors.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object] | None, optional
        Vector-store-specific configuration table.

    Returns
    -------
    tuple[int, int]
        ``(recomputed, reused)`` embedding counts for the file.
    """
    if not embeddings_enabled(root=root):
        return (0, 0)

    recomputed = 0
    reused = 0
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]] = []

    for row in sorted(
        embedding_rows,
        key=lambda item: (item.object_type, item.object_id),
    ):
        content_hash = _embedding_content_hash(row.text)
        reusable_row = None
        if previous_embeddings is not None:
            reusable_row = previous_embeddings.get(row.stable_id)

        if (
            reusable_row is not None
            and reusable_row.content_hash == content_hash
            and reusable_row.dim == backend.dim
        ):
            prepared_rows.append((row, content_hash, None))
            recomputed += 1
        else:
            prepared_rows.append((row, content_hash, None))
            recomputed += 1

    if defer_embeddings:
        if pending_embedding_rows is not None:
            pending_embedding_rows.extend(prepared_rows)
            return (0, 0)
        _store_pending_embedding_rows(
            conn, prepared_rows=prepared_rows, backend=backend
        )
        return (0, 0)

    missing_hashes = [
        content_hash
        for row, content_hash, stored_vector in prepared_rows
        if stored_vector is None
    ]
    cached_vectors = (
        {}
        if (root is None or vector_store is None or vector_set_identity is None)
        else vector_store.load_cached_vectors(
            root,
            vector_set_identity,
            missing_hashes,
            {} if vector_store_config is None else vector_store_config,
        )
    )
    if cached_vectors:
        resolved_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]] = []
        cached_reuses = 0
        for row, content_hash, stored_vector in prepared_rows:
            if stored_vector is None and content_hash in cached_vectors:
                resolved_rows.append((row, content_hash, cached_vectors[content_hash]))
                cached_reuses += 1
            else:
                resolved_rows.append((row, content_hash, stored_vector))
        prepared_rows = resolved_rows
        recomputed -= cached_reuses
        reused += cached_reuses

    if pending_embedding_rows is not None:
        pending_embedding_rows.extend(prepared_rows)
        return (recomputed, reused)

    _flush_prepared_embedding_rows(
        conn,
        root,
        prepared_rows=prepared_rows,
        backend=backend,
        vector_store=vector_store,
        vector_set_identity=vector_set_identity,
        vector_store_config={} if vector_store_config is None else vector_store_config,
    )
    return (recomputed, reused)


def _store_pending_embedding_rows(
    conn: sqlite3.Connection,
    *,
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
) -> None:
    """
    Persist deferred embedding rows for later computation.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    root : pathlib.Path | None, optional
        Repository root used for embedding configuration and vector-store paths.
    prepared_rows : list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]]
        Prepared embedding rows as ``(row, content_hash, stored_vector)``.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    vector_store : codira.contracts.VectorStore | None, optional
        Active separated vector-store plugin used for materialized vectors.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object] | None, optional
        Vector-store-specific configuration table.

    Returns
    -------
    None
        Pending rows are inserted or replaced in place.
    """

    if not prepared_rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO pending_embeddings(
            object_type, object_id, stable_id, backend, version, content_hash, dim, text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.object_type,
                row.object_id,
                row.stable_id,
                backend.name,
                backend.version,
                content_hash,
                backend.dim,
                row.text,
            )
            for row, content_hash, _stored_vector in prepared_rows
        ],
    )


def _store_vector_store_materialized_rows(
    *,
    vector_store: VectorStore | None,
    vector_set_identity: VectorSetIdentity | None,
    vector_store_config: Mapping[str, object],
    root: Path | None,
    prepared_rows: list[PreparedVectorRow],
    encoded_vectors: dict[str, bytes],
) -> None:
    """
    Mirror materialized embedding rows into the separated vector store.

    Parameters
    ----------
    vector_store : codira.contracts.VectorStore | None
        Active vector-store plugin, when configured by the caller.
    vector_set_identity : codira.contracts.VectorSetIdentity | None
        Active vector-set identity, when configured by the caller.
    vector_store_config : collections.abc.Mapping[str, object]
        Vector-store-specific configuration table.
    root : pathlib.Path
        Repository root whose vector store should be updated.
    prepared_rows : list[codira.contracts.PreparedVectorRow]
        Materialized vector rows to persist.
    encoded_vectors : dict[str, bytes]
        Newly encoded vectors keyed by content hash.

    Returns
    -------
    None
        Vector-store cache and materialized rows are persisted when available.
    """
    if vector_store is None or vector_set_identity is None or root is None:
        return
    from codira.contracts import VectorStoreBulkWriter, VectorStoreFullIndexRequest

    if isinstance(vector_store, VectorStoreBulkWriter):
        vector_store.store_vectors_for_full_index(
            VectorStoreFullIndexRequest(
                root=root,
                identity=vector_set_identity,
                rows=prepared_rows,
                cached_vectors=encoded_vectors,
                config=vector_store_config,
                preserve_existing=True,
            )
        )
        return
    if encoded_vectors:
        vector_store.store_cached_vectors(
            root,
            vector_set_identity,
            encoded_vectors,
            vector_store_config,
        )
    vector_store.store_vectors(
        root,
        vector_set_identity,
        prepared_rows,
        vector_store_config,
    )
    vector_store.delete_pending_vectors(
        root,
        vector_set_identity,
        prepared_rows,
        vector_store_config,
    )


def _delete_pending_embedding_rows(
    conn: sqlite3.Connection,
    *,
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
) -> None:
    """
    Delete pending rows that have been materialized into embeddings.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    root : pathlib.Path | None, optional
        Repository root used for embedding configuration and vector-store paths.
    prepared_rows : list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]]
        Prepared embedding rows as ``(row, content_hash, stored_vector)``.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    vector_store : codira.contracts.VectorStore | None, optional
        Active separated vector-store plugin used for materialized vectors.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object] | None, optional
        Vector-store-specific configuration table.

    Returns
    -------
    None
        Matching pending rows are deleted in place.
    """

    if not prepared_rows:
        return
    conn.executemany(
        """
        DELETE FROM pending_embeddings
        WHERE object_type = ?
          AND object_id = ?
          AND backend = ?
          AND version = ?
        """,
        [
            (row.object_type, row.object_id, backend.name, backend.version)
            for row, _content_hash, _stored_vector in prepared_rows
        ],
    )


def _flush_prepared_embedding_rows(
    conn: sqlite3.Connection,
    root: Path | None = None,
    *,
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
) -> None:
    """
    Flush prepared embedding rows to SQLite.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    root : pathlib.Path | None, optional
        Repository root used for embedding configuration and vector-store paths.
    prepared_rows : list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]]
        Prepared embedding rows as ``(row, content_hash, stored_vector)``.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    vector_store : codira.contracts.VectorStore | None, optional
        Active separated vector-store plugin used for materialized vectors.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object] | None, optional
        Vector-store-specific configuration table.

    Returns
    -------
    None
        Prepared embedding rows are inserted in place.
    """
    if not prepared_rows:
        return
    _delete_pending_embedding_rows(conn, prepared_rows=prepared_rows, backend=backend)
    deduplicated_rows = list(
        {
            (row.object_type, row.object_id, backend.name, backend.version): (
                row,
                content_hash,
                stored_vector,
            )
            for row, content_hash, stored_vector in prepared_rows
        }.values()
    )
    encoded_vectors: dict[str, bytes] = {}
    texts_to_encode = {
        content_hash: row.text
        for row, content_hash, stored_vector in deduplicated_rows
        if stored_vector is None
    }
    if texts_to_encode:
        ordered_content_hashes = list(dict.fromkeys(texts_to_encode))
        encoded_rows = embed_texts(
            [texts_to_encode[content_hash] for content_hash in ordered_content_hashes],
            root=root,
        )
        for content_hash, vector in zip(
            ordered_content_hashes,
            encoded_rows,
            strict=True,
        ):
            encoded_vectors[content_hash] = serialize_vector(vector)
    insert_rows: list[tuple[str, int, str, str, str, int, bytes]] = []
    materialized_rows: list[PreparedVectorRow] = []
    for row, content_hash, stored_vector in deduplicated_rows:
        resolved_blob = stored_vector
        if resolved_blob is None:
            resolved_blob = encoded_vectors[content_hash]

        materialized_rows.append(
            PreparedVectorRow(
                row=row,
                content_hash=content_hash,
                vector=resolved_blob,
            )
        )
        insert_rows.append(
            (
                row.object_type,
                row.object_id,
                backend.name,
                backend.version,
                content_hash,
                backend.dim,
                b"",
            )
        )
    conn.executemany(
        """
        DELETE FROM embeddings
        WHERE object_type = ?
          AND object_id = ?
          AND backend = ?
          AND version = ?
        """,
        [
            (
                object_type,
                object_id,
                backend_name,
                backend_version,
            )
            for (
                object_type,
                object_id,
                backend_name,
                backend_version,
                _content_hash,
                _dim,
                _vector,
            ) in insert_rows
        ],
    )
    conn.executemany(
        "INSERT INTO embeddings"
        "(object_type, object_id, backend, version, content_hash, dim, vector) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        insert_rows,
    )
    _store_vector_store_materialized_rows(
        vector_store=vector_store,
        vector_set_identity=vector_set_identity,
        vector_store_config={} if vector_store_config is None else vector_store_config,
        root=root,
        prepared_rows=materialized_rows,
        encoded_vectors=encoded_vectors,
    )


def _flush_pending_embedding_rows(
    conn: sqlite3.Connection,
    root: Path | None = None,
    *,
    pending_embedding_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
) -> None:
    """
    Flush session-level embedding rows to SQLite.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    root : pathlib.Path | None, optional
        Repository root used for embedding configuration and vector-store paths.
    pending_embedding_rows : list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]]
        Session-level prepared embedding rows.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    vector_store : codira.contracts.VectorStore | None, optional
        Active separated vector-store plugin used for materialized vectors.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object] | None, optional
        Vector-store-specific configuration table.

    Returns
    -------
    None
        Pending embeddings are encoded and inserted in one backend batch.
    """
    if not pending_embedding_rows:
        return
    if not embeddings_enabled(root=root):
        pending_embedding_rows.clear()
        return
    work_batch_size = embedding_work_batch_size(root=root)
    for index in range(0, len(pending_embedding_rows), work_batch_size):
        _flush_prepared_embedding_rows(
            conn,
            root,
            prepared_rows=pending_embedding_rows[index : index + work_batch_size],
            backend=backend,
            vector_store=vector_store,
            vector_set_identity=vector_set_identity,
            vector_store_config={}
            if vector_store_config is None
            else vector_store_config,
        )
    pending_embedding_rows.clear()


def _process_pending_embedding_rows(
    conn: sqlite3.Connection,
    root: Path,
    *,
    backend: EmbeddingBackendSpec,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
) -> tuple[int, int]:
    """
    Compute all pending embeddings for one backend and version.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    root : pathlib.Path
        Repository root used for embedding configuration and vector-store paths.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    vector_store : codira.contracts.VectorStore | None, optional
        Active separated vector-store plugin used for materialized vectors.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object] | None, optional
        Vector-store-specific configuration table.

    Returns
    -------
    tuple[int, int]
        ``(recomputed, reused)`` embedding counts for processed rows.
    """

    rows = conn.execute(
        """
        SELECT object_type, object_id, stable_id, content_hash, text
        FROM pending_embeddings
        WHERE backend = ?
          AND version = ?
          AND dim = ?
        ORDER BY object_type, object_id, stable_id
        """,
        (backend.name, backend.version, backend.dim),
    ).fetchall()
    if not rows:
        return (0, 0)

    pending_rows = [
        (
            PendingEmbeddingRow(
                object_type=str(object_type),
                object_id=int(object_id),
                stable_id=str(stable_id),
                text=str(text),
            ),
            str(content_hash),
            None,
        )
        for object_type, object_id, stable_id, content_hash, text in rows
    ]
    content_hashes = [content_hash for _row, content_hash, _vector in pending_rows]
    cached_vectors = (
        {}
        if vector_store is None or vector_set_identity is None
        else vector_store.load_cached_vectors(
            root,
            vector_set_identity,
            content_hashes,
            {} if vector_store_config is None else vector_store_config,
        )
    )
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]] = []
    recomputed = 0
    reused = 0
    for row, content_hash, _stored_vector in pending_rows:
        cached_vector = cached_vectors.get(content_hash)
        if cached_vector is None:
            recomputed += 1
        else:
            reused += 1
        prepared_rows.append((row, content_hash, cached_vector))

    _flush_prepared_embedding_rows(
        conn,
        root,
        prepared_rows=prepared_rows,
        backend=backend,
        vector_store=vector_store,
        vector_set_identity=vector_set_identity,
        vector_store_config={} if vector_store_config is None else vector_store_config,
    )
    return (recomputed, reused)


def _reference_scan_rows(path: Path) -> list[ReferenceSearchRow]:
    """
    Return deterministic non-import source lines for query-time reference scans.

    Parameters
    ----------
    path : pathlib.Path
        Source file whose text should be prepared for stored reference scans.

    Returns
    -------
    list[codira.types.ReferenceSearchRow]
        Stored rows as ``(file_path, lineno, line_text)``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    file_path = str(path)
    return [
        (file_path, lineno, line)
        for lineno, line in enumerate(text.splitlines(), start=1)
        if not line.strip().startswith(("import ", "from "))
    ]


def _flush_reference_scan_rows(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    path: Path,
) -> None:
    """
    Persist the stored reference-search surface for one indexed file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    file_id : int
        Owning indexed file identifier.
    path : pathlib.Path
        Source file whose text should be stored for later query-time scans.

    Returns
    -------
    None
        Matching non-import lines are inserted in deterministic order.
    """
    reference_rows = _reference_scan_rows(path)
    if not reference_rows:
        return

    conn.executemany(
        "INSERT INTO reference_scan_lines(file_id, lineno, line_text) VALUES (?, ?, ?)",
        [
            (file_id, lineno, line_text)
            for _file_path, lineno, line_text in reference_rows
        ],
    )


def _store_analysis(
    conn: sqlite3.Connection,
    root: Path,
    file_metadata: FileMetadataSnapshot,
    analysis: AnalysisResult,
    *,
    backend: EmbeddingBackendSpec,
    embedding_indexing: EmbeddingIndexingPolicy | None = None,
    embedding_metrics: EmbeddingIndexingMetrics | None = None,
    defer_embeddings: bool = False,
    previous_embeddings: dict[str, StoredEmbeddingRow] | None = None,
    pending_embedding_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]]
    | None = None,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
) -> tuple[int, int]:
    """
    Persist one parsed file snapshot into the index.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    root : pathlib.Path
        Repository root used for embedding path filters.
    file_metadata : codira.models.FileMetadataSnapshot
        Stable file metadata for the analyzed file.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    embedding_indexing : codira.contracts.EmbeddingIndexingPolicy | None, optional
        Optional embedding row eligibility policy.
    embedding_metrics : codira.contracts.EmbeddingIndexingMetrics | None, optional
        Optional mutable counters updated for skipped embedding rows.
    defer_embeddings : bool, optional
        Whether eligible embedding rows should be queued for later computation.
    previous_embeddings : dict[str, codira.indexer.StoredEmbeddingRow] | None, optional
        Stored symbol embeddings captured before replacing file-owned rows.
    pending_embedding_rows : list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]] | None, optional
        Session-level buffer used to batch embedding generation across files.
    vector_store : codira.contracts.VectorStore | None, optional
        Active separated vector-store plugin used for materialized vectors.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object] | None, optional
        Vector-store-specific configuration table.

    Returns
    -------
    tuple[int, int]
        ``(recomputed, reused)`` embedding counts for the file.
    """
    embedding_rows: list[PendingEmbeddingRow] = []
    call_rows: list[CallRow] = []
    ref_rows: list[RefRow] = []

    cur = conn.execute(
        "INSERT INTO files"
        "(path, hash, mtime, size, analyzer_name, analyzer_version) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(file_metadata.path),
            file_metadata.sha256,
            file_metadata.mtime,
            file_metadata.size,
            file_metadata.analyzer_name,
            file_metadata.analyzer_version,
        ),
    )
    assert cur.lastrowid is not None
    file_id = int(cur.lastrowid)
    if analysis.status is not None:
        conn.execute(
            "INSERT OR REPLACE INTO analysis_status "
            "(path, grammar, target_contract, diagnostics, reliable_categories, "
            "omitted_categories, coverage_state) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(file_metadata.path),
                analysis.status.grammar,
                json.dumps(analysis.status.target_contract, sort_keys=True),
                json.dumps(
                    [diagnostic.__dict__ for diagnostic in analysis.status.diagnostics],
                    sort_keys=True,
                ),
                json.dumps(analysis.status.reliable_categories),
                json.dumps(analysis.status.omitted_categories),
                analysis.status.coverage_state.value,
            ),
        )
    if analysis.status is not None and not analysis.index_symbols:
        return (0, 0)
    _persist_documentation_artifacts(
        conn,
        file_id=file_id,
        analysis=analysis,
        embedding_rows=embedding_rows,
    )
    if not analysis.index_symbols:
        embedding_rows, skipped = filter_embedding_rows_for_policy(
            embedding_rows,
            embedding_indexing,
            root=root,
            path=file_metadata.path,
        )
        if embedding_metrics is not None:
            embedding_metrics.skipped += skipped
            if defer_embeddings:
                embedding_metrics.pending += len(embedding_rows)
        return _flush_embedding_rows(
            conn,
            root,
            embedding_rows=embedding_rows,
            backend=backend,
            defer_embeddings=defer_embeddings,
            previous_embeddings=previous_embeddings,
            pending_embedding_rows=pending_embedding_rows,
            vector_store=vector_store,
            vector_set_identity=vector_set_identity,
            vector_store_config=vector_store_config,
        )
    module_name, module_id, c_embedding_context = _persist_module_artifacts(
        conn,
        file_id=file_id,
        root=root,
        analysis=analysis,
        embedding_rows=embedding_rows,
    )
    artifact_request = ArtifactPersistenceRequest(
        conn=conn,
        file_id=file_id,
        module_id=module_id,
        module_name=module_name,
        analysis=analysis,
        c_embedding_context=c_embedding_context,
        embedding_rows=embedding_rows,
        call_rows=call_rows,
        ref_rows=ref_rows,
        root=root,
    )
    _persist_class_artifacts(artifact_request)
    _persist_function_artifacts(artifact_request)
    _persist_declaration_artifacts(artifact_request)
    _persist_import_artifacts(
        conn,
        module_id=module_id,
        analysis=analysis,
    )
    _flush_reference_scan_rows(
        conn,
        file_id=file_id,
        path=file_metadata.path,
    )
    _flush_persisted_relationship_rows(
        conn,
        call_rows=call_rows,
        ref_rows=ref_rows,
    )
    embedding_rows, skipped = filter_embedding_rows_for_policy(
        embedding_rows,
        embedding_indexing,
        root=root,
        path=file_metadata.path,
    )
    if embedding_metrics is not None:
        embedding_metrics.skipped += skipped
        if defer_embeddings:
            embedding_metrics.pending += len(embedding_rows)
    return _flush_embedding_rows(
        conn,
        root,
        embedding_rows=embedding_rows,
        backend=backend,
        defer_embeddings=defer_embeddings,
        previous_embeddings=previous_embeddings,
        pending_embedding_rows=pending_embedding_rows,
        vector_store=vector_store,
        vector_set_identity=vector_set_identity,
        vector_store_config=vector_store_config,
    )


def _persist_runtime_inventory(
    conn: sqlite3.Connection,
    *,
    backend_name: str,
    backend_version: str,
    coverage_complete: bool,
    analyzers: list[LanguageAnalyzer],
) -> None:
    """
    Persist backend and analyzer inventory for one successful index run.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    backend_name : str
        Active backend name.
    backend_version : str
        Active backend version.
    coverage_complete : bool
        Whether canonical-directory coverage had no gaps.
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Active analyzers for the run.

    Returns
    -------
    None
        Inventory rows are replaced in place on ``conn``.
    """
    conn.execute("DELETE FROM index_runtime")
    conn.execute("DELETE FROM index_analyzers")
    conn.execute(
        """
        INSERT INTO index_runtime(
            singleton,
            backend_name,
            backend_version,
            coverage_complete
        ) VALUES (?, ?, ?, ?)
        """,
        (1, backend_name, backend_version, int(coverage_complete)),
    )

    for analyzer in sorted(analyzers, key=lambda item: str(item.name)):
        conn.execute(
            """
            INSERT INTO index_analyzers(name, version, discovery_globs)
            VALUES (?, ?, ?)
            """,
            (
                str(analyzer.name),
                str(analyzer.version),
                analyzer_inventory_discovery_json(analyzer),
            ),
        )


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
    documentation_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM documentation_artifacts WHERE file_id = ?",
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
                f"DELETE FROM pending_embeddings WHERE object_type = 'symbol' "
                f"AND object_id IN ({_placeholders(symbol_ids)})",
                tuple(symbol_ids),
            )
        if documentation_ids:
            conn.execute(
                f"DELETE FROM embeddings WHERE object_type = 'documentation' "
                f"AND object_id IN ({_placeholders(documentation_ids)})",
                tuple(documentation_ids),
            )
            conn.execute(
                "DELETE FROM pending_embeddings WHERE object_type = 'documentation' "
                f"AND object_id IN ({_placeholders(documentation_ids)})",
                tuple(documentation_ids),
            )

        conn.execute(
            "DELETE FROM docstring_issues WHERE file_id = ?",
            (file_id,),
        )
        conn.execute(
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"""
            DELETE FROM overloads
            WHERE function_id IN (
                SELECT id
                FROM functions
                WHERE module_id IN ({_placeholders(module_ids)})
            )
            """,
            tuple(module_ids),
        )
        conn.execute(
            "DELETE FROM enum_members WHERE file_id = ?",
            (file_id,),
        )
        conn.execute(
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"DELETE FROM imports WHERE module_id IN ({_placeholders(module_ids)})",
            tuple(module_ids),
        )
        conn.execute(
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"DELETE FROM functions WHERE module_id IN ({_placeholders(module_ids)})",
            tuple(module_ids),
        )
        conn.execute(
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"DELETE FROM classes WHERE module_id IN ({_placeholders(module_ids)})",
            tuple(module_ids),
        )
        conn.execute(
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
    elif documentation_ids:
        conn.execute(
            f"DELETE FROM embeddings WHERE object_type = 'documentation' "
            f"AND object_id IN ({_placeholders(documentation_ids)})",
            tuple(documentation_ids),
        )
        conn.execute(
            "DELETE FROM pending_embeddings WHERE object_type = 'documentation' "
            f"AND object_id IN ({_placeholders(documentation_ids)})",
            tuple(documentation_ids),
        )

    conn.execute("DELETE FROM documentation_artifacts WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM symbol_index WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM call_edges WHERE caller_file_id = ?", (file_id,))
    conn.execute("DELETE FROM callable_refs WHERE owner_file_id = ?", (file_id,))
    conn.execute("DELETE FROM call_records WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM callable_ref_records WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM reference_scan_lines WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM files WHERE path = ?", (file_path,))
    conn.execute("DELETE FROM analysis_status WHERE path = ?", (file_path,))


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
    rows.extend(
        conn.execute(
            """
            SELECT
                d.stable_id,
                e.content_hash,
                e.dim,
                e.vector
            FROM embeddings e
            JOIN documentation_artifacts d
              ON e.object_type = 'documentation'
             AND e.object_id = d.id
            JOIN files f
              ON d.file_id = f.id
            WHERE f.path = ?
              AND e.backend = ?
              AND e.version = ?
            ORDER BY d.stable_id
            """,
            (file_path, backend.name, backend.version),
        ).fetchall()
    )
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
        "SELECT DISTINCT backend, version, dim "
        "FROM embeddings ORDER BY backend, version, dim"
    ).fetchall()
    if not rows:
        return True
    return rows == [(backend.name, backend.version, backend.dim)]


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
    conn.execute("""
        DELETE FROM embeddings
        WHERE object_type = 'documentation'
          AND object_id NOT IN (SELECT id FROM documentation_artifacts)
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


def _count_indexed_files(conn: sqlite3.Connection) -> int:
    """
    Count files currently persisted in the SQLite index.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.

    Returns
    -------
    int
        Number of rows in the indexed files table.
    """
    row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
    assert row is not None
    return int(row[0])


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

    total = 0
    for path_batch in _path_batches(reused_paths):
        placeholders = ",".join("?" for _ in path_batch)
        # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT e.id
                FROM embeddings e
                JOIN symbol_index s
                  ON e.object_type = 'symbol'
                 AND e.object_id = s.id
                JOIN files f
                  ON s.file_id = f.id
                WHERE f.path IN ({placeholders})
                UNION ALL
                SELECT e.id
                FROM embeddings e
                JOIN documentation_artifacts d
                  ON e.object_type = 'documentation'
                 AND e.object_id = d.id
                JOIN files f
                  ON d.file_id = f.id
                WHERE f.path IN ({placeholders})
            )
            """,
            (*path_batch, *path_batch),
        ).fetchone()
        assert row is not None
        total += int(row[0])
    return total
