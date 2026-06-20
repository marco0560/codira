"""First-party DuckDB backend plugin package for codira.

Responsibilities
----------------
- Publish the canonical DuckDB backend through the `codira.backends` entry-point group.
- Own the concrete DuckDB backend implementation at the package boundary.
- Keep the package-facing backend factory explicit and deterministic.

Design principles
-----------------
The package mirrors the SQLite backend contract while keeping DuckDB-specific
storage initialization and connection behavior local to the package.

Architectural role
------------------
This module belongs to the **first-party backend plugin layer** and provides
the production DuckDB backend introduced by issue `#10`.
"""

from __future__ import annotations

import importlib
import json
import re
from typing import TYPE_CHECKING, Protocol, cast

from codira.contracts import (
    BackendError,
    BackendPersistAnalysisRequest,
    BackendRuntimeInventoryRequest,
    PendingEmbeddingRow,
    PreparedVectorRow,
    StoredEmbeddingRow,
)
from .duckdb_support import (
    CallRow,
    DuckDBIdAllocator,
    DuckDBStructuralRowBuffers,
    RefRow,
    _DuckDBPersistenceConnection,
    _delete_indexed_file_data,
    _flush_docstring_issue_rows,
    _flush_import_rows,
    _flush_pending_embedding_rows,
    _flush_pending_reference_scan_rows,
    _flush_pending_relationship_rows,
    _flush_structural_rows,
    _process_pending_embedding_rows,
    _store_analysis,
    _store_pending_embedding_rows,
)
from .repo_storage import get_codira_dir, get_metadata_path
from .duckdb_query_backend import (
    _BackendCompatibleConnectionAdapter,
    DuckDBQueryBackend,
)
from codira.schema import DDL, SCHEMA_VERSION
from codira.semantic.embeddings import EmbeddingBackendSpec, get_embedding_backend
from codira.plugin_config import analyzer_inventory_discovery_json, plugin_json_schema

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence
    from pathlib import Path

    from codira.contracts import (
        IndexBackend,
        IndexWriteSession,
        VectorSetIdentity,
        VectorStore,
    )

PACKAGE_VERSION = "1.49.0"
_SAFE_SQL_IDENTIFIER_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$", re.IGNORECASE)
_INDEX_NAME_PATTERN = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
_SEQUENCED_TABLES: tuple[str, ...] = (
    "files",
    "modules",
    "classes",
    "functions",
    "imports",
    "overloads",
    "enum_members",
    "docstring_issues",
    "symbol_index",
    "documentation_artifacts",
    "embeddings",
)
_TABLE_ID_SEQUENCE: dict[str, str] = {
    table: f"{table}_id_seq" for table in _SEQUENCED_TABLES
}
_INDEX_DATA_TABLES: tuple[str, ...] = (
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
)
_SEQUENCE_REWRITE_PREFIXES: tuple[str, ...] = tuple(
    f"CREATE TABLE IF NOT EXISTS {table} (" for table in _SEQUENCED_TABLES
)
_CALL_EDGES_TABLE_PREFIX = "CREATE TABLE IF NOT EXISTS call_edges ("
_CALLABLE_REFS_TABLE_PREFIX = "CREATE TABLE IF NOT EXISTS callable_refs ("
_EMBEDDINGS_TABLE_PREFIX = "CREATE TABLE IF NOT EXISTS embeddings ("
_DUCKDB_CALL_EDGES_DDL = """
    CREATE TABLE IF NOT EXISTS call_edges (
        caller_file_id INTEGER NOT NULL,
        caller_module TEXT NOT NULL,
        caller_name TEXT NOT NULL,
        callee_module TEXT,
        callee_name TEXT,
        unresolved_identity TEXT NOT NULL DEFAULT '',
        external_target_kind TEXT,
        external_target_name TEXT,
        resolved INTEGER NOT NULL,
        FOREIGN KEY(caller_file_id) REFERENCES files(id)
    );
"""
_DUCKDB_CALLABLE_REFS_DDL = """
    CREATE TABLE IF NOT EXISTS callable_refs (
        owner_file_id INTEGER NOT NULL,
        owner_module TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        target_module TEXT,
        target_name TEXT,
        unresolved_identity TEXT NOT NULL DEFAULT '',
        external_target_kind TEXT,
        external_target_name TEXT,
        resolved INTEGER NOT NULL,
        FOREIGN KEY(owner_file_id) REFERENCES files(id)
    );
"""
_DUCKDB_EMBEDDINGS_DDL = """
    CREATE TABLE IF NOT EXISTS embeddings (
        id INTEGER PRIMARY KEY DEFAULT nextval('embeddings_id_seq'),
        object_type TEXT NOT NULL,
        object_id INTEGER NOT NULL,
        backend TEXT NOT NULL,
        version TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        dim INTEGER NOT NULL,
        vector BLOB NOT NULL,
        vector_values DOUBLE[]
    );
"""
_DUCKDB_SYMBOL_DETAIL_INDEX_DDL = (
    """
    CREATE INDEX IF NOT EXISTS idx_duckdb_modules_file_name
    ON modules(file_id, name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_duckdb_functions_symbol_detail
    ON functions(name, lineno, is_method, module_id);
    """,
)
_NULLABLE_EDGE_TABLE_REWRITES: dict[
    str, tuple[str, tuple[str, ...], tuple[str, ...]]
] = {
    "call_edges": (
        _DUCKDB_CALL_EDGES_DDL,
        (
            "caller_file_id",
            "caller_module",
            "caller_name",
            "callee_module",
            "callee_name",
            "unresolved_identity",
            "external_target_kind",
            "external_target_name",
            "resolved",
        ),
        (
            "idx_call_edges_identity",
            "idx_call_edges_caller",
            "idx_call_edges_caller_lookup",
            "idx_call_edges_callee",
            "idx_call_edges_callee_lookup",
            "idx_call_edges_resolved",
        ),
    ),
    "callable_refs": (
        _DUCKDB_CALLABLE_REFS_DDL,
        (
            "owner_file_id",
            "owner_module",
            "owner_name",
            "target_module",
            "target_name",
            "unresolved_identity",
            "external_target_kind",
            "external_target_name",
            "resolved",
        ),
        (
            "idx_callable_refs_identity",
            "idx_callable_refs_owner",
            "idx_callable_refs_owner_lookup",
            "idx_callable_refs_target",
            "idx_callable_refs_target_lookup",
            "idx_callable_refs_resolved",
        ),
    ),
}


class _DuckDBIndexWriteSession:
    """
    DuckDB-backed write session for one indexing run.

    Parameters
    ----------
    backend : DuckDBIndexBackend
        Backend instance that owns the session.
    root : pathlib.Path
        Repository root whose backend state will be mutated.
    """

    def __init__(self, backend: DuckDBIndexBackend, root: Path) -> None:
        self._backend = backend
        self._root = root
        if not _duckdb_db_path(root).exists():
            backend.initialize(root)
        self._conn = backend.open_connection(root)
        raw = cast("DuckDBConnection", self._conn)._raw
        _repair_nullable_edge_tables(raw)
        self._conn.execute("BEGIN TRANSACTION")
        persistence_conn = cast("_DuckDBPersistenceConnection", self._conn)
        self._transaction_open = True
        self._closed = False
        self._completed = False
        self._deferred_schema_indexes = False
        self._id_allocator = DuckDBIdAllocator(persistence_conn)
        self._structural_rows = DuckDBStructuralRowBuffers()
        self._pending_embedding_rows: list[
            tuple[PendingEmbeddingRow, str, bytes | None]
        ] = []
        self._pending_embedding_rows_deferred = False
        self._embedding_backend: EmbeddingBackendSpec | None = None
        self._vector_store: VectorStore | None = None
        self._vector_set_identity: VectorSetIdentity | None = None
        self._vector_store_config: Mapping[str, object] = {}
        self._pending_reference_scan_rows: list[tuple[int, int, str]] = []
        self._pending_call_rows: list[CallRow] = []
        self._pending_ref_rows: list[RefRow] = []
        self._pending_import_rows: list[tuple[int, str, str | None, str, int]] = []
        self._pending_docstring_issue_rows: list[
            tuple[int, int | None, int | None, int | None, str, str]
        ] = []

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
            _drop_duckdb_schema_indexes(self._conn)
            _recreate_duckdb_index_tables(self._conn)
            persistence_conn = cast("_DuckDBPersistenceConnection", self._conn)
            self._id_allocator = DuckDBIdAllocator(persistence_conn)
            self._structural_rows = DuckDBStructuralRowBuffers()
            self._pending_embedding_rows = []
            self._pending_embedding_rows_deferred = False
            self._pending_reference_scan_rows = []
            self._pending_call_rows = []
            self._pending_ref_rows = []
            self._pending_import_rows = []
            self._pending_docstring_issue_rows = []
            self._deferred_schema_indexes = True
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
        Persist one analyzed file through the shared DuckDB session.

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
            If DuckDB rejects persistence for the analyzed file.
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

        duckdb_error = _duckdb_module().Error
        try:
            return _store_analysis(
                cast("_DuckDBPersistenceConnection", self._conn),
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
                pending_reference_scan_rows=self._pending_reference_scan_rows,
                pending_call_rows=self._pending_call_rows,
                pending_ref_rows=self._pending_ref_rows,
                pending_import_rows=self._pending_import_rows,
                pending_docstring_issue_rows=self._pending_docstring_issue_rows,
                structural_rows=self._structural_rows,
                id_allocator=self._id_allocator,
            )
        except duckdb_error as exc:
            _delete_indexed_file_data(
                cast("_DuckDBPersistenceConnection", self._conn),
                str(request.file_metadata.path),
            )
            msg = str(exc)
            raise BackendError(msg) from exc
        except (OSError, RuntimeError, ValueError):
            _delete_indexed_file_data(
                cast("_DuckDBPersistenceConnection", self._conn),
                str(request.file_metadata.path),
            )
            raise

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
                cast("_DuckDBPersistenceConnection", self._conn),
                prepared_rows=self._pending_embedding_rows,
                backend=backend,
            )
        else:
            _flush_pending_embedding_rows(
                cast("_DuckDBPersistenceConnection", self._conn),
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

    def _flush_structural_rows(self) -> None:
        """
        Flush pending session-level structural rows.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Buffered structural rows are inserted in dependency order.
        """
        _flush_structural_rows(
            cast("_DuckDBPersistenceConnection", self._conn),
            self._structural_rows,
        )

    def _flush_pending_imports(self) -> None:
        """
        Flush pending session-level import rows.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Buffered import rows are inserted in place.
        """
        if not self._pending_import_rows:
            return
        _flush_import_rows(
            cast("_DuckDBPersistenceConnection", self._conn),
            self._pending_import_rows,
        )
        self._pending_import_rows = []

    def _flush_pending_docstring_issues(self) -> None:
        """
        Flush pending session-level docstring issue rows.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Buffered docstring issue rows are inserted in place.
        """
        if not self._pending_docstring_issue_rows:
            return
        _flush_docstring_issue_rows(
            cast("_DuckDBPersistenceConnection", self._conn),
            self._pending_docstring_issue_rows,
        )
        self._pending_docstring_issue_rows = []

    def _flush_non_embedding_buffers(self) -> None:
        """
        Flush session-level buffers that are independent of embedding rows.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Structural, import, diagnostic, reference-scan, and relationship
            buffers are inserted in dependency order.
        """
        self._flush_structural_rows()
        self._flush_pending_imports()
        self._flush_pending_docstring_issues()
        _flush_pending_reference_scan_rows(
            cast("_DuckDBPersistenceConnection", self._conn),
            self._pending_reference_scan_rows,
        )
        self._pending_reference_scan_rows = []
        _flush_pending_relationship_rows(
            cast("_DuckDBPersistenceConnection", self._conn),
            pending_call_rows=self._pending_call_rows,
            pending_ref_rows=self._pending_ref_rows,
        )
        self._pending_call_rows = []
        self._pending_ref_rows = []

    def _begin_transaction(self) -> None:
        """
        Open a fresh DuckDB transaction for the session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The session transaction state is marked open after `BEGIN`.
        """
        self._conn.execute("BEGIN TRANSACTION")
        self._transaction_open = True

    def _commit_transaction(self) -> None:
        """
        Commit the active DuckDB transaction for the session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Pending writes are committed and the session transaction state is
            marked closed.
        """
        self._backend.commit(self._root, conn=self._conn)
        self._transaction_open = False

    def _rollback_transaction(self) -> None:
        """
        Roll back the active DuckDB transaction for the session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The session transaction state is marked closed after rollback.
        """
        self._conn.execute("ROLLBACK")
        self._transaction_open = False

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
        self._flush_non_embedding_buffers()
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

        Raises
        ------
        BaseException
            Propagates DuckDB or helper failures after rolling back the active
            split transaction when possible.
        """
        if not self._completed and self._transaction_open:
            if self._deferred_schema_indexes:
                self._flush_non_embedding_buffers()
                self._commit_transaction()
                self._begin_transaction()
                try:
                    self._flush_pending_embeddings()
                except BaseException:
                    self._rollback_transaction()
                    raise
                self._commit_transaction()
                try:
                    _create_duckdb_schema_indexes(self._conn)
                except BaseException:
                    self._begin_transaction()
                    raise
                else:
                    self._deferred_schema_indexes = False
            else:
                self._flush_non_embedding_buffers()
                self._flush_pending_embeddings()
                self._commit_transaction()
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
        if self._completed or self._closed or not self._transaction_open:
            return
        self._rollback_transaction()

    def close(self) -> None:
        """
        Close resources owned by the current indexing session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The shared DuckDB connection is closed once per session.
        """
        if self._closed:
            return
        self._backend.close_connection(self._conn)
        self._closed = True


class _DuckDBRawConnection(Protocol):
    """DuckDB connection surface used by the backend wrapper."""

    def execute(self, query: str, parameters: Sequence[object] | None = None) -> object:
        """
        Execute one SQL statement.

        Parameters
        ----------
        query : str
            SQL statement to execute.
        parameters : Sequence[object] | None, optional
            Positional parameters bound to ``query``.

        Returns
        -------
        object
            Driver-specific execution result.
        """

    def register(self, view_name: str, python_object: object) -> object:
        """
        Register a Python object as a DuckDB replacement scan.

        Parameters
        ----------
        view_name : str
            Temporary replacement-scan name.
        python_object : object
            Object accepted by DuckDB's Python replacement-scan API.

        Returns
        -------
        object
            Driver-specific execution result.
        """

    def unregister(self, view_name: str) -> object:
        """
        Unregister a DuckDB replacement scan.

        Parameters
        ----------
        view_name : str
            Temporary replacement-scan name to remove.

        Returns
        -------
        object
            Driver-specific execution result.
        """

    def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[object]],
    ) -> object:
        """
        Execute one statement against many parameter rows.

        Parameters
        ----------
        query : str
            SQL statement to execute repeatedly.
        parameters : Sequence[Sequence[object]]
            Parameter rows bound to ``query``.

        Returns
        -------
        object
            Driver-specific execution result.
        """

    def fetchone(self) -> tuple[object, ...] | None:
        """
        Fetch one row from the most recent result.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[object, ...] | None
            Next available row, or ``None`` when the result is exhausted.
        """

    def fetchall(self) -> list[tuple[object, ...]]:
        """
        Fetch all rows from the most recent result.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[object, ...]]
            Remaining result rows.
        """
        ...

    def commit(self) -> None:
        """
        Commit the current transaction.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The active transaction is committed in place.
        """
        ...

    def close(self) -> None:
        """
        Close the active connection.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The active connection is closed in place.
        """
        ...


class _DuckDBModule(Protocol):
    """DuckDB module surface used for lazy dependency loading."""

    Error: type[BaseException]

    def connect(self, database: str) -> _DuckDBRawConnection:
        """
        Open one persistent DuckDB database.

        Parameters
        ----------
        database : str
            Database path passed to the DuckDB driver.

        Returns
        -------
        _DuckDBRawConnection
            Open raw DuckDB connection handle.
        """
        ...


class _DuckDBCursorWrapper:
    """Minimal DB-API-like cursor wrapper with `lastrowid` support."""

    def __init__(
        self,
        raw: _DuckDBRawConnection,
        *,
        lastrowid: int | None = None,
    ) -> None:
        self._raw = raw
        self.lastrowid = lastrowid

    def fetchone(self) -> tuple[object, ...] | None:
        """
        Return the next result row from the wrapped DuckDB connection.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[object, ...] | None
            Next available row or ``None`` when the result is exhausted.
        """
        return self._raw.fetchone()

    def fetchall(self) -> list[tuple[object, ...]]:
        """
        Return every remaining result row from the wrapped connection.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[object, ...]]
            Remaining result rows.
        """
        return self._raw.fetchall()


class _DuckDBCursorCompatibilityAdapter:
    """Cursor-style adapter for query paths that call ``conn.cursor()``."""

    def __init__(self, raw: _DuckDBRawConnection) -> None:
        self._raw = raw

    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
    ) -> _DuckDBCursorCompatibilityAdapter:
        """
        Execute one query through the compatibility cursor adapter.

        Parameters
        ----------
        query : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[object] | None, optional
            Positional parameters for the statement.

        Returns
        -------
        _DuckDBCursorCompatibilityAdapter
            The current cursor adapter so callers can fetch from it directly.
        """
        if parameters is None:
            self._raw.execute(query)
        else:
            self._raw.execute(query, parameters)
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        """
        Return the next row from the active cursor result.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[object, ...] | None
            Next result row or ``None`` when exhausted.
        """
        return self._raw.fetchone()

    def fetchall(self) -> list[tuple[object, ...]]:
        """
        Return every remaining row from the active cursor result.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[object, ...]]
            Remaining result rows.
        """
        return self._raw.fetchall()


class DuckDBConnection:
    """Connection adapter exposing the subset used by codira helpers."""

    def __init__(self, raw: _DuckDBRawConnection) -> None:
        self._raw = raw

    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
    ) -> _DuckDBCursorWrapper:
        """
        Execute one SQL statement and expose a cursor-like wrapper.

        Parameters
        ----------
        query : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[object] | None, optional
            Positional parameters for the statement.

        Returns
        -------
        _DuckDBCursorWrapper
            Cursor wrapper exposing fetch methods and `lastrowid` when
            applicable.
        """
        if parameters is None:
            self._raw.execute(query)
        else:
            self._raw.execute(query, parameters)
        return _DuckDBCursorWrapper(self._raw)

    def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[object]],
    ) -> _DuckDBCursorWrapper:
        """
        Execute one SQL statement against many parameter rows.

        Parameters
        ----------
        query : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[collections.abc.Sequence[object]]
            Parameter rows for the statement.

        Returns
        -------
        _DuckDBCursorWrapper
            Cursor wrapper over the most recent execution.
        """
        self._raw.executemany(query, parameters)
        return _DuckDBCursorWrapper(self._raw)

    def register(self, view_name: str, python_object: object) -> _DuckDBCursorWrapper:
        """
        Register a Python object as a DuckDB replacement scan.

        Parameters
        ----------
        view_name : str
            Temporary replacement-scan name.
        python_object : object
            Object accepted by DuckDB's Python replacement-scan API.

        Returns
        -------
        _DuckDBCursorWrapper
            Cursor wrapper over the most recent driver state.
        """
        self._raw.register(view_name, python_object)
        return _DuckDBCursorWrapper(self._raw)

    def unregister(self, view_name: str) -> _DuckDBCursorWrapper:
        """
        Unregister a DuckDB replacement scan.

        Parameters
        ----------
        view_name : str
            Temporary replacement-scan name to remove.

        Returns
        -------
        _DuckDBCursorWrapper
            Cursor wrapper over the most recent driver state.
        """
        self._raw.unregister(view_name)
        return _DuckDBCursorWrapper(self._raw)

    def cursor(self) -> _DuckDBCursorCompatibilityAdapter:
        """
        Return a DB-API-like cursor adapter for compatibility call sites.

        Parameters
        ----------
        None

        Returns
        -------
        _DuckDBCursorCompatibilityAdapter
            Cursor adapter that exposes the execute and fetch methods expected
            by query paths that explicitly request ``conn.cursor()``.
        """
        return _DuckDBCursorCompatibilityAdapter(self._raw)

    def commit(self) -> None:
        """
        Commit the active DuckDB transaction.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Pending writes are committed.
        """
        self._raw.commit()

    def close(self) -> None:
        """
        Close the active DuckDB connection.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The wrapped connection is closed.
        """
        self._raw.close()


def _duckdb_module() -> _DuckDBModule:
    """
    Return the lazily imported DuckDB Python module.

    Parameters
    ----------
    None

    Returns
    -------
    _DuckDBModule
        Imported DuckDB module.

    Raises
    ------
    codira.contracts.BackendError
        If the optional DuckDB dependency is not installed.
    """
    try:
        module = importlib.import_module("duckdb")
    except ModuleNotFoundError as exc:
        msg = (
            "DuckDB backend requires the optional `duckdb` package. "
            "Install `codira-backend-duckdb` with its declared dependencies."
        )
        raise BackendError(msg) from exc
    return cast("_DuckDBModule", module)


def _validated_sql_identifier(identifier: str, *, kind: str) -> str:
    """
    Validate one internal DuckDB identifier before SQL interpolation.

    Parameters
    ----------
    identifier : str
        Internal identifier name that will be interpolated into SQL text.
    kind : str
        Human-readable identifier class used in error messages.

    Returns
    -------
    str
        The validated identifier.

    Raises
    ------
    ValueError
        Raised when ``identifier`` contains characters outside the internal
        identifier allowlist.
    """
    if not _SAFE_SQL_IDENTIFIER_PATTERN.fullmatch(identifier):
        msg = f"Unsafe DuckDB {kind} identifier: {identifier!r}"
        raise ValueError(msg)
    return identifier


def _duckdb_db_path(root: Path) -> Path:
    """
    Return the DuckDB database path for one repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to the `index.duckdb` file under `.codira`.
    """
    return get_codira_dir(root) / "index.duckdb"


def _rewrite_duckdb_ddl(statement: str) -> str:
    """
    Rewrite one canonical schema statement for DuckDB sequence-backed IDs.

    Parameters
    ----------
    statement : str
        Canonical schema DDL statement.

    Returns
    -------
    str
        DuckDB-compatible statement.
    """
    if _CALL_EDGES_TABLE_PREFIX in statement:
        return _strip_foreign_key_constraints(_DUCKDB_CALL_EDGES_DDL)

    if _CALLABLE_REFS_TABLE_PREFIX in statement:
        return _strip_foreign_key_constraints(_DUCKDB_CALLABLE_REFS_DDL)

    if _EMBEDDINGS_TABLE_PREFIX in statement:
        return _strip_foreign_key_constraints(_DUCKDB_EMBEDDINGS_DDL)

    for table, prefix in zip(
        _SEQUENCED_TABLES, _SEQUENCE_REWRITE_PREFIXES, strict=True
    ):
        if prefix in statement:
            return _strip_foreign_key_constraints(
                statement.replace(
                    "id INTEGER PRIMARY KEY,",
                    f"id INTEGER PRIMARY KEY DEFAULT nextval('{_TABLE_ID_SEQUENCE[table]}'),",
                    1,
                )
            )
    return _strip_foreign_key_constraints(statement)


def _strip_foreign_key_constraints(statement: str) -> str:
    """
    Remove foreign-key constraints from DuckDB physical table DDL.

    Parameters
    ----------
    statement : str
        DuckDB table or index DDL statement.

    Returns
    -------
    str
        Statement without table-level foreign-key constraints.

    Notes
    -----
    DuckDB enforces foreign keys with delete/update limitations that conflict
    with codira's replace-file indexing workflow. The backend maintains
    relationship consistency explicitly during persistence and deletes.
    """
    lines = statement.splitlines()
    filtered = [line for line in lines if not line.strip().startswith("FOREIGN KEY(")]
    if len(filtered) == len(lines):
        return statement
    for index in range(len(filtered) - 1, -1, -1):
        stripped = filtered[index].strip()
        if not stripped or stripped == ");":
            continue
        filtered[index] = filtered[index].rstrip().removesuffix(",")
        break
    return "\n".join(filtered)


def _duckdb_schema_ddl() -> tuple[str, ...]:
    """
    Return DuckDB schema statements for the codira backend store.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[str, ...]
        Sequence creation statements followed by rewritten table/index DDL.
    """
    sequence_statements = tuple(
        f"CREATE SEQUENCE IF NOT EXISTS {sequence_name} START 1;"
        for sequence_name in _TABLE_ID_SEQUENCE.values()
    )
    table_statements = tuple(_rewrite_duckdb_ddl(statement) for statement in DDL)
    return (*sequence_statements, *table_statements, *_DUCKDB_SYMBOL_DETAIL_INDEX_DDL)


def _duckdb_schema_index_ddl() -> tuple[str, ...]:
    """
    Return DuckDB schema index creation statements.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[str, ...]
        Index DDL statements from the rewritten DuckDB schema.
    """
    return tuple(
        statement for statement in _duckdb_schema_ddl() if " INDEX " in statement
    )


def _duckdb_schema_index_names() -> tuple[str, ...]:
    """
    Return DuckDB schema index names declared by the backend schema.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[str, ...]
        Validated index names parsed from schema index DDL statements.
    """
    index_names: list[str] = []
    for statement in _duckdb_schema_index_ddl():
        match = _INDEX_NAME_PATTERN.search(statement)
        if match is None:
            continue
        index_names.append(_validated_sql_identifier(match.group(1), kind="index"))
    return tuple(index_names)


def _drop_duckdb_schema_indexes(conn: _BackendCompatibleConnectionAdapter) -> None:
    """
    Drop schema indexes before a DuckDB full-rebuild bulk ingest.

    Parameters
    ----------
    conn : _BackendCompatibleConnectionAdapter
        Open backend-compatible DuckDB connection.

    Returns
    -------
    None
        Existing schema indexes are dropped in place.
    """
    for index_name in _duckdb_schema_index_names():
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
        conn.execute(f"DROP INDEX IF EXISTS {index_name}")


def _create_duckdb_schema_indexes(conn: _BackendCompatibleConnectionAdapter) -> None:
    """
    Create schema indexes after a DuckDB full-rebuild bulk ingest.

    Parameters
    ----------
    conn : _BackendCompatibleConnectionAdapter
        Open backend-compatible DuckDB connection.

    Returns
    -------
    None
        Schema indexes are created in place.
    """
    for statement in _duckdb_schema_index_ddl():
        conn.execute(statement)


def _recreate_duckdb_index_tables(conn: _BackendCompatibleConnectionAdapter) -> None:
    """
    Recreate indexed-data tables for one transactional full rebuild.

    Parameters
    ----------
    conn : _BackendCompatibleConnectionAdapter
        Open backend-compatible DuckDB connection.

    Returns
    -------
    None
        Indexed tables are dropped and recreated while cache/runtime tables are
        preserved.
    """
    for table_name in _INDEX_DATA_TABLES:
        safe_table_name = _validated_sql_identifier(table_name, kind="table")
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
        # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        conn.execute(f"DROP TABLE IF EXISTS {safe_table_name}")

    table_prefixes = tuple(
        f"CREATE TABLE IF NOT EXISTS {table_name} ("
        for table_name in _INDEX_DATA_TABLES
    )
    for statement in _duckdb_schema_ddl():
        if statement.lstrip().startswith(table_prefixes):
            conn.execute(statement)


def _table_info_notnull_by_name(
    raw: _DuckDBRawConnection,
    table_name: str,
) -> dict[str, bool]:
    """
    Return per-column ``NOT NULL`` flags for one DuckDB table.

    Parameters
    ----------
    raw : _DuckDBRawConnection
        Active raw DuckDB connection.
    table_name : str
        Table whose column metadata should be inspected.

    Returns
    -------
    dict[str, bool]
        Mapping of column names to their ``NOT NULL`` flags.
    """
    safe_table_name = _validated_sql_identifier(table_name, kind="table")
    # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
    # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
    raw.execute(  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
        f"PRAGMA table_info('{safe_table_name}')"
    )
    rows = raw.fetchall()
    notnull_by_name: dict[str, bool] = {}
    for row in rows:
        column_name = str(row[1])
        notnull_value = row[3]
        assert isinstance(notnull_value, (int, str, bytes, bytearray))
        notnull_by_name[column_name] = bool(int(notnull_value))
    return notnull_by_name


def _repair_nullable_edge_table(
    raw: _DuckDBRawConnection,
    *,
    table_name: str,
    create_statement: str,
    column_names: tuple[str, ...],
    index_names: tuple[str, ...],
) -> None:
    """
    Rebuild one edge table so unresolved targets remain nullable in DuckDB.

    Parameters
    ----------
    raw : _DuckDBRawConnection
        Active raw DuckDB connection.
    table_name : str
        Edge table requiring nullable-target repair.
    create_statement : str
        DuckDB-compatible ``CREATE TABLE`` statement for the repaired table.
    column_names : tuple[str, ...]
        Ordered columns copied into the replacement table.
    index_names : tuple[str, ...]
        Index names to drop and recreate around the rebuild.

    Returns
    -------
    None
        The existing table is replaced in place when repair is needed.

    Raises
    ------
    RuntimeError
        If the legacy table is missing columns other than supported nullable
        edge metadata columns.
    """
    safe_table_name = _validated_sql_identifier(table_name, kind="table")
    legacy_table_name = _validated_sql_identifier(
        f"{safe_table_name}_legacy_nullable_fix",
        kind="table",
    )
    current_columns = set(_table_info_notnull_by_name(raw, table_name))
    missing_columns = set(column_names) - current_columns
    supported_missing_columns = {
        "unresolved_identity",
        "external_target_kind",
        "external_target_name",
    }
    unsupported_missing_columns = missing_columns - supported_missing_columns
    if unsupported_missing_columns:
        columns = ", ".join(sorted(unsupported_missing_columns))
        msg = f"Cannot repair DuckDB {table_name} with missing columns: {columns}"
        raise RuntimeError(msg)
    column_list = ", ".join(column_names)
    select_list = ", ".join(
        column_name
        if column_name in current_columns
        else (
            f"'' AS {column_name}"
            if column_name == "unresolved_identity"
            else f"NULL AS {column_name}"
        )
        for column_name in column_names
    )
    for index_name in index_names:
        safe_index_name = _validated_sql_identifier(index_name, kind="index")
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
        # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        raw.execute(  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
            f"DROP INDEX IF EXISTS {safe_index_name}"
        )
    # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
    # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
    raw.execute(  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
        f"ALTER TABLE {safe_table_name} RENAME TO {legacy_table_name}"
    )
    raw.execute(create_statement)
    # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
    # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
    raw.execute(
        f"INSERT INTO {safe_table_name} ({column_list}) "
        f"SELECT {select_list} FROM {legacy_table_name}"
    )
    # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
    # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
    raw.execute(  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
        f"DROP TABLE {legacy_table_name}"
    )
    for statement in _duckdb_schema_ddl():
        if any(index_name in statement for index_name in index_names):
            raw.execute(statement)


def _repair_nullable_edge_tables(raw: _DuckDBRawConnection) -> None:
    """
    Repair legacy DuckDB edge tables that encoded nullable targets as primary keys.

    Parameters
    ----------
    raw : _DuckDBRawConnection
        Active raw DuckDB connection.

    Returns
    -------
    None
        Legacy edge tables are rebuilt in place when their nullable target
        columns are incorrectly marked ``NOT NULL``.
    """
    for table_name, (
        create_statement,
        column_names,
        index_names,
    ) in _NULLABLE_EDGE_TABLE_REWRITES.items():
        notnull_by_name = _table_info_notnull_by_name(raw, table_name)
        if not notnull_by_name:
            continue
        current_columns = tuple(notnull_by_name)
        nullable_columns = (
            ("callee_module", "callee_name")
            if table_name == "call_edges"
            else ("target_module", "target_name")
        )
        needs_repair = current_columns != column_names or any(
            notnull_by_name.get(column_name, False) for column_name in nullable_columns
        )
        if needs_repair:
            _repair_nullable_edge_table(
                raw,
                table_name=table_name,
                create_statement=create_statement,
                column_names=column_names,
                index_names=index_names,
            )
    raw.commit()


def _write_schema_metadata(root: Path) -> None:
    """
    Persist the active schema version under the repository metadata file.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose metadata should be updated.

    Returns
    -------
    None
        Metadata is rewritten atomically in place.
    """
    metadata_path = get_metadata_path(root)
    metadata: dict[str, str]
    if metadata_path.exists():
        try:
            metadata = dict(json.loads(metadata_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            metadata = {}
    else:
        metadata = {}
    metadata["schema_version"] = str(SCHEMA_VERSION)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )


class DuckDBIndexBackend(DuckDBQueryBackend):
    """
    Concrete DuckDB backend exposed from the package boundary.

    The backend mirrors SQLite query semantics while owning a DuckDB-specific
    storage file, schema bootstrap, and error translation layer.
    """

    name = "duckdb"
    version = SCHEMA_VERSION

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the DuckDB backend configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for DuckDB backend options.
        """

        return plugin_json_schema({})

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply DuckDB backend configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced backend configuration table.

        Returns
        -------
        None
            DuckDB currently has no backend-specific settings.
        """

        del config

    def begin_index_session(self, root: Path) -> IndexWriteSession:
        """
        Open the explicit write-side lifecycle for one indexing run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state will be mutated.

        Returns
        -------
        codira.contracts.IndexWriteSession
            Mutable session object used only by indexing flows.
        """
        return _DuckDBIndexWriteSession(self, root)

    def initialize(self, root: Path) -> None:
        """
        Prepare the repository-local DuckDB database.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should exist.

        Returns
        -------
        None
            The DuckDB schema and metadata are created or refreshed in place.
        """
        db_path = _duckdb_db_path(root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        module = _duckdb_module()
        raw = module.connect(str(db_path))
        try:
            schema_statements = _duckdb_schema_ddl()
            for statement in schema_statements:
                if " INDEX " not in statement:
                    raw.execute(statement)
            _repair_nullable_edge_tables(raw)
            for statement in schema_statements:
                if " INDEX " in statement:
                    raw.execute(statement)
            raw.commit()
        finally:
            raw.close()
        _write_schema_metadata(root)

    def open_connection(self, root: Path) -> _BackendCompatibleConnectionAdapter:
        """
        Open a DuckDB connection for one repository index.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index database should be opened.

        Returns
        -------
        _BackendCompatibleConnectionAdapter
            Open DuckDB connection adapter.
        """
        if not _duckdb_db_path(root).exists():
            self.initialize(root)
        raw = _duckdb_module().connect(str(_duckdb_db_path(root)))
        return cast("_BackendCompatibleConnectionAdapter", DuckDBConnection(raw))

    def process_pending_embeddings(
        self,
        root: Path,
        *,
        embedding_backend: EmbeddingBackendSpec,
        vector_store: VectorStore | None = None,
        vector_set_identity: VectorSetIdentity | None = None,
        vector_store_config: Mapping[str, object] | None = None,
        conn: _BackendCompatibleConnectionAdapter | None = None,
    ) -> tuple[int, int]:
        """
        Compute pending embeddings without reparsing source files.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose pending embedding rows should be processed.
        embedding_backend : EmbeddingBackendSpec
            Active embedding backend metadata.
        conn : _BackendCompatibleConnectionAdapter | None, optional
            Existing DuckDB connection to reuse.

        Returns
        -------
        tuple[int, int]
            ``(recomputed, reused)`` counts for processed pending rows.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            result = _process_pending_embedding_rows(
                cast("_DuckDBPersistenceConnection", conn),
                root,
                backend=embedding_backend,
                vector_store=vector_store,
                vector_set_identity=vector_set_identity,
                vector_store_config={}
                if vector_store_config is None
                else vector_store_config,
            )
            if owns_connection:
                conn.commit()
            return result
        finally:
            if owns_connection:
                conn.close()

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Persist normalized artifacts for one analyzed file.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request carrying file metadata, normalized analysis,
            embedding backend metadata, reusable embeddings, and optional
            connection reuse.

        Returns
        -------
        tuple[int, int]
            ``(recomputed, reused)`` embedding counts for the file.

        Raises
        ------
        codira.contracts.BackendError
            Raised when the DuckDB driver reports one persistence failure.
        """
        root = request.root
        error_type = _duckdb_module().Error
        conn = cast("_BackendCompatibleConnectionAdapter | None", request.conn)
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        assert conn is not None
        active_backend = (
            get_embedding_backend(root=root)
            if request.embedding_backend is None
            else request.embedding_backend
        )
        try:
            if owns_connection:
                written = _store_analysis(
                    cast("_DuckDBPersistenceConnection", conn),
                    root,
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
                    vector_store=request.vector_store,
                    vector_set_identity=request.vector_set_identity,
                    vector_store_config=request.vector_store_config,
                )
            else:
                # DuckDB does not support SQLite-style savepoints, so isolate
                # each file write in its own transaction on the shared
                # connection instead.
                conn.commit()
                conn.execute("BEGIN TRANSACTION")
                try:
                    written = _store_analysis(
                        cast("_DuckDBPersistenceConnection", conn),
                        root,
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
                        vector_store=request.vector_store,
                        vector_set_identity=request.vector_set_identity,
                        vector_store_config=request.vector_store_config,
                    )
                except (OSError, error_type, RuntimeError, ValueError):
                    conn.execute("ROLLBACK")
                    raise
                else:
                    conn.execute("COMMIT")
        except error_type as exc:
            msg = str(exc)
            raise BackendError(msg) from exc
        else:
            if owns_connection:
                conn.commit()
            return written
        finally:
            if owns_connection:
                conn.close()

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Persist backend and analyzer inventory for one successful index run.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory persistence request.

        Returns
        -------
        None
            Runtime inventory rows are replaced in place.

        Raises
        ------
        codira.contracts.BackendError
            Raised when the DuckDB driver reports one inventory-write failure.
        """
        root = request.root
        backend_name = request.backend_name
        backend_version = request.backend_version
        coverage_complete = request.coverage_complete
        analyzers = request.analyzers
        error_type = _duckdb_module().Error
        conn = cast("_BackendCompatibleConnectionAdapter | None", request.conn)
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        assert conn is not None
        try:
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
            if owns_connection:
                conn.commit()
        except error_type as exc:
            msg = str(exc)
            raise BackendError(msg) from exc
        finally:
            if owns_connection:
                conn.close()


def build_backend() -> IndexBackend:
    """
    Build the first-party DuckDB backend plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.IndexBackend
        Active DuckDB backend instance.
    """
    return cast("IndexBackend", DuckDBIndexBackend())
