"""First-party SQLite backend plugin package for codira.

Responsibilities
----------------
- Publish the canonical SQLite backend through the `codira.backends` entry-point group.
- Own the concrete SQLite backend implementation at the package boundary.
- Keep the package-facing backend factory explicit and deterministic.

Design principles
-----------------
The package owns the runtime backend implementation while reusing stable
storage and indexing helpers from core during the Phase 2 migration.

Architectural role
------------------
This module belongs to the **first-party backend plugin layer** introduced by
ADR-012.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, cast

from codira.contracts import (
    BackendError,
    BackendPersistAnalysisRequest,
    BackendRuntimeInventoryRequest,
    PendingEmbeddingRow,
    PreparedVectorRow,
    StoredEmbeddingRow,
)
from codira.semantic.embeddings import (
    EmbeddingBackendSpec,
    embedding_work_batch_size,
    get_embedding_backend,
)
from codira_backend_sqlite.sqlite_support import (
    _delete_indexed_file_data,
    _flush_pending_embedding_rows,
    _store_analysis,
    _store_pending_embedding_rows,
)

_SQLITE_QUERY_PARAMETER_CHUNK_SIZE = 900


def _chunks(items: Sequence[str], size: int) -> tuple[tuple[str, ...], ...]:
    """
    Split values into bounded SQLite parameter batches.

    Parameters
    ----------
    items : collections.abc.Sequence[str]
        Ordered values to split.
    size : int
        Maximum number of values per batch.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Non-empty chunks preserving input order.
    """

    return tuple(
        tuple(items[index : index + size]) for index in range(0, len(items), size)
    )


if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence
    from pathlib import Path

    from codira.contracts import (
        VectorSetIdentity,
        VectorStore,
    )

    from . import SQLiteIndexBackend

CallEdgeRow = tuple[str, str, str | None, str | None, str | None, str | None, int]
CallableRefRow = tuple[str, str, str | None, str | None, str | None, str | None, int]
EmbeddingInventoryRow = tuple[str, str, int, int]


class _SQLiteIndexWriteSession:
    """
    SQLite-backed write session for one indexing run.

    Parameters
    ----------
    backend : SQLiteIndexBackend
        Backend instance that owns the session.
    root : pathlib.Path
        Repository root whose backend state will be mutated.
    """

    def __init__(self, backend: "SQLiteIndexBackend", root: Path) -> None:
        self._backend = backend
        self._root = root
        self._conn = backend.open_connection(root)
        self._closed = False
        self._completed = False
        self._pending_embedding_rows: list[
            tuple[PendingEmbeddingRow, str, bytes | None]
        ] = []
        self._pending_embedding_rows_deferred = False
        self._embedding_backend: EmbeddingBackendSpec | None = None
        self._vector_store: VectorStore | None = None
        self._vector_set_identity: VectorSetIdentity | None = None
        self._vector_store_config: Mapping[str, object] = {}

    def purge_skipped_docstring_issues(self) -> None:
        """
        Remove stale diagnostics for files excluded from docstring auditing.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Matching persisted issues are removed in place.
        """
        self._backend.purge_skipped_docstring_issues(self._root, conn=self._conn)

    def prune_orphaned_embeddings(self) -> None:
        """
        Remove embedding rows whose owning symbols no longer exist.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Orphaned embedding rows are removed in place.
        """
        self._backend.prune_orphaned_embeddings(self._root, conn=self._conn)

    def load_existing_file_hashes(self) -> dict[str, str]:
        """
        Return persisted file hashes used for incremental planning.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, str]
            Indexed file hashes keyed by absolute path.
        """
        return self._backend.load_existing_file_hashes(self._root, conn=self._conn)

    def load_existing_file_ownership(self) -> dict[str, tuple[str, str]]:
        """
        Return persisted analyzer ownership keyed by absolute path.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, tuple[str, str]]
            Stored analyzer name and version keyed by absolute path.
        """
        return self._backend.load_existing_file_ownership(self._root, conn=self._conn)

    def current_embedding_state_matches(
        self,
        embedding_backend: EmbeddingBackendSpec,
    ) -> bool:
        """
        Report whether persisted embeddings match the active backend.

        Parameters
        ----------
        embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
            Active embedding backend metadata.

        Returns
        -------
        bool
            ``True`` when persisted embeddings remain reusable.
        """
        return self._backend.current_embedding_state_matches(
            self._root,
            embedding_backend=embedding_backend,
            conn=self._conn,
        )

    def load_previous_embeddings_by_path(
        self,
        *,
        paths: Sequence[str],
        embedding_backend: EmbeddingBackendSpec,
    ) -> dict[str, dict[str, StoredEmbeddingRow]]:
        """
        Load reusable embeddings for files selected for replacement.

        Parameters
        ----------
        paths : collections.abc.Sequence[str]
            Absolute file paths being replaced by the current run.
        embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
            Active embedding backend metadata.

        Returns
        -------
        dict[str, dict[str, codira.contracts.StoredEmbeddingRow]]
            Reusable embeddings grouped by absolute file path.
        """
        return self._backend.load_previous_embeddings_by_path(
            self._root,
            paths=list(paths),
            embedding_backend=embedding_backend,
            conn=self._conn,
        )

    def count_reusable_embeddings(self, *, paths: Sequence[str]) -> int:
        """
        Count embeddings preserved for unchanged files.

        Parameters
        ----------
        paths : collections.abc.Sequence[str]
            Absolute file paths reused without reparsing.

        Returns
        -------
        int
            Number of reusable embedding rows.
        """
        return self._backend.count_reusable_embeddings(
            self._root,
            paths=list(paths),
            conn=self._conn,
        )

    def prepare(
        self,
        *,
        full: bool,
        indexed_paths: Sequence[str],
        deleted_paths: Sequence[str],
    ) -> None:
        """
        Delete persisted rows that the current index run will replace.

        Parameters
        ----------
        full : bool
            Whether the current run is a full rebuild.
        indexed_paths : collections.abc.Sequence[str]
            Absolute file paths selected for reindexing.
        deleted_paths : collections.abc.Sequence[str]
            Absolute file paths removed from the repository.

        Returns
        -------
        None
            Matching persisted rows are removed in place.
        """
        if full:
            self._backend.clear_index(self._root, conn=self._conn)
            return
        self._backend.delete_paths(
            self._root,
            paths=sorted(set(indexed_paths) | set(deleted_paths)),
            conn=self._conn,
        )

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Persist one analyzed file through the shared SQLite session.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request for one analyzed file snapshot.

        Returns
        -------
        tuple[int, int]
            ``(recomputed, reused)`` embedding counts for the file.

        Raises
        ------
        BackendError
            If SQLite rejects persistence for the analyzed file.
        OSError
            If file-backed persistence fails while storing analyzed artifacts.
        RuntimeError
            If embedding persistence cannot complete for the analyzed file.
        ValueError
            If validated persistence inputs are semantically inconsistent.
        """
        active_backend = (
            get_embedding_backend(root=request.root)
            if request.embedding_backend is None
            else request.embedding_backend
        )
        if self._embedding_backend is None:
            self._embedding_backend = active_backend
        elif (
            self._embedding_backend != active_backend
            or self._pending_embedding_rows_deferred != request.defer_embeddings
        ):
            self._flush_pending_embeddings()
            self._embedding_backend = active_backend
        self._pending_embedding_rows_deferred = request.defer_embeddings
        self._vector_store = request.vector_store
        self._vector_set_identity = request.vector_set_identity
        self._vector_store_config = request.vector_store_config

        try:
            result = _store_analysis(
                self._conn,
                request.root,
                request.file_metadata,
                request.analysis,
                backend=active_backend,
                embedding_indexing=request.embedding_indexing,
                embedding_metrics=request.embedding_metrics,
                defer_embeddings=request.defer_embeddings,
                previous_embeddings=cast(
                    "dict[str, StoredEmbeddingRow] | None",
                    request.previous_embeddings,
                ),
                pending_embedding_rows=self._pending_embedding_rows,
                vector_store=request.vector_store,
                vector_set_identity=request.vector_set_identity,
                vector_store_config=request.vector_store_config,
            )
            self._flush_pending_embeddings_if_needed()
            return result
        except sqlite3.Error as exc:
            _delete_indexed_file_data(self._conn, str(request.file_metadata.path))
            msg = str(exc)
            raise BackendError(msg) from exc
        except (OSError, RuntimeError, ValueError):
            _delete_indexed_file_data(self._conn, str(request.file_metadata.path))
            raise

    def _flush_pending_embeddings_if_needed(self) -> None:
        """
        Flush session-level embedding rows when the work segment is full.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Buffered embedding rows are flushed when they reach the configured
            work-segment size.
        """
        if len(self._pending_embedding_rows) < embedding_work_batch_size(
            root=self._root
        ):
            return
        self._flush_pending_embeddings()

    def _flush_pending_embeddings(self) -> None:
        """
        Flush pending session-level embedding rows.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Buffered embedding rows are encoded and inserted in place.
        """
        if not self._pending_embedding_rows:
            return
        backend = self._embedding_backend
        if backend is None:
            backend = get_embedding_backend(root=self._root)
            self._embedding_backend = backend
        if self._pending_embedding_rows_deferred:
            self._store_deferred_vector_rows()
            _store_pending_embedding_rows(
                self._conn,
                prepared_rows=self._pending_embedding_rows,
                backend=backend,
            )
        else:
            _flush_pending_embedding_rows(
                self._conn,
                self._root,
                pending_embedding_rows=self._pending_embedding_rows,
                backend=backend,
                vector_store=self._vector_store,
                vector_set_identity=self._vector_set_identity,
                vector_store_config=self._vector_store_config,
            )
        self._pending_embedding_rows = []

    def _store_deferred_vector_rows(self) -> None:
        """
        Mirror buffered deferred embedding rows into the separated vector store.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Pending vector rows are persisted when vector-store context exists.
        """
        if (
            self._vector_store is None
            or self._vector_set_identity is None
            or not self._pending_embedding_rows
        ):
            return
        self._vector_store.store_pending_vectors(
            self._root,
            self._vector_set_identity,
            [
                PreparedVectorRow(
                    row=row,
                    content_hash=content_hash,
                    vector=stored_vector,
                )
                for row, content_hash, stored_vector in self._pending_embedding_rows
            ],
            self._vector_store_config,
        )

    def rebuild_derived_indexes(self) -> None:
        """
        Refresh derived backend tables after file persistence.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Derived backend state is refreshed in place.
        """
        self._flush_pending_embeddings()
        self._backend.rebuild_derived_indexes(self._root, conn=self._conn)

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Persist backend and analyzer inventory for the completed run.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory request for the completed index run.

        Returns
        -------
        None
            Runtime inventory rows are replaced in place.
        """
        self._backend.persist_runtime_inventory(
            BackendRuntimeInventoryRequest(
                root=request.root,
                backend_name=request.backend_name,
                backend_version=request.backend_version,
                coverage_complete=request.coverage_complete,
                analyzers=request.analyzers,
                conn=self._conn,
            )
        )

    def commit(self) -> None:
        """
        Commit pending writes for the current indexing session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Pending writes are committed once per session.
        """
        if not self._completed:
            self._flush_pending_embeddings()
            self._backend.commit(self._root, conn=self._conn)
            self._completed = True

    def abort(self) -> None:
        """
        Roll back pending writes for the current indexing session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Uncommitted writes are discarded when the session is still active.
        """
        if self._completed or self._closed:
            return
        self._conn.rollback()

    def close(self) -> None:
        """
        Close resources owned by the current indexing session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The shared SQLite connection is closed once per session.
        """
        if self._closed:
            return
        self._backend.close_connection(self._conn)
        self._closed = True
