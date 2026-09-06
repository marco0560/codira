"""DuckDB embedding row persistence owned by the backend package."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from codira.contracts import (
    BackendError,
    PendingEmbeddingRow,
    PreparedVectorIdentityRow,
    PreparedVectorRow,
    StoredEmbeddingRow,
    VectorStore,
    VectorStoreBulkWriter,
    VectorStoreFullIndexRequest,
    VectorSetIdentity,
)
from codira.semantic.embeddings import EmbeddingBackendSpec, embeddings_enabled
from .duckdb_bulk_io import _flush_registered_arrow_table
from .duckdb_embedding_payload import _embedding_content_hash
from .profiling import DuckDBProfileRecorder

if TYPE_CHECKING:
    from .duckdb_support import _DuckDBPersistenceConnection

_T = TypeVar("_T")


def _flush_embedding_rows(
    conn: _DuckDBPersistenceConnection,
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
    defer_cache_lookup: bool = False,
) -> tuple[int, int]:
    """
    Persist pending embedding payloads for one analyzed file.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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
    defer_cache_lookup : bool, optional
        Whether cache reuse should be resolved later by a bulk caller.

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

    if defer_embeddings and pending_embedding_rows is not None:
        pending_embedding_rows.extend(prepared_rows)
        return (0, 0)

    if defer_embeddings:
        _store_pending_embedding_rows(
            conn, prepared_rows=prepared_rows, backend=backend
        )
        return (0, 0)

    if pending_embedding_rows is not None and defer_cache_lookup:
        pending_embedding_rows.extend(prepared_rows)
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

    from .duckdb_support import _flush_prepared_embedding_rows

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


def _chunked_embedding_batches(
    rows: Sequence[_T],
    *,
    chunk_size: int | None = None,
) -> Iterator[Sequence[_T]]:
    """
    Yield bounded row batches for DuckDB embedding persistence.

    Parameters
    ----------
    rows : collections.abc.Sequence[_T]
        Ordered rows to split.
    chunk_size : int | None, optional
        Maximum row count per yielded batch.

    Yields
    ------
    collections.abc.Sequence[_T]
        Bounded slices of ``rows``.

    Raises
    ------
    ValueError
        Raised when ``chunk_size`` is not positive.
    """
    from .duckdb_support import _DUCKDB_EMBEDDING_BATCH_ROWS

    active_chunk_size = (
        _DUCKDB_EMBEDDING_BATCH_ROWS if chunk_size is None else chunk_size
    )
    if active_chunk_size <= 0:
        msg = f"chunk_size must be positive, got {active_chunk_size}"
        raise ValueError(msg)
    for start in range(0, len(rows), active_chunk_size):
        yield rows[start : start + active_chunk_size]


def _duckdb_batch_error_types() -> tuple[type[BaseException], ...]:
    """
    Return expected batch-write exception types for DuckDB helper operations.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[type[BaseException], ...]
        Exception classes that should be wrapped as backend persistence
        failures.
    """
    import pyarrow as pa

    try:
        import duckdb
    except ModuleNotFoundError:
        return (OSError, RuntimeError, ValueError, pa.ArrowException)
    return (OSError, RuntimeError, ValueError, pa.ArrowException, duckdb.Error)


def _embedding_batch_backend_error(
    *,
    operation: str,
    row_count: int,
    payload_bytes: int,
) -> str:
    """
    Build one operator-facing DuckDB embedding batch failure message.

    Parameters
    ----------
    operation : str
        Logical batch operation that failed.
    row_count : int
        Number of rows in the failed batch.
    payload_bytes : int
        Approximate text or vector payload size in bytes.

    Returns
    -------
    str
        Diagnostic message suitable for ``BackendError``.
    """
    return (
        f"DuckDB embedding batch operation failed: operation={operation} "
        f"rows={row_count} approx_payload_bytes={payload_bytes}. "
        "Inspect the underlying DuckDB exception for memory pressure. If the "
        "failed row count is already small, reduce transaction scope or "
        "available embedding volume before changing embedding batch size."
    )


def _pending_embedding_payload_bytes(
    prepared_rows: Sequence[tuple[PendingEmbeddingRow, str, bytes | None]],
    *,
    backend: EmbeddingBackendSpec,
) -> int:
    """
    Estimate pending-embedding batch payload bytes.

    Parameters
    ----------
    prepared_rows : collections.abc.Sequence[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]]
        Prepared embedding rows in the batch.
    backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.

    Returns
    -------
    int
        Approximate payload byte count for diagnostics.
    """
    return sum(
        len(row.object_type.encode("utf-8"))
        + len(row.stable_id.encode("utf-8"))
        + len(row.text.encode("utf-8"))
        + len(content_hash.encode("utf-8"))
        + len(backend.name.encode("utf-8"))
        + len(backend.version.encode("utf-8"))
        + (len(stored_vector) if stored_vector is not None else 0)
        for row, content_hash, stored_vector in prepared_rows
    )


def _cached_vector_payload_bytes(encoded_vectors: dict[str, bytes]) -> int:
    """
    Estimate cached-vector batch payload bytes.

    Parameters
    ----------
    encoded_vectors : dict[str, bytes]
        Serialized vectors keyed by content hash.

    Returns
    -------
    int
        Approximate payload byte count for diagnostics.
    """
    return sum(
        len(content_hash.encode("utf-8")) + len(vector)
        for content_hash, vector in encoded_vectors.items()
    )


def _store_pending_embedding_rows(
    conn: _DuckDBPersistenceConnection,
    *,
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
    profiler: DuckDBProfileRecorder | None = None,
) -> None:
    """
    Persist deferred embedding rows for later computation.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    root : pathlib.Path | None, optional
        Repository root used for embedding configuration and vector-store paths.
    prepared_rows : list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]]
        Prepared embedding rows as ``(row, content_hash, stored_vector)``.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for Arrow batch spans.

    Returns
    -------
    None
        Pending rows are inserted or replaced in place.

    Raises
    ------
    codira.contracts.BackendError
        Raised when DuckDB or Arrow rejects one pending-row batch.
    """

    if not prepared_rows:
        return

    import pyarrow as pa

    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    for batch in _chunked_embedding_batches(prepared_rows):
        object_types: list[str] = []
        object_ids: list[int] = []
        stable_ids: list[str] = []
        backends: list[str] = []
        versions: list[str] = []
        content_hashes: list[str] = []
        dims: list[int] = []
        texts: list[str] = []
        for row, content_hash, _stored_vector in batch:
            object_types.append(row.object_type)
            object_ids.append(row.object_id)
            stable_ids.append(row.stable_id)
            backends.append(backend.name)
            versions.append(backend.version)
            content_hashes.append(content_hash)
            dims.append(backend.dim)
            texts.append(row.text)

        try:
            with active_profiler.span(
                "arrow.build.pending_embeddings",
                rows=len(batch),
            ):
                table = pa.table(
                    {
                        "object_type": pa.array(object_types, type=pa.string()),
                        "object_id": pa.array(object_ids, type=pa.int64()),
                        "stable_id": pa.array(stable_ids, type=pa.string()),
                        "backend": pa.array(backends, type=pa.string()),
                        "version": pa.array(versions, type=pa.string()),
                        "content_hash": pa.array(content_hashes, type=pa.string()),
                        "dim": pa.array(dims, type=pa.int64()),
                        "text": pa.array(texts, type=pa.string()),
                    }
                )
            with active_profiler.span(
                "arrow.flush.pending_embeddings",
                rows=len(batch),
            ):
                _flush_registered_arrow_table(
                    conn,
                    view_name="__codira_pending_embedding_queue_rows",
                    table=table,
                    insert_sql="""
                        INSERT OR REPLACE INTO pending_embeddings(
                            object_type,
                            object_id,
                            stable_id,
                            backend,
                            version,
                            content_hash,
                            dim,
                            text
                        )
                        SELECT
                            object_type,
                            object_id,
                            stable_id,
                            backend,
                            version,
                            content_hash,
                            dim,
                            text
                        FROM __codira_pending_embedding_queue_rows
                        """,
                )
        except _duckdb_batch_error_types() as exc:
            msg = _embedding_batch_backend_error(
                operation="pending_embeddings_insert",
                row_count=len(batch),
                payload_bytes=_pending_embedding_payload_bytes(
                    batch,
                    backend=backend,
                ),
            )
            raise BackendError(msg) from exc


def _store_vector_store_materialized_rows(
    *,
    vector_store: VectorStore | None,
    vector_set_identity: VectorSetIdentity | None,
    vector_store_config: Mapping[str, object],
    root: Path | None,
    prepared_rows: list[PreparedVectorRow],
    identity_rows: list[PreparedVectorIdentityRow] | None = None,
    encoded_vectors: dict[str, bytes],
    backend_connection: object | None = None,
    profiler: DuckDBProfileRecorder | None = None,
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
    identity_rows : list[codira.contracts.PreparedVectorIdentityRow] | None, optional
        Complete desired materialized vector identities for full-index
        preservation.
    encoded_vectors : dict[str, bytes]
        Newly encoded vectors keyed by content hash.
    backend_connection : object | None, optional
        Backend-owned connection that compatible vector stores may reuse.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for separated vector-store spans.

    Returns
    -------
    None
        Vector-store cache and materialized rows are persisted when available.
    """
    if vector_store is None or vector_set_identity is None or root is None:
        return
    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    with active_profiler.span("vector_store.store_vectors", rows=len(prepared_rows)):
        if isinstance(vector_store, VectorStoreBulkWriter):
            vector_store.store_vectors_for_full_index(
                VectorStoreFullIndexRequest(
                    root=root,
                    identity=vector_set_identity,
                    rows=prepared_rows,
                    cached_vectors=encoded_vectors,
                    config=vector_store_config,
                    identity_rows=() if identity_rows is None else identity_rows,
                    backend_connection=backend_connection,
                    preserve_existing=True,
                )
            )
        else:
            if encoded_vectors:
                with active_profiler.span(
                    "vector_store.store_cached_vectors",
                    rows=len(encoded_vectors),
                    payload_bytes=_cached_vector_payload_bytes(encoded_vectors),
                ):
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
            with active_profiler.span(
                "vector_store.delete_pending_vectors",
                rows=len(prepared_rows),
            ):
                vector_store.delete_pending_vectors(
                    root,
                    vector_set_identity,
                    prepared_rows,
                    vector_store_config,
                )


def _delete_pending_embedding_rows(
    conn: _DuckDBPersistenceConnection,
    *,
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
    profiler: DuckDBProfileRecorder | None = None,
) -> None:
    """
    Delete pending rows that have been materialized into embeddings.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    root : pathlib.Path | None, optional
        Repository root used for embedding configuration and vector-store paths.
    prepared_rows : list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]]
        Prepared embedding rows as ``(row, content_hash, stored_vector)``.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for pending-row delete spans.

    Returns
    -------
    None
        Matching pending rows are deleted in place.

    Raises
    ------
    codira.contracts.BackendError
        Raised when DuckDB or Arrow rejects one pending-row deletion batch.
    """

    if not prepared_rows:
        return

    import pyarrow as pa

    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    for batch in _chunked_embedding_batches(prepared_rows):
        object_types: list[str] = []
        object_ids: list[int] = []
        backends: list[str] = []
        versions: list[str] = []
        for row, _content_hash, _stored_vector in batch:
            object_types.append(row.object_type)
            object_ids.append(row.object_id)
            backends.append(backend.name)
            versions.append(backend.version)

        try:
            with active_profiler.span(
                "arrow.build.pending_embedding_delete",
                rows=len(batch),
            ):
                table = pa.table(
                    {
                        "object_type": pa.array(object_types, type=pa.string()),
                        "object_id": pa.array(object_ids, type=pa.int64()),
                        "backend": pa.array(backends, type=pa.string()),
                        "version": pa.array(versions, type=pa.string()),
                    }
                )
            with active_profiler.span(
                "arrow.flush.pending_embedding_delete",
                rows=len(batch),
            ):
                _flush_registered_arrow_table(
                    conn,
                    view_name="__codira_pending_embedding_delete_rows",
                    table=table,
                    insert_sql="""
                        DELETE FROM pending_embeddings
                        USING __codira_pending_embedding_delete_rows pending
                        WHERE pending_embeddings.object_type = pending.object_type
                          AND pending_embeddings.object_id = pending.object_id
                          AND pending_embeddings.backend = pending.backend
                          AND pending_embeddings.version = pending.version
                        """,
                )
        except _duckdb_batch_error_types() as exc:
            msg = _embedding_batch_backend_error(
                operation="pending_embeddings_delete",
                row_count=len(batch),
                payload_bytes=_pending_embedding_payload_bytes(
                    batch,
                    backend=backend,
                ),
            )
            raise BackendError(msg) from exc
