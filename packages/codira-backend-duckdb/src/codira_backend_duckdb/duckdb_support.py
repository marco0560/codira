"""DuckDB backend-owned persistence helpers for the first-party plugin.

Responsibilities
----------------
- Hold DuckDB-owned persistence helpers that do not belong to the index-planning flow.
- Provide reusable embedding-row models for DuckDB backend persistence.
- Keep low-level DuckDB mutation helpers package-owned behind the plugin boundary.

Design principles
-----------------
Support helpers stay deterministic and narrowly scoped to DuckDB persistence so
the backend plugin can own its storage implementation without routing writes
through SQLite-owned helper modules.

Architectural role
------------------
This module belongs to the **DuckDB backend plugin layer** and owns the
package-local helper implementation used by the first-party DuckDB backend.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from codira.contracts import (
    BackendError,
    EmbeddingIndexingMetrics,
    EmbeddingIndexingPolicy,
    PendingEmbeddingRow,
    PreparedVectorIdentityRow,
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
from .profiling import DuckDBProfileRecorder
from .duckdb_bulk_io import _flush_registered_arrow_table
from .duckdb_reference_scan import (
    _flush_pending_reference_scan_rows,
    _flush_reference_scan_rows,
)
from .duckdb_embedding_persistence import (
    _delete_pending_embedding_rows,
    _flush_embedding_rows,
    _store_vector_store_materialized_rows,
)
from .duckdb_embedding_persistence import (
    _store_pending_embedding_rows as _store_pending_embedding_rows,
)

__all__ = [
    "CallResolutionRequest",
    "DuckDBIdAllocator",
    "DuckDBStructuralRowBuffers",
    "EmbeddingTextRequest",
    "_DuckDBPersistenceConnection",
    "_delete_pending_embedding_rows",
    "_duckdb_int",
    "_flush_docstring_issue_rows",
    "_flush_import_rows",
    "_store_pending_embedding_rows",
]

from .duckdb_artifact_persistence import (
    ArtifactPersistenceRequest,
    CallResolutionRequest,
    DuckDBIdAllocator,
    DuckDBStructuralRowBuffers,
    EmbeddingTextRequest,
    _DuckDBPersistenceConnection,
    _duckdb_int,
    _flush_call_record_rows,
    _flush_callable_ref_record_rows,
    _flush_docstring_issue_rows,
    _flush_import_rows,
    _flush_persisted_relationship_rows,
    _persist_class_artifacts,
    _persist_declaration_artifacts,
    _persist_documentation_artifacts,
    _persist_function_artifacts,
    _persist_import_artifacts,
    _persist_module_artifacts,
)

if TYPE_CHECKING:
    from codira.contracts import LanguageAnalyzer, VectorSetIdentity, VectorStore
    from codira.models import (
        AnalysisResult,
        FileMetadataSnapshot,
    )
    from codira.semantic.embeddings import EmbeddingBackendSpec

CallRecord = dict[str, str | int]
CallRow = tuple[int, str, str, str, str, str, str | None, str | None, int, int]
RefRow = tuple[int, str, str, str, str, str, str, str | None, str | None, int, int]
FileRow = tuple[int, str, str, float, int, str, str]
ModuleRow = tuple[int, int, str, str | None, int]
ClassRow = tuple[int, int, str, int, int | None, str | None, int]
FunctionRow = tuple[
    int,
    int,
    int | None,
    str,
    int,
    int | None,
    str | None,
    str | None,
    int,
    int,
    int,
]
SymbolIndexRow = tuple[int, str, str, str, str, int, int]
DocumentationArtifactRow = tuple[
    int,
    int,
    str,
    str,
    str,
    int,
    int | None,
    str,
    str,
    str,
    str | None,
    str | None,
    str | None,
]
DocstringIssueRow = tuple[
    int,
    int | None,
    int | None,
    int | None,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
]
ImportRow = tuple[int, str, str | None, str, int]
OverloadRow = tuple[int, str, str, int, str, str | None, int, int | None]
EnumMemberRow = tuple[int, str, str, int, str, str, int, str, str, int]
_T = TypeVar("_T")
_DUCKDB_EMBEDDING_BATCH_ROWS = 2_048

_DERIVED_GRAPH_INDEX_DROP_DDL = (
    "DROP INDEX IF EXISTS idx_call_edges_identity",
    "DROP INDEX IF EXISTS idx_call_edges_caller",
    "DROP INDEX IF EXISTS idx_call_edges_caller_lookup",
    "DROP INDEX IF EXISTS idx_call_edges_callee",
    "DROP INDEX IF EXISTS idx_call_edges_callee_lookup",
    "DROP INDEX IF EXISTS idx_call_edges_resolved",
    "DROP INDEX IF EXISTS idx_callable_refs_identity",
    "DROP INDEX IF EXISTS idx_callable_refs_owner",
    "DROP INDEX IF EXISTS idx_callable_refs_owner_lookup",
    "DROP INDEX IF EXISTS idx_callable_refs_target",
    "DROP INDEX IF EXISTS idx_callable_refs_target_lookup",
    "DROP INDEX IF EXISTS idx_callable_refs_resolved",
)
_CALL_EDGES_REBUILD_TABLE_DDL = """
    CREATE TABLE call_edges (
        caller_file_id INTEGER NOT NULL,
        caller_module TEXT NOT NULL,
        caller_name TEXT NOT NULL,
        callee_module TEXT,
        callee_name TEXT,
        unresolved_identity TEXT NOT NULL DEFAULT '',
        external_target_kind TEXT,
        external_target_name TEXT,
        resolved INTEGER NOT NULL
    );
"""
_CALLABLE_REFS_REBUILD_TABLE_DDL = """
    CREATE TABLE callable_refs (
        owner_file_id INTEGER NOT NULL,
        owner_module TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        target_module TEXT,
        target_name TEXT,
        unresolved_identity TEXT NOT NULL DEFAULT '',
        external_target_kind TEXT,
        external_target_name TEXT,
        resolved INTEGER NOT NULL
    );
"""
_DERIVED_GRAPH_INDEX_DDL = (
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_call_edges_identity
    ON call_edges(
        caller_file_id,
        caller_module,
        caller_name,
        COALESCE(callee_module, ''),
        COALESCE(callee_name, ''),
        unresolved_identity
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_edges_caller
    ON call_edges(caller_file_id, caller_module, caller_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_edges_caller_lookup
    ON call_edges(caller_name, caller_module, caller_file_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_edges_callee
    ON call_edges(callee_module, callee_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_edges_callee_lookup
    ON call_edges(callee_name, callee_module);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_edges_resolved
    ON call_edges(resolved);
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_callable_refs_identity
    ON callable_refs(
        owner_file_id,
        owner_module,
        owner_name,
        COALESCE(target_module, ''),
        COALESCE(target_name, ''),
        unresolved_identity
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_refs_owner
    ON callable_refs(owner_file_id, owner_module, owner_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_refs_owner_lookup
    ON callable_refs(owner_name, owner_module, owner_file_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_refs_target
    ON callable_refs(target_module, target_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_refs_target_lookup
    ON callable_refs(target_name, target_module);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_refs_resolved
    ON callable_refs(resolved);
    """,
)


def _flush_pending_relationship_rows(
    conn: _DuckDBPersistenceConnection,
    *,
    pending_call_rows: list[CallRow],
    pending_ref_rows: list[RefRow],
    profiler: DuckDBProfileRecorder | None = None,
) -> None:
    """
    Flush session-level relationship rows to DuckDB.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    pending_call_rows : list[CallRow]
        Session-level normalized call rows.
    pending_ref_rows : list[RefRow]
        Session-level normalized callable-reference rows.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for batch write spans.

    Returns
    -------
    None
        Pending relationship rows are inserted in deterministic order.
    """
    if pending_call_rows:
        _flush_call_record_rows(
            conn,
            sorted(set(pending_call_rows)),
            profiler=profiler,
        )
    if pending_ref_rows:
        _flush_callable_ref_record_rows(
            conn,
            sorted(set(pending_ref_rows)),
            profiler=profiler,
        )


def _flush_structural_file_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[FileRow],
) -> None:
    """
    Flush file rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[FileRow]
        File rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.

    """
    if not rows:
        return

    import pyarrow as pa

    table = pa.table(
        {
            "id": pa.array([row[0] for row in rows], type=pa.int64()),
            "path": pa.array([row[1] for row in rows], type=pa.string()),
            "hash": pa.array([row[2] for row in rows], type=pa.string()),
            "mtime": pa.array([row[3] for row in rows], type=pa.float64()),
            "size": pa.array([row[4] for row in rows], type=pa.int64()),
            "analyzer_name": pa.array([row[5] for row in rows], type=pa.string()),
            "analyzer_version": pa.array([row[6] for row in rows], type=pa.string()),
        }
    )
    _flush_registered_arrow_table(
        conn,
        view_name="__codira_pending_file_rows",
        table=table,
        insert_sql="""
            INSERT INTO files(id, path, hash, mtime, size, analyzer_name, analyzer_version)
            SELECT id, path, hash, mtime, size, analyzer_name, analyzer_version
            FROM __codira_pending_file_rows
            """,
    )


def _flush_structural_module_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[ModuleRow],
) -> None:
    """
    Flush module rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[ModuleRow]
        Module rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.
    """
    if not rows:
        return

    import pyarrow as pa

    table = pa.table(
        {
            "id": pa.array([row[0] for row in rows], type=pa.int64()),
            "file_id": pa.array([row[1] for row in rows], type=pa.int64()),
            "name": pa.array([row[2] for row in rows], type=pa.string()),
            "docstring": pa.array([row[3] for row in rows], type=pa.string()),
            "has_docstring": pa.array([row[4] for row in rows], type=pa.int64()),
        }
    )
    _flush_registered_arrow_table(
        conn,
        view_name="__codira_pending_module_rows",
        table=table,
        insert_sql="""
            INSERT INTO modules(id, file_id, name, docstring, has_docstring)
            SELECT id, file_id, name, docstring, has_docstring
            FROM __codira_pending_module_rows
            """,
    )


def _flush_structural_class_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[ClassRow],
) -> None:
    """
    Flush class rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[ClassRow]
        Class rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.
    """
    if not rows:
        return

    import pyarrow as pa

    table = pa.table(
        {
            "id": pa.array([row[0] for row in rows], type=pa.int64()),
            "module_id": pa.array([row[1] for row in rows], type=pa.int64()),
            "name": pa.array([row[2] for row in rows], type=pa.string()),
            "lineno": pa.array([row[3] for row in rows], type=pa.int64()),
            "end_lineno": pa.array([row[4] for row in rows], type=pa.int64()),
            "docstring": pa.array([row[5] for row in rows], type=pa.string()),
            "has_docstring": pa.array([row[6] for row in rows], type=pa.int64()),
        }
    )
    _flush_registered_arrow_table(
        conn,
        view_name="__codira_pending_class_rows",
        table=table,
        insert_sql="""
            INSERT INTO classes(id, module_id, name, lineno, end_lineno, docstring, has_docstring)
            SELECT id, module_id, name, lineno, end_lineno, docstring, has_docstring
            FROM __codira_pending_class_rows
            """,
    )


def _flush_structural_function_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[FunctionRow],
) -> None:
    """
    Flush function rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[FunctionRow]
        Function rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.
    """
    if not rows:
        return

    import pyarrow as pa

    table = pa.table(
        {
            "id": pa.array([row[0] for row in rows], type=pa.int64()),
            "module_id": pa.array([row[1] for row in rows], type=pa.int64()),
            "class_id": pa.array([row[2] for row in rows], type=pa.int64()),
            "name": pa.array([row[3] for row in rows], type=pa.string()),
            "lineno": pa.array([row[4] for row in rows], type=pa.int64()),
            "end_lineno": pa.array([row[5] for row in rows], type=pa.int64()),
            "signature": pa.array([row[6] for row in rows], type=pa.string()),
            "docstring": pa.array([row[7] for row in rows], type=pa.string()),
            "has_docstring": pa.array([row[8] for row in rows], type=pa.int64()),
            "is_method": pa.array([row[9] for row in rows], type=pa.int64()),
            "is_public": pa.array([row[10] for row in rows], type=pa.int64()),
        }
    )
    _flush_registered_arrow_table(
        conn,
        view_name="__codira_pending_function_rows",
        table=table,
        insert_sql="""
            INSERT INTO functions(
                id,
                module_id,
                class_id,
                name,
                lineno,
                end_lineno,
                signature,
                docstring,
                has_docstring,
                is_method,
                is_public
            )
            SELECT
                id,
                module_id,
                class_id,
                name,
                lineno,
                end_lineno,
                signature,
                docstring,
                has_docstring,
                is_method,
                is_public
            FROM __codira_pending_function_rows
            """,
    )


def _flush_structural_symbol_index_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[SymbolIndexRow],
) -> None:
    """
    Flush symbol-index rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[SymbolIndexRow]
        Symbol-index rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.
    """
    if not rows:
        return

    import pyarrow as pa

    table = pa.table(
        {
            "id": pa.array([row[0] for row in rows], type=pa.int64()),
            "name": pa.array([row[1] for row in rows], type=pa.string()),
            "stable_id": pa.array([row[2] for row in rows], type=pa.string()),
            "type": pa.array([row[3] for row in rows], type=pa.string()),
            "module_name": pa.array([row[4] for row in rows], type=pa.string()),
            "file_id": pa.array([row[5] for row in rows], type=pa.int64()),
            "lineno": pa.array([row[6] for row in rows], type=pa.int64()),
        }
    )
    _flush_registered_arrow_table(
        conn,
        view_name="__codira_pending_symbol_index_rows",
        table=table,
        insert_sql="""
            INSERT INTO symbol_index(id, name, stable_id, type, module_name, file_id, lineno)
            SELECT id, name, stable_id, type, module_name, file_id, lineno
            FROM __codira_pending_symbol_index_rows
            """,
    )


def _flush_structural_documentation_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[DocumentationArtifactRow],
) -> None:
    """
    Flush documentation rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[DocumentationArtifactRow]
        Documentation artifact rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.

    Raises
    ------
    BackendError
        If buffered documentation rows contain duplicate stable IDs.
    """
    if not rows:
        return
    stable_id_counts = Counter(row[2] for row in rows)
    duplicates = sorted(
        stable_id for stable_id, count in stable_id_counts.items() if count > 1
    )
    if duplicates:
        duplicates_text = ", ".join(duplicates)
        msg = f"duplicate documentation stable_id(s): {duplicates_text}"
        raise BackendError(msg)

    import pyarrow as pa

    table = pa.table(
        {
            "id": pa.array([row[0] for row in rows], type=pa.int64()),
            "file_id": pa.array([row[1] for row in rows], type=pa.int64()),
            "stable_id": pa.array([row[2] for row in rows], type=pa.string()),
            "kind": pa.array([row[3] for row in rows], type=pa.string()),
            "source_format": pa.array([row[4] for row in rows], type=pa.string()),
            "lineno": pa.array([row[5] for row in rows], type=pa.int64()),
            "end_lineno": pa.array([row[6] for row in rows], type=pa.int64()),
            "title": pa.array([row[7] for row in rows], type=pa.string()),
            "heading_path": pa.array([row[8] for row in rows], type=pa.string()),
            "text": pa.array([row[9] for row in rows], type=pa.string()),
            "owner_stable_id": pa.array([row[10] for row in rows], type=pa.string()),
            "owner_kind": pa.array([row[11] for row in rows], type=pa.string()),
            "attachment_confidence": pa.array(
                [row[12] for row in rows], type=pa.string()
            ),
        }
    )
    _flush_registered_arrow_table(
        conn,
        view_name="__codira_pending_documentation_rows",
        table=table,
        insert_sql="""
            INSERT INTO documentation_artifacts(
                id,
                file_id,
                stable_id,
                kind,
                source_format,
                lineno,
                end_lineno,
                title,
                heading_path,
                text,
                owner_stable_id,
                owner_kind,
                attachment_confidence
            )
            SELECT
                id,
                file_id,
                stable_id,
                kind,
                source_format,
                lineno,
                end_lineno,
                title,
                heading_path,
                text,
                owner_stable_id,
                owner_kind,
                attachment_confidence
            FROM __codira_pending_documentation_rows
            """,
    )


def _flush_structural_overload_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[OverloadRow],
) -> None:
    """
    Flush overload rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[OverloadRow]
        Overload rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.
    """
    if not rows:
        return

    import pyarrow as pa

    table = pa.table(
        {
            "function_id": pa.array([row[0] for row in rows], type=pa.int64()),
            "stable_id": pa.array([row[1] for row in rows], type=pa.string()),
            "parent_stable_id": pa.array([row[2] for row in rows], type=pa.string()),
            "ordinal": pa.array([row[3] for row in rows], type=pa.int64()),
            "signature": pa.array([row[4] for row in rows], type=pa.string()),
            "docstring": pa.array([row[5] for row in rows], type=pa.string()),
            "lineno": pa.array([row[6] for row in rows], type=pa.int64()),
            "end_lineno": pa.array([row[7] for row in rows], type=pa.int64()),
        }
    )
    _flush_registered_arrow_table(
        conn,
        view_name="__codira_pending_overload_rows",
        table=table,
        insert_sql="""
            INSERT INTO overloads(
                function_id,
                stable_id,
                parent_stable_id,
                ordinal,
                signature,
                docstring,
                lineno,
                end_lineno
            )
            SELECT
                function_id,
                stable_id,
                parent_stable_id,
                ordinal,
                signature,
                docstring,
                lineno,
                end_lineno
            FROM __codira_pending_overload_rows
            """,
    )


def _flush_structural_enum_member_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[EnumMemberRow],
) -> None:
    """
    Flush enum-member rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[EnumMemberRow]
        Enum-member rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.
    """
    if not rows:
        return

    import pyarrow as pa

    table = pa.table(
        {
            "file_id": pa.array([row[0] for row in rows], type=pa.int64()),
            "module_name": pa.array([row[1] for row in rows], type=pa.string()),
            "symbol_name": pa.array([row[2] for row in rows], type=pa.string()),
            "symbol_lineno": pa.array([row[3] for row in rows], type=pa.int64()),
            "stable_id": pa.array([row[4] for row in rows], type=pa.string()),
            "parent_stable_id": pa.array([row[5] for row in rows], type=pa.string()),
            "ordinal": pa.array([row[6] for row in rows], type=pa.int64()),
            "name": pa.array([row[7] for row in rows], type=pa.string()),
            "signature": pa.array([row[8] for row in rows], type=pa.string()),
            "lineno": pa.array([row[9] for row in rows], type=pa.int64()),
        }
    )
    _flush_registered_arrow_table(
        conn,
        view_name="__codira_pending_enum_member_rows",
        table=table,
        insert_sql="""
            INSERT INTO enum_members(
                file_id,
                module_name,
                symbol_name,
                symbol_lineno,
                stable_id,
                parent_stable_id,
                ordinal,
                name,
                signature,
                lineno
            )
            SELECT
                file_id,
                module_name,
                symbol_name,
                symbol_lineno,
                stable_id,
                parent_stable_id,
                ordinal,
                name,
                signature,
                lineno
            FROM __codira_pending_enum_member_rows
            """,
    )


def _flush_structural_rows(
    conn: _DuckDBPersistenceConnection,
    rows: DuckDBStructuralRowBuffers,
) -> None:
    """
    Flush buffered structural rows in foreign-key-safe order.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : DuckDBStructuralRowBuffers
        Structural rows accumulated by the current write session.

    Returns
    -------
    None
        Pending rows are inserted and buffers are cleared.
    """
    _flush_structural_file_rows(conn, rows.files)
    _flush_structural_module_rows(conn, rows.modules)
    _flush_structural_class_rows(conn, rows.classes)
    _flush_structural_function_rows(conn, rows.functions)
    _flush_structural_symbol_index_rows(conn, rows.symbol_index)
    _flush_structural_documentation_rows(conn, rows.documentation_artifacts)
    _flush_structural_overload_rows(conn, rows.overloads)
    _flush_structural_enum_member_rows(conn, rows.enum_members)
    rows.clear()


def _flush_prepared_embedding_rows(
    conn: _DuckDBPersistenceConnection,
    root: Path | None = None,
    *,
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
    backend_connection: object | None = None,
    profiler: DuckDBProfileRecorder | None = None,
    fresh_full_index: bool = False,
) -> None:
    """
    Flush prepared embedding rows to DuckDB.

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
    vector_store : codira.contracts.VectorStore | None, optional
        Active separated vector-store plugin used for materialized vectors.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object] | None, optional
        Vector-store-specific configuration table.
    backend_connection : object | None, optional
        Backend-owned connection that compatible vector stores may reuse.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for embedding persistence spans.
    fresh_full_index : bool, optional
        Whether the caller has just recreated the embedding table for a full
        index rebuild. Fresh rebuilds can skip stale-row deletes and SQL
        deduplication windows.

    Returns
    -------
    None
        Prepared embedding rows are inserted in place.
    """
    if not prepared_rows:
        return
    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    if not fresh_full_index:
        _delete_pending_embedding_rows(
            conn,
            prepared_rows=prepared_rows,
            backend=backend,
            profiler=active_profiler,
        )

    import pyarrow as pa

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
    encoded_vectors: dict[str, tuple[bytes, list[float]]] = {}
    texts_to_encode = {
        content_hash: row.text
        for row, content_hash, stored_vector in deduplicated_rows
        if stored_vector is None
    }
    if texts_to_encode:
        ordered_content_hashes = list(dict.fromkeys(texts_to_encode))
        with active_profiler.span("embeddings.embed_texts", rows=len(texts_to_encode)):
            encoded_rows = embed_texts(
                [
                    texts_to_encode[content_hash]
                    for content_hash in ordered_content_hashes
                ],
                root=root,
            )
        for content_hash, vector in zip(
            ordered_content_hashes,
            encoded_rows,
            strict=True,
        ):
            encoded_vectors[content_hash] = (serialize_vector(vector), vector)
    object_types: list[str] = []
    object_ids: list[int] = []
    backends: list[str] = []
    versions: list[str] = []
    content_hashes: list[str] = []
    dims: list[int] = []
    vectors: list[bytes] = []
    vector_values_rows: list[list[float] | None] = []
    row_ordinals: list[int] = []
    materialized_rows: list[PreparedVectorRow] = []
    identity_rows: list[PreparedVectorIdentityRow] = []
    for row_ordinal, (row, content_hash, stored_vector) in enumerate(deduplicated_rows):
        resolved_blob = stored_vector
        if resolved_blob is None:
            resolved_blob, _vector_values = encoded_vectors[content_hash]

        object_types.append(row.object_type)
        object_ids.append(row.object_id)
        backends.append(backend.name)
        versions.append(backend.version)
        content_hashes.append(content_hash)
        dims.append(backend.dim)
        vectors.append(b"")
        vector_values_rows.append(None)
        row_ordinals.append(row_ordinal)
        materialized_rows.append(
            PreparedVectorRow(
                row=row,
                content_hash=content_hash,
                vector=resolved_blob,
            )
        )
        identity_rows.append(
            PreparedVectorIdentityRow(
                object_type=row.object_type,
                stable_id=row.stable_id,
                content_hash=content_hash,
                vector=resolved_blob if stored_vector is None else None,
            )
        )

    with active_profiler.span(
        "arrow.build.embeddings",
        rows=len(deduplicated_rows),
        payload_bytes=sum(len(vector) for vector in vectors),
    ):
        table = pa.table(
            {
                "object_type": pa.array(object_types, type=pa.string()),
                "object_id": pa.array(object_ids, type=pa.int64()),
                "backend": pa.array(backends, type=pa.string()),
                "version": pa.array(versions, type=pa.string()),
                "content_hash": pa.array(content_hashes, type=pa.string()),
                "dim": pa.array(dims, type=pa.int64()),
                "vector": pa.array(vectors, type=pa.binary()),
                "vector_values": pa.array(
                    vector_values_rows,
                    type=pa.list_(pa.float64()),
                ),
                "row_ordinal": pa.array(row_ordinals, type=pa.int64()),
            }
        )
    view_name = "__codira_pending_embedding_rows"
    conn.register(view_name, table)
    try:
        if not fresh_full_index:
            with active_profiler.span(
                "embeddings.delete_existing", rows=len(deduplicated_rows)
            ):
                conn.execute(
                    """
                    DELETE FROM embeddings
                    USING __codira_pending_embedding_rows pending
                    WHERE embeddings.object_type = pending.object_type
                      AND embeddings.object_id = pending.object_id
                      AND embeddings.backend = pending.backend
                      AND embeddings.version = pending.version
                    """
                )
        with active_profiler.span(
            "embeddings.insert_rows", rows=len(deduplicated_rows)
        ):
            if fresh_full_index:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO embeddings(
                        object_type,
                        object_id,
                        backend,
                        version,
                        content_hash,
                        dim,
                        vector,
                        vector_values
                    )
                    SELECT
                        object_type,
                        object_id,
                        backend,
                        version,
                        content_hash,
                        dim,
                        vector,
                        vector_values
                    FROM __codira_pending_embedding_rows
                    """
                )
            else:
                conn.execute(
                    """
                    INSERT INTO embeddings(
                        object_type,
                        object_id,
                        backend,
                        version,
                        content_hash,
                        dim,
                        vector,
                        vector_values
                    )
                    SELECT
                        object_type,
                        object_id,
                        backend,
                        version,
                        content_hash,
                        dim,
                        vector,
                        vector_values
                    FROM (
                        SELECT
                            object_type,
                            object_id,
                            backend,
                            version,
                            content_hash,
                            dim,
                            vector,
                            vector_values,
                            row_number() OVER (
                                PARTITION BY object_type, object_id, backend, version
                                ORDER BY row_ordinal DESC
                            ) AS codira_row_rank
                        FROM __codira_pending_embedding_rows
                    )
                    WHERE codira_row_rank = 1
                    """
                )
    finally:
        conn.unregister(view_name)
    _store_vector_store_materialized_rows(
        vector_store=vector_store,
        vector_set_identity=vector_set_identity,
        vector_store_config={} if vector_store_config is None else vector_store_config,
        root=root,
        prepared_rows=materialized_rows,
        identity_rows=identity_rows,
        encoded_vectors={
            content_hash: vector_blob
            for content_hash, (
                vector_blob,
                _vector_values,
            ) in encoded_vectors.items()
        },
        backend_connection=backend_connection,
        profiler=active_profiler,
    )


def _resolve_cached_prepared_embedding_rows(
    *,
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    root: Path | None = None,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
    profiler: DuckDBProfileRecorder | None = None,
) -> tuple[list[tuple[PendingEmbeddingRow, str, bytes | None]], int, int]:
    """
    Resolve vector-cache reuse for a prepared embedding batch.

    Parameters
    ----------
    prepared_rows : list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]]
        Prepared embedding rows as ``(row, content_hash, stored_vector)``.
    root : pathlib.Path | None, optional
        Repository root used to load vector-store cache rows.
    vector_store : codira.contracts.VectorStore | None, optional
        Active vector store used as the authoritative vector cache.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for cache lookup.
    vector_store_config : collections.abc.Mapping[str, object] | None, optional
        Vector-store-specific configuration table.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for cache lookup spans.

    Returns
    -------
    tuple[list[tuple[codira.indexer.PendingEmbeddingRow, str, bytes | None]], int, int]
        Resolved rows and ``(recomputed, reused)`` counters.
    """
    if not prepared_rows:
        return ([], 0, 0)

    missing_hashes = list(
        dict.fromkeys(
            content_hash
            for _row, content_hash, stored_vector in prepared_rows
            if stored_vector is None
        )
    )
    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    with active_profiler.span(
        "embeddings.load_cached_vectors",
        rows=len(missing_hashes),
    ):
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

    resolved_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]] = []
    recomputed = 0
    reused = 0
    for row, content_hash, stored_vector in prepared_rows:
        resolved_vector = stored_vector
        if resolved_vector is None:
            resolved_vector = cached_vectors.get(content_hash)
        if resolved_vector is None:
            recomputed += 1
        else:
            reused += 1
        resolved_rows.append((row, content_hash, resolved_vector))
    return (resolved_rows, recomputed, reused)


def _flush_pending_embedding_rows(
    conn: _DuckDBPersistenceConnection,
    root: Path | None = None,
    *,
    pending_embedding_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
    backend_connection: object | None = None,
    profiler: DuckDBProfileRecorder | None = None,
    fresh_full_index: bool = False,
) -> None:
    """
    Flush session-level embedding rows to DuckDB.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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
    backend_connection : object | None, optional
        Backend-owned connection that compatible vector stores may reuse.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for embedding persistence spans.
    fresh_full_index : bool, optional
        Whether the caller has just recreated the embedding table for a full
        index rebuild.

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
            vector_store_config=(
                {} if vector_store_config is None else vector_store_config
            ),
            backend_connection=backend_connection,
            profiler=profiler,
            fresh_full_index=fresh_full_index,
        )
    pending_embedding_rows.clear()


def _process_pending_embedding_rows(
    conn: _DuckDBPersistenceConnection,
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
    conn : _DuckDBPersistenceConnection
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
                object_id=_duckdb_int(object_id),
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


def _append_analysis_rows(
    conn: _DuckDBPersistenceConnection,
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
    pending_reference_scan_rows: list[tuple[int, int, str]] | None = None,
    pending_call_rows: list[CallRow] | None = None,
    pending_ref_rows: list[RefRow] | None = None,
    pending_import_rows: list[ImportRow] | None = None,
    pending_docstring_issue_rows: list[DocstringIssueRow] | None = None,
    structural_rows: DuckDBStructuralRowBuffers | None = None,
    id_allocator: DuckDBIdAllocator | None = None,
    defer_embedding_cache_lookup: bool = False,
) -> tuple[int, int]:
    """
    Append one parsed file snapshot to DuckDB persistence buffers.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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
    pending_reference_scan_rows : list[tuple[int, int, str]] | None, optional
        Session-level buffer used to batch reference-search rows across files.
    pending_call_rows : list[CallRow] | None, optional
        Session-level buffer used to batch call records across files.
    pending_ref_rows : list[RefRow] | None, optional
        Session-level buffer used to batch callable-reference records across
        files.
    pending_import_rows : list[ImportRow] | None, optional
        Session-level buffer used to batch import rows across files.
    pending_docstring_issue_rows : list[DocstringIssueRow] | None, optional
        Session-level buffer used to batch docstring issues across files.
    structural_rows : DuckDBStructuralRowBuffers | None, optional
        Session-level structural row buffers. A local buffer is used when not
        supplied.
    id_allocator : DuckDBIdAllocator | None, optional
        Session-level explicit-ID allocator. A local allocator is used when not
        supplied.
    defer_embedding_cache_lookup : bool, optional
        Whether cache reuse should be resolved later by a bulk caller.

    Returns
    -------
    tuple[int, int]
        ``(recomputed, reused)`` embedding counts for the file.
    """
    embedding_rows: list[PendingEmbeddingRow] = []
    call_rows: list[CallRow] = []
    ref_rows: list[RefRow] = []
    owns_structural_rows = structural_rows is None
    if structural_rows is None:
        structural_rows = DuckDBStructuralRowBuffers()
    if id_allocator is None:
        id_allocator = DuckDBIdAllocator(conn)
    effective_import_rows = [] if pending_import_rows is None else pending_import_rows
    effective_docstring_issue_rows = (
        [] if pending_docstring_issue_rows is None else pending_docstring_issue_rows
    )
    effective_reference_scan_rows = (
        [] if pending_reference_scan_rows is None else pending_reference_scan_rows
    )

    file_id = id_allocator.next_id("files")
    structural_rows.files.append(
        (
            file_id,
            str(file_metadata.path),
            file_metadata.sha256,
            file_metadata.mtime,
            file_metadata.size,
            file_metadata.analyzer_name,
            file_metadata.analyzer_version,
        )
    )
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
        if owns_structural_rows:
            _flush_structural_rows(conn, structural_rows)
        return (0, 0)
    _persist_documentation_artifacts(
        structural_rows=structural_rows,
        id_allocator=id_allocator,
        file_id=file_id,
        analysis=analysis,
        embedding_rows=embedding_rows,
    )
    if not analysis.index_symbols:
        if owns_structural_rows:
            _flush_structural_rows(conn, structural_rows)
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
            defer_cache_lookup=defer_embedding_cache_lookup,
        )
    module_name, module_id, c_embedding_context = _persist_module_artifacts(
        conn,
        file_id=file_id,
        root=root,
        analysis=analysis,
        embedding_rows=embedding_rows,
        structural_rows=structural_rows,
        id_allocator=id_allocator,
        pending_docstring_issue_rows=effective_docstring_issue_rows,
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
        pending_docstring_issue_rows=effective_docstring_issue_rows,
        structural_rows=structural_rows,
        id_allocator=id_allocator,
        root=root,
    )
    _persist_class_artifacts(artifact_request)
    _persist_function_artifacts(artifact_request)
    _persist_declaration_artifacts(artifact_request)
    _persist_import_artifacts(
        conn,
        module_id=module_id,
        analysis=analysis,
        pending_rows=effective_import_rows,
    )
    _flush_reference_scan_rows(
        conn,
        file_id=file_id,
        path=file_metadata.path,
        pending_rows=effective_reference_scan_rows,
    )
    if owns_structural_rows:
        _flush_structural_rows(conn, structural_rows)
        _flush_import_rows(conn, effective_import_rows)
        _flush_docstring_issue_rows(conn, effective_docstring_issue_rows)
        _flush_pending_reference_scan_rows(conn, effective_reference_scan_rows)
    _flush_persisted_relationship_rows(
        conn,
        call_rows=call_rows,
        ref_rows=ref_rows,
        pending_call_rows=pending_call_rows,
        pending_ref_rows=pending_ref_rows,
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
        defer_cache_lookup=defer_embedding_cache_lookup,
    )


def _store_analysis(
    conn: _DuckDBPersistenceConnection,
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
    pending_reference_scan_rows: list[tuple[int, int, str]] | None = None,
    pending_call_rows: list[CallRow] | None = None,
    pending_ref_rows: list[RefRow] | None = None,
    pending_import_rows: list[ImportRow] | None = None,
    pending_docstring_issue_rows: list[DocstringIssueRow] | None = None,
    structural_rows: DuckDBStructuralRowBuffers | None = None,
    id_allocator: DuckDBIdAllocator | None = None,
) -> tuple[int, int]:
    """
    Persist one parsed file snapshot into the index.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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
    pending_reference_scan_rows : list[tuple[int, int, str]] | None, optional
        Session-level buffer used to batch reference-search rows across files.
    pending_call_rows : list[CallRow] | None, optional
        Session-level buffer used to batch call records across files.
    pending_ref_rows : list[RefRow] | None, optional
        Session-level buffer used to batch callable-reference records across
        files.
    pending_import_rows : list[ImportRow] | None, optional
        Session-level buffer used to batch import rows across files.
    pending_docstring_issue_rows : list[DocstringIssueRow] | None, optional
        Session-level buffer used to batch docstring issues across files.
    structural_rows : DuckDBStructuralRowBuffers | None, optional
        Session-level structural row buffers. A local buffer is used when not
        supplied.
    id_allocator : DuckDBIdAllocator | None, optional
        Session-level explicit-ID allocator. A local allocator is used when not
        supplied.

    Returns
    -------
    tuple[int, int]
        ``(recomputed, reused)`` embedding counts for the file.
    """
    return _append_analysis_rows(
        conn,
        root,
        file_metadata,
        analysis,
        backend=backend,
        embedding_indexing=embedding_indexing,
        embedding_metrics=embedding_metrics,
        defer_embeddings=defer_embeddings,
        previous_embeddings=previous_embeddings,
        pending_embedding_rows=pending_embedding_rows,
        vector_store=vector_store,
        vector_set_identity=vector_set_identity,
        vector_store_config=vector_store_config,
        pending_reference_scan_rows=pending_reference_scan_rows,
        pending_call_rows=pending_call_rows,
        pending_ref_rows=pending_ref_rows,
        pending_import_rows=pending_import_rows,
        pending_docstring_issue_rows=pending_docstring_issue_rows,
        structural_rows=structural_rows,
        id_allocator=id_allocator,
    )


def _persist_runtime_inventory(
    conn: _DuckDBPersistenceConnection,
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
    conn : _DuckDBPersistenceConnection
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

    analyzer_rows = [
        (
            str(analyzer.name),
            str(analyzer.version),
            analyzer_inventory_discovery_json(analyzer),
        )
        for analyzer in sorted(analyzers, key=lambda item: str(item.name))
    ]
    if analyzer_rows:
        import pyarrow as pa

        table = pa.table(
            {
                "name": pa.array([row[0] for row in analyzer_rows], type=pa.string()),
                "version": pa.array(
                    [row[1] for row in analyzer_rows],
                    type=pa.string(),
                ),
                "discovery_globs": pa.array(
                    [row[2] for row in analyzer_rows],
                    type=pa.string(),
                ),
            }
        )
        _flush_registered_arrow_table(
            conn,
            view_name="__codira_pending_index_analyzer_rows",
            table=table,
            insert_sql="""
                INSERT INTO index_analyzers(name, version, discovery_globs)
                SELECT name, version, discovery_globs
                FROM __codira_pending_index_analyzer_rows
                """,
        )


def _placeholders(values: Sequence[object]) -> str:
    """
    Build a positional placeholder string for SQL ``IN`` clauses.

    Parameters
    ----------
    values : collections.abc.Sequence[object]
        Values that will populate the clause.

    Returns
    -------
    str
        Comma-separated ``?`` placeholders sized to ``values``.
    """
    return ",".join("?" for _ in values)


def _delete_indexed_file_data(
    conn: _DuckDBPersistenceConnection, file_path: str
) -> None:
    """
    Remove all indexed data owned by one file.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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

    file_id = _duckdb_int(file_row[0])

    module_ids = [
        _duckdb_int(row[0])
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
        _duckdb_int(row[0])
        for row in conn.execute(
            "SELECT id FROM symbol_index WHERE file_id = ?",
            (file_id,),
        ).fetchall()
    ]
    documentation_ids = [
        _duckdb_int(row[0])
        for row in conn.execute(
            "SELECT id FROM documentation_artifacts WHERE file_id = ?",
            (file_id,),
        ).fetchall()
    ]

    if module_ids:
        class_ids = [
            _duckdb_int(row[0])
            for row in conn.execute(
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"""
                SELECT id
                FROM classes
                WHERE module_id IN ({_placeholders(module_ids)})
                """,
                tuple(module_ids),
            ).fetchall()
        ]
        function_ids = [
            _duckdb_int(row[0])
            for row in conn.execute(
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                (
                    f"""
                    SELECT id
                    FROM functions
                    WHERE module_id IN ({_placeholders(module_ids)})
                    """
                    if not class_ids
                    else f"""
                    SELECT id
                    FROM functions
                    WHERE module_id IN ({_placeholders(module_ids)})
                       OR class_id IN ({_placeholders(class_ids)})
                    """
                ),
                tuple(module_ids) if not class_ids else (*module_ids, *class_ids),
            ).fetchall()
        ]
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
        if function_ids:
            conn.execute(
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"DELETE FROM overloads WHERE function_id IN ({_placeholders(function_ids)})",
                tuple(function_ids),
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
        if class_ids:
            conn.execute(
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"UPDATE functions SET class_id = NULL WHERE class_id IN ({_placeholders(class_ids)})",
                tuple(class_ids),
            )
        if function_ids:
            conn.execute(
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"DELETE FROM functions WHERE id IN ({_placeholders(function_ids)})",
                tuple(function_ids),
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

    conn.execute("DELETE FROM documentation_artifacts WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM symbol_index WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM call_edges WHERE caller_file_id = ?", (file_id,))
    conn.execute("DELETE FROM callable_refs WHERE owner_file_id = ?", (file_id,))
    conn.execute("DELETE FROM call_records WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM callable_ref_records WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM reference_scan_lines WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM files WHERE path = ?", (file_path,))
    conn.execute("DELETE FROM analysis_status WHERE path = ?", (file_path,))
