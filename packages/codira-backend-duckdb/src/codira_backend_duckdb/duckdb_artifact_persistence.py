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

from collections.abc import Sequence
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeVar, cast

from codira.contracts import (
    PendingEmbeddingRow,
)
from codira.docstring import validate_documentation_issues_with_configured_plugin
from codira.semantic.embeddings import (
    embed_texts as embed_texts,
)
from .duckdb_call_resolution import _qualified_callable_name
from .duckdb_bulk_io import _temporary_csv_path_for_rows
from .duckdb_embedding_payload import (
    _c_embedding_context,
    _embedding_text,
    _python_embedding_context,
)
from .duckdb_docstring_policy import (
    _should_audit_docstrings,
    _should_require_raises_section,
)
from .duckdb_embedding_persistence import (
    _delete_pending_embedding_rows,
)
from .profiling import DuckDBProfileRecorder
from .duckdb_embedding_persistence import (
    _store_pending_embedding_rows as _store_pending_embedding_rows,
)

__all__ = [
    "_delete_pending_embedding_rows",
    "_store_pending_embedding_rows",
]

if TYPE_CHECKING:
    from codira.models import (
        AnalysisResult,
        CallableReference,
        CallSite,
        DocumentationArtifact,
        EnumMemberArtifact,
        OverloadArtifact,
    )

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


class _DuckDBCursorLike(Protocol):
    """Cursor surface required by the DuckDB persistence helpers."""

    lastrowid: int | None

    def fetchone(self) -> tuple[object, ...] | None:
        """
        Return the next available row from the active DuckDB result set.

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
        Return every remaining row from the active DuckDB result set.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[object, ...]]
            Remaining rows from the active DuckDB result set.
        """


class _DuckDBPersistenceConnection(Protocol):
    """Connection surface required by the DuckDB persistence helpers."""

    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
    ) -> _DuckDBCursorLike:
        """
        Execute one DuckDB statement and expose its cursor-like result.

        Parameters
        ----------
        query : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[object] | None, optional
            Positional parameters bound to ``query``.

        Returns
        -------
        _DuckDBCursorLike
            Cursor-like result for the executed statement.
        """

    def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[object]],
    ) -> object:
        """
        Execute one DuckDB statement against multiple parameter rows.

        Parameters
        ----------
        query : str
            SQL statement to execute repeatedly.
        parameters : collections.abc.Sequence[collections.abc.Sequence[object]]
            Parameter rows bound to ``query``.

        Returns
        -------
        object
            Driver-specific result for the most recent execution.
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
            Driver-specific result for the registration operation.
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
            Driver-specific result for the unregister operation.
        """


def _duckdb_int(value: object) -> int:
    """
    Coerce one DuckDB row value into an integer.

    Parameters
    ----------
    value : object
        Scalar value returned from one DuckDB row.

    Returns
    -------
    int
        Integer form of ``value``.
    """

    return int(cast("str | bytes | bytearray | int", value))


def _duckdb_bytes(value: object) -> bytes:
    """
    Coerce one DuckDB row value into raw bytes.

    Parameters
    ----------
    value : object
        Scalar value returned from one DuckDB row.

    Returns
    -------
    bytes
        Raw byte representation of ``value``.
    """

    return bytes(cast("bytes | bytearray", value))


@dataclass
class DuckDBIdAllocator:
    """
    Allocate explicit DuckDB row identifiers for buffered inserts.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection used to discover current table maxima.
    _next_by_table : dict[str, int]
        Lazily populated next identifiers keyed by table name.
    """

    conn: _DuckDBPersistenceConnection
    _next_by_table: dict[str, int] = field(default_factory=dict)

    def next_id(self, table_name: str) -> int:
        """
        Return the next explicit identifier for one table.

        Parameters
        ----------
        table_name : str
            Table whose integer ``id`` should be allocated.

        Returns
        -------
        int
            Next identifier greater than the current table maximum.
        """
        if table_name not in self._next_by_table:
            row = self.conn.execute(
                f"SELECT COALESCE(MAX(id), 0) FROM {table_name}"
            ).fetchone()
            assert row is not None
            self._next_by_table[table_name] = _duckdb_int(row[0]) + 1
        next_id = self._next_by_table[table_name]
        self._next_by_table[table_name] = next_id + 1
        return next_id


@dataclass
class DuckDBStructuralRowBuffers:
    """
    Hold structural rows before one bulk DuckDB flush.

    Parameters
    ----------
    files : list[FileRow]
        Pending file rows.
    modules : list[ModuleRow]
        Pending module rows.
    classes : list[ClassRow]
        Pending class rows.
    functions : list[FunctionRow]
        Pending function rows.
    symbol_index : list[SymbolIndexRow]
        Pending symbol-index rows.
    documentation_artifacts : list[DocumentationArtifactRow]
        Pending documentation artifact rows.
    overloads : list[OverloadRow]
        Pending overload rows.
    enum_members : list[EnumMemberRow]
        Pending enum-member rows.
    """

    files: list[FileRow] = field(default_factory=list)
    modules: list[ModuleRow] = field(default_factory=list)
    classes: list[ClassRow] = field(default_factory=list)
    functions: list[FunctionRow] = field(default_factory=list)
    symbol_index: list[SymbolIndexRow] = field(default_factory=list)
    documentation_artifacts: list[DocumentationArtifactRow] = field(
        default_factory=list
    )
    overloads: list[OverloadRow] = field(default_factory=list)
    enum_members: list[EnumMemberRow] = field(default_factory=list)

    def clear(self) -> None:
        """
        Clear every pending structural row buffer.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Buffers are emptied in place.
        """
        self.files.clear()
        self.modules.clear()
        self.classes.clear()
        self.functions.clear()
        self.symbol_index.clear()
        self.documentation_artifacts.clear()
        self.overloads.clear()
        self.enum_members.clear()


@dataclass(frozen=True)
class CallResolutionRequest:
    """
    Request parameters for parsed call resolution.

    Parameters
    ----------
    call : dict[str, str | int]
        Parsed call-site record.
    caller_module : str
        Module containing the caller.
    caller_class : str | None
        Owning class for method callers.
    import_aliases : dict[str, str]
        Mapping of locally bound import names to imported dotted targets.
    module_functions : dict[str, set[str]]
        Known top-level functions keyed by module name.
    class_methods : dict[tuple[str, str], set[str]]
        Known method names keyed by ``(module_name, class_name)``.
    """

    call: dict[str, str | int]
    caller_module: str
    caller_class: str | None
    import_aliases: dict[str, str]
    module_functions: dict[str, set[str]]
    class_methods: dict[tuple[str, str], set[str]]


@dataclass(frozen=True)
class EmbeddingTextRequest:
    """
    Request parameters for deterministic embedding text construction.

    Parameters
    ----------
    module_name : str
        Dotted module name that owns the symbol.
    symbol_name : str
        Logical symbol name.
    symbol_type : str
        Indexed symbol type.
    signature : str | None
        Callable signature when present.
    docstring : str | None
        Symbol docstring when present.
    extra_context : tuple[str, ...]
        Additional deterministic semantic context lines.
    """

    module_name: str
    symbol_name: str
    symbol_type: str
    signature: str | None = None
    docstring: str | None = None
    extra_context: tuple[str, ...] = ()


@dataclass(frozen=True)
class SymbolIndexInsertRequest:
    """
    Request parameters for inserting one symbol-index row.

    Parameters
    ----------
    name : str
        Symbol name stored in the index.
    stable_id : str
        Durable analyzer-owned symbol identity.
    symbol_type : str
        Stable symbol kind stored in the index.
    module_name : str
        Module name owning the symbol.
    file_id : int
        Integer identifier of the owner file.
    lineno : int
        Source line of the indexed symbol.
    """

    name: str
    stable_id: str
    symbol_type: str
    module_name: str
    file_id: int
    lineno: int


@dataclass(frozen=True)
class EmbeddingRowRequest:
    """
    Request parameters for appending a pending embedding row.

    Parameters
    ----------
    symbol_row_id : int
        Inserted symbol row identifier referenced by the embedding.
    stable_id : str
        Durable analyzer-owned symbol identity.
    module_name : str
        Module name owning the symbol.
    symbol_name : str
        Logical symbol name used for embedding text.
    symbol_type : str
        Stable symbol kind used for embedding text.
    signature : str | None
        Callable or declaration signature when available.
    docstring : str | None
        Symbol docstring when available.
    extra_context : tuple[str, ...]
        Additional analyzer-specific context lines.
    """

    symbol_row_id: int
    stable_id: str
    module_name: str
    symbol_name: str
    symbol_type: str
    signature: str | None = None
    docstring: str | None = None
    extra_context: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocstringIssueRequest:
    """
    Request parameters for docstring issue persistence.

    Parameters
    ----------
    file_id : int
        Integer identifier of the owner file.
    label : str
        Stable artifact label prefixed onto each issue message.
    docstring : str | None
        Artifact docstring to validate.
    is_public : int
        Public-visibility flag passed to the validator.
    function_id : int | None
        Function row identifier when the issues belong to a callable.
    class_id : int | None
        Class row identifier when the issues belong to a class.
    module_id : int | None
        Module row identifier when the issues belong to a module.
    parameters : list[str] | None
        Callable parameters used by the validator.
    require_callable_sections : bool
        Whether callable-specific sections must be present.
    yields_value : bool
        Whether the callable yields values.
    returns_value : bool
        Whether the callable returns values.
    raises_exception : bool
        Whether the callable raises exceptions.
    root : pathlib.Path
        Repository root whose config selects audit routes.
    source_path : pathlib.Path
        Source file owning the artifact.
    stable_id : str
        Stable analyzer-owned artifact identifier.
    symbol_name : str
        Artifact name shown in diagnostics.
    artifact_kind : str
        Artifact kind shown to plugins.
    """

    file_id: int
    label: str
    docstring: str | None
    is_public: int
    root: Path
    source_path: Path
    stable_id: str
    symbol_name: str
    artifact_kind: str
    function_id: int | None = None
    class_id: int | None = None
    module_id: int | None = None
    parameters: list[str] | None = None
    require_callable_sections: bool = False
    yields_value: bool = False
    returns_value: bool = False
    raises_exception: bool = False


@dataclass(frozen=True)
class ArtifactPersistenceRequest:
    """
    Request parameters shared by artifact persistence helpers.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    file_id : int
        Integer identifier of the owner file.
    module_id : int
        Inserted module row identifier.
    module_name : str
        Module name owning the artifacts.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    c_embedding_context : tuple[str, ...]
        C-family embedding context reused by declarations and classes.
    embedding_rows : list[PendingEmbeddingRow]
        Pending embedding rows collected for the file.
    call_rows : list[CallRow]
        Pending call rows collected for the file.
    ref_rows : list[RefRow]
        Pending callable-reference rows collected for the file.
    pending_docstring_issue_rows : list[DocstringIssueRow] | None
        Optional session-level docstring issue buffer.
    structural_rows : DuckDBStructuralRowBuffers
        Pending structural row buffers for explicit-ID bulk inserts.
    id_allocator : DuckDBIdAllocator
        Explicit-ID allocator shared across structural tables.
    root : pathlib.Path | None
        Repository root whose config selects audit routes.
    """

    conn: _DuckDBPersistenceConnection
    file_id: int
    module_id: int
    module_name: str
    analysis: AnalysisResult
    c_embedding_context: tuple[str, ...]
    embedding_rows: list[PendingEmbeddingRow]
    call_rows: list[CallRow]
    ref_rows: list[RefRow]
    pending_docstring_issue_rows: list[DocstringIssueRow] | None = None
    structural_rows: DuckDBStructuralRowBuffers | None = None
    id_allocator: DuckDBIdAllocator | None = None
    root: Path | None = None


@dataclass(frozen=True)
class EnumMemberPersistenceRequest:
    """
    Request parameters for enum-member metadata persistence.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    file_id : int
        Inserted file row identifier that owns the enum declaration.
    module_name : str
        Module name that owns the enum declaration.
    symbol_name : str
        Canonical enum declaration name.
    symbol_lineno : int
        Canonical enum declaration line number.
    enum_members : tuple[codira.models.EnumMemberArtifact, ...]
        Ordered enum-member declarations attached to the enum.
    structural_rows : DuckDBStructuralRowBuffers
        Pending structural row buffers for explicit-ID bulk inserts.
    """

    conn: _DuckDBPersistenceConnection
    file_id: int
    module_name: str
    symbol_name: str
    symbol_lineno: int
    enum_members: tuple[EnumMemberArtifact, ...]
    structural_rows: DuckDBStructuralRowBuffers


def _record_tuple(
    file_id: int,
    owner_module: str,
    owner_name: str,
    record: CallSite,
) -> CallRow:
    """
    Normalize one raw call-style record for DuckDB persistence.

    Parameters
    ----------
    file_id : int
        Integer identifier of the owner file.
    owner_module : str
        Owning module name.
    owner_name : str
        Logical owner name.
    record : codira.models.CallSite
        Normalized call-site record.

    Returns
    -------
    CallRow
        Normalized DuckDB row values.
    """
    return (
        file_id,
        owner_module,
        owner_name,
        record.kind,
        record.base,
        record.target,
        record.external_target_kind,
        record.external_target_name,
        record.lineno,
        record.col_offset,
    )


def _reference_tuple(
    file_id: int,
    owner_module: str,
    owner_name: str,
    record: CallableReference,
) -> RefRow:
    """
    Normalize one callable-reference record for DuckDB persistence.

    Parameters
    ----------
    file_id : int
        Integer identifier of the owner file.
    owner_module : str
        Owning module name.
    owner_name : str
        Logical owner name.
    record : codira.models.CallableReference
        Normalized callable-reference record.

    Returns
    -------
    RefRow
        Normalized DuckDB row values.
    """
    return (
        file_id,
        owner_module,
        owner_name,
        record.kind,
        record.ref_kind,
        record.base,
        record.target,
        record.external_target_kind,
        record.external_target_name,
        record.lineno,
        record.col_offset,
    )


def _insert_symbol_index_row(
    structural_rows: DuckDBStructuralRowBuffers,
    id_allocator: DuckDBIdAllocator,
    request: SymbolIndexInsertRequest,
) -> int:
    """
    Buffer one symbol-index row and return its explicit identifier.

    Parameters
    ----------
    structural_rows : DuckDBStructuralRowBuffers
        Pending structural row buffers.
    id_allocator : DuckDBIdAllocator
        Explicit-ID allocator for the current write session.
    request : SymbolIndexInsertRequest
        Symbol-index row insert request.

    Returns
    -------
    int
        Allocated symbol row identifier.
    """
    symbol_row_id = id_allocator.next_id("symbol_index")
    structural_rows.symbol_index.append(
        (
            symbol_row_id,
            request.name,
            request.stable_id,
            request.symbol_type,
            request.module_name,
            request.file_id,
            request.lineno,
        )
    )
    return symbol_row_id


def _append_embedding_row(
    embedding_rows: list[PendingEmbeddingRow],
    request: EmbeddingRowRequest,
) -> None:
    """
    Append one normalized symbol embedding payload to the pending batch.

    Parameters
    ----------
    embedding_rows : list[codira.indexer.PendingEmbeddingRow]
        Pending embedding rows collected for the current file.
    request : EmbeddingRowRequest
        Pending embedding row request.

    Returns
    -------
    None
        The embedding row is appended in place.
    """
    embedding_rows.append(
        PendingEmbeddingRow(
            object_type="symbol",
            object_id=request.symbol_row_id,
            stable_id=request.stable_id,
            text=_embedding_text(
                EmbeddingTextRequest(
                    module_name=request.module_name,
                    symbol_name=request.symbol_name,
                    symbol_type=request.symbol_type,
                    signature=request.signature,
                    docstring=request.docstring,
                    extra_context=request.extra_context,
                )
            ),
        )
    )


def _insert_documentation_artifact(
    structural_rows: DuckDBStructuralRowBuffers,
    id_allocator: DuckDBIdAllocator,
    *,
    file_id: int,
    artifact: DocumentationArtifact,
) -> int:
    """
    Buffer one documentation artifact and return its explicit identifier.

    Parameters
    ----------
    structural_rows : DuckDBStructuralRowBuffers
        Pending structural row buffers.
    id_allocator : DuckDBIdAllocator
        Explicit-ID allocator for the current write session.
    file_id : int
        Integer identifier of the owner file.
    artifact : codira.models.DocumentationArtifact
        Normalized documentation artifact emitted by an analyzer.

    Returns
    -------
    int
        Allocated documentation row identifier.
    """
    documentation_id = id_allocator.next_id("documentation_artifacts")
    structural_rows.documentation_artifacts.append(
        (
            documentation_id,
            file_id,
            artifact.stable_id,
            artifact.kind,
            artifact.source_format,
            artifact.lineno,
            artifact.end_lineno,
            artifact.title,
            json.dumps(list(artifact.heading_path)),
            artifact.text,
            artifact.owner_stable_id,
            artifact.owner_kind,
            artifact.attachment_confidence,
        )
    )
    return documentation_id


def _persist_documentation_artifacts(
    *,
    structural_rows: DuckDBStructuralRowBuffers,
    id_allocator: DuckDBIdAllocator,
    file_id: int,
    analysis: AnalysisResult,
    embedding_rows: list[PendingEmbeddingRow],
) -> None:
    """
    Persist analyzer-emitted documentation artifacts for one file.

    Parameters
    ----------
    structural_rows : DuckDBStructuralRowBuffers
        Pending structural row buffers.
    id_allocator : DuckDBIdAllocator
        Explicit-ID allocator for the current write session.
    file_id : int
        Integer identifier of the owner file.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    embedding_rows : list[codira.contracts.PendingEmbeddingRow]
        Pending embedding rows collected for the file.

    Returns
    -------
    None
        Documentation rows and embedding payloads are appended in place.
    """
    for artifact in analysis.documentation:
        documentation_id = _insert_documentation_artifact(
            structural_rows,
            id_allocator,
            file_id=file_id,
            artifact=artifact,
        )
        embedding_rows.append(
            PendingEmbeddingRow(
                object_type="documentation",
                object_id=documentation_id,
                stable_id=artifact.stable_id,
                text=artifact.text,
            )
        )


def _persist_docstring_issues(
    conn: _DuckDBPersistenceConnection,
    request: DocstringIssueRequest,
    *,
    pending_rows: list[DocstringIssueRow] | None = None,
) -> None:
    """
    Persist docstring-audit findings for one indexed artifact.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    request : DocstringIssueRequest
        Docstring issue persistence request.
    pending_rows : list[DocstringIssueRow] | None, optional
        Session-level issue buffer used to batch inserts across files.

    Returns
    -------
    None
        Matching docstring issues are inserted in place.
    """
    issue_rows = [
        (
            request.file_id,
            request.function_id,
            request.class_id,
            request.module_id,
            issue.issue_type,
            issue.message,
            issue.audit_language,
            issue.audit_plugin_name,
            issue.audit_plugin_version,
            issue.convention_name,
            issue.convention_version,
            issue.rule_id,
            str(issue.severity),
        )
        for issue in validate_documentation_issues_with_configured_plugin(
            root=request.root,
            source_path=request.source_path,
            stable_id=request.stable_id,
            symbol_name=request.symbol_name,
            artifact_kind=request.artifact_kind,
            label=request.label,
            doc=request.docstring,
            is_public=request.is_public,
            parameters=request.parameters,
            require_callable_sections=request.require_callable_sections,
            yields_value=request.yields_value,
            returns_value=request.returns_value,
            raises_exception=request.raises_exception,
        )
    ]
    if issue_rows:
        if pending_rows is None:
            _flush_docstring_issue_rows(conn, issue_rows)
        else:
            pending_rows.extend(issue_rows)


def _persist_module_artifacts(
    conn: _DuckDBPersistenceConnection,
    *,
    file_id: int,
    root: Path,
    analysis: AnalysisResult,
    embedding_rows: list[PendingEmbeddingRow],
    structural_rows: DuckDBStructuralRowBuffers,
    id_allocator: DuckDBIdAllocator,
    pending_docstring_issue_rows: list[DocstringIssueRow] | None = None,
) -> tuple[str, int, tuple[str, ...]]:
    """
    Persist module-level rows for one analyzed file.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    file_id : int
        Integer identifier of the owner file.
    root : pathlib.Path
        Repository root whose config selects audit routes.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    embedding_rows : list[codira.indexer.PendingEmbeddingRow]
        Pending embedding rows collected for the file.
    structural_rows : DuckDBStructuralRowBuffers
        Pending structural row buffers.
    id_allocator : DuckDBIdAllocator
        Explicit-ID allocator for the current write session.
    pending_docstring_issue_rows : list[DocstringIssueRow] | None, optional
        Session-level docstring issue buffer.

    Returns
    -------
    tuple[str, int, tuple[str, ...]]
        Module name, inserted module row identifier, and C-family embedding
        context for downstream artifacts.
    """
    module = analysis.module
    module_name = module.name
    c_embedding_context = _c_embedding_context(analysis)
    module_id = id_allocator.next_id("modules")
    structural_rows.modules.append(
        (
            module_id,
            file_id,
            module_name,
            module.docstring,
            module.has_docstring,
        )
    )
    symbol_row_id = _insert_symbol_index_row(
        structural_rows,
        id_allocator,
        SymbolIndexInsertRequest(
            name=module_name,
            stable_id=module.stable_id,
            symbol_type="module",
            module_name=module_name,
            file_id=file_id,
            lineno=1,
        ),
    )
    _append_embedding_row(
        embedding_rows,
        EmbeddingRowRequest(
            symbol_row_id=symbol_row_id,
            stable_id=module.stable_id,
            module_name=module_name,
            symbol_name=module_name,
            symbol_type="module",
            docstring=module.docstring,
            extra_context=c_embedding_context,
        ),
    )
    _persist_docstring_issues(
        conn,
        DocstringIssueRequest(
            file_id=file_id,
            module_id=module_id,
            label=f"Module {module_name}",
            docstring=module.docstring,
            is_public=int(_should_audit_docstrings(analysis.source_path)),
            root=root,
            source_path=analysis.source_path,
            stable_id=module.stable_id,
            symbol_name=module_name,
            artifact_kind="module",
        ),
        pending_rows=pending_docstring_issue_rows,
    )
    return module_name, module_id, c_embedding_context


def _persist_class_artifacts(request: ArtifactPersistenceRequest) -> None:
    """
    Persist classes and methods for one analyzed file.

    Parameters
    ----------
    request : ArtifactPersistenceRequest
        Artifact persistence request carrying shared file state.

    Returns
    -------
    None
        Class and method rows are inserted in place.
    """
    conn = request.conn
    file_id = request.file_id
    module_id = request.module_id
    module_name = request.module_name
    analysis = request.analysis
    c_embedding_context = request.c_embedding_context
    embedding_rows = request.embedding_rows
    call_rows = request.call_rows
    ref_rows = request.ref_rows
    pending_docstring_issue_rows = request.pending_docstring_issue_rows
    structural_rows = request.structural_rows
    id_allocator = request.id_allocator
    root = request.root
    assert structural_rows is not None
    assert id_allocator is not None
    assert root is not None

    for cls in analysis.classes:
        class_id = id_allocator.next_id("classes")
        structural_rows.classes.append(
            (
                class_id,
                module_id,
                cls.name,
                cls.lineno,
                cls.end_lineno,
                cls.docstring,
                cls.has_docstring,
            )
        )
        symbol_row_id = _insert_symbol_index_row(
            structural_rows,
            id_allocator,
            SymbolIndexInsertRequest(
                name=cls.name,
                stable_id=cls.stable_id,
                symbol_type="class",
                module_name=module_name,
                file_id=file_id,
                lineno=cls.lineno,
            ),
        )
        _append_embedding_row(
            embedding_rows,
            EmbeddingRowRequest(
                symbol_row_id=symbol_row_id,
                stable_id=cls.stable_id,
                module_name=module_name,
                symbol_name=cls.name,
                symbol_type="class",
                docstring=cls.docstring,
                extra_context=c_embedding_context,
            ),
        )
        if _should_audit_docstrings(analysis.source_path):
            _persist_docstring_issues(
                conn,
                DocstringIssueRequest(
                    file_id=file_id,
                    class_id=class_id,
                    label=f"Class {cls.name}",
                    docstring=cls.docstring,
                    is_public=1,
                    root=root,
                    source_path=analysis.source_path,
                    stable_id=cls.stable_id,
                    symbol_name=cls.name,
                    artifact_kind="class",
                ),
                pending_rows=pending_docstring_issue_rows,
            )

        for method in cls.methods:
            logical_name = _qualified_callable_name(method.name, cls.name)
            python_embedding_context = _python_embedding_context(
                analysis,
                method,
                class_name=cls.name,
            )
            function_id = id_allocator.next_id("functions")
            structural_rows.functions.append(
                (
                    function_id,
                    module_id,
                    class_id,
                    method.name,
                    method.lineno,
                    method.end_lineno,
                    method.signature,
                    method.docstring,
                    method.has_docstring,
                    method.is_method,
                    method.is_public,
                )
            )
            symbol_row_id = _insert_symbol_index_row(
                structural_rows,
                id_allocator,
                SymbolIndexInsertRequest(
                    name=method.name,
                    stable_id=method.stable_id,
                    symbol_type="method",
                    module_name=module_name,
                    file_id=file_id,
                    lineno=method.lineno,
                ),
            )
            _append_embedding_row(
                embedding_rows,
                EmbeddingRowRequest(
                    symbol_row_id=symbol_row_id,
                    stable_id=method.stable_id,
                    module_name=module_name,
                    symbol_name=logical_name,
                    symbol_type="method",
                    signature=method.signature,
                    docstring=method.docstring,
                    extra_context=python_embedding_context or c_embedding_context,
                ),
            )
            if _should_audit_docstrings(analysis.source_path):
                _persist_docstring_issues(
                    conn,
                    DocstringIssueRequest(
                        file_id=file_id,
                        function_id=function_id,
                        label=f"Method {cls.name}.{method.name}",
                        docstring=method.docstring,
                        is_public=method.is_public,
                        root=root,
                        source_path=analysis.source_path,
                        stable_id=method.stable_id,
                        symbol_name=logical_name,
                        artifact_kind="method",
                        parameters=list(method.parameters),
                        require_callable_sections=True,
                        yields_value=bool(method.yields_value),
                        returns_value=bool(method.returns_value),
                        raises_exception=bool(method.raises)
                        and _should_require_raises_section(
                            analysis.source_path, method.name
                        ),
                    ),
                    pending_rows=pending_docstring_issue_rows,
                )
            _persist_overload_artifacts(
                function_id=function_id,
                overloads=method.overloads,
                structural_rows=structural_rows,
            )
            for call in method.calls:
                call_rows.append(
                    _record_tuple(file_id, module_name, logical_name, call)
                )
            for ref in method.callable_refs:
                ref_rows.append(
                    _reference_tuple(file_id, module_name, logical_name, ref)
                )


def _persist_function_artifacts(request: ArtifactPersistenceRequest) -> None:
    """
    Persist top-level functions for one analyzed file.

    Parameters
    ----------
    request : ArtifactPersistenceRequest
        Artifact persistence request carrying shared file state.

    Returns
    -------
    None
        Function rows are inserted in place.
    """
    conn = request.conn
    file_id = request.file_id
    module_id = request.module_id
    module_name = request.module_name
    analysis = request.analysis
    c_embedding_context = request.c_embedding_context
    embedding_rows = request.embedding_rows
    call_rows = request.call_rows
    ref_rows = request.ref_rows
    pending_docstring_issue_rows = request.pending_docstring_issue_rows
    structural_rows = request.structural_rows
    id_allocator = request.id_allocator
    root = request.root
    assert structural_rows is not None
    assert id_allocator is not None
    assert root is not None

    for fn in analysis.functions:
        python_embedding_context = _python_embedding_context(analysis, fn)
        function_id = id_allocator.next_id("functions")
        structural_rows.functions.append(
            (
                function_id,
                module_id,
                None,
                fn.name,
                fn.lineno,
                fn.end_lineno,
                fn.signature,
                fn.docstring,
                fn.has_docstring,
                fn.is_method,
                fn.is_public,
            )
        )
        symbol_row_id = _insert_symbol_index_row(
            structural_rows,
            id_allocator,
            SymbolIndexInsertRequest(
                name=fn.name,
                stable_id=fn.stable_id,
                symbol_type="function",
                module_name=module_name,
                file_id=file_id,
                lineno=fn.lineno,
            ),
        )
        _append_embedding_row(
            embedding_rows,
            EmbeddingRowRequest(
                symbol_row_id=symbol_row_id,
                stable_id=fn.stable_id,
                module_name=module_name,
                symbol_name=fn.name,
                symbol_type="function",
                signature=fn.signature,
                docstring=fn.docstring,
                extra_context=python_embedding_context or c_embedding_context,
            ),
        )
        if _should_audit_docstrings(analysis.source_path):
            _persist_docstring_issues(
                conn,
                DocstringIssueRequest(
                    file_id=file_id,
                    function_id=function_id,
                    label=f"Function {fn.name}",
                    docstring=fn.docstring,
                    is_public=fn.is_public,
                    root=root,
                    source_path=analysis.source_path,
                    stable_id=fn.stable_id,
                    symbol_name=fn.name,
                    artifact_kind="function",
                    parameters=list(fn.parameters),
                    require_callable_sections=True,
                    yields_value=bool(fn.yields_value),
                    returns_value=bool(fn.returns_value),
                    raises_exception=bool(fn.raises)
                    and _should_require_raises_section(analysis.source_path, fn.name),
                ),
                pending_rows=pending_docstring_issue_rows,
            )
        _persist_overload_artifacts(
            function_id=function_id,
            overloads=fn.overloads,
            structural_rows=structural_rows,
        )
        for call in fn.calls:
            call_rows.append(_record_tuple(file_id, module_name, fn.name, call))
        for ref in fn.callable_refs:
            ref_rows.append(_reference_tuple(file_id, module_name, fn.name, ref))


def _persist_overload_artifacts(
    *,
    function_id: int,
    overloads: tuple[OverloadArtifact, ...],
    structural_rows: DuckDBStructuralRowBuffers,
) -> None:
    """
    Persist overload metadata rows for one canonical callable.

    Parameters
    ----------
    function_id : int
        Inserted function row identifier that owns the overloads.
    overloads : tuple[codira.models.OverloadArtifact, ...]
        Ordered overload declarations attached to the callable.
    structural_rows : DuckDBStructuralRowBuffers
        Pending structural row buffers.

    Returns
    -------
    None
        Overload rows are inserted in place.
    """
    overload_rows = [
        (
            function_id,
            overload.stable_id,
            overload.parent_stable_id,
            overload.ordinal,
            overload.signature,
            overload.docstring,
            overload.lineno,
            overload.end_lineno,
        )
        for overload in overloads
    ]
    structural_rows.overloads.extend(overload_rows)


def _persist_enum_member_artifacts(request: EnumMemberPersistenceRequest) -> None:
    """
    Persist enum-member metadata rows for one canonical enum declaration.

    Parameters
    ----------
    request : EnumMemberPersistenceRequest
        Persistence request describing the owning enum and attached members.

    Returns
    -------
    None
        Enum-member rows are inserted in place.
    """
    enum_member_rows = [
        (
            request.file_id,
            request.module_name,
            request.symbol_name,
            request.symbol_lineno,
            enum_member.stable_id,
            enum_member.parent_stable_id,
            enum_member.ordinal,
            enum_member.name,
            enum_member.signature,
            enum_member.lineno,
        )
        for enum_member in request.enum_members
    ]
    request.structural_rows.enum_members.extend(enum_member_rows)


def _persist_declaration_artifacts(request: ArtifactPersistenceRequest) -> None:
    """
    Persist declaration-style symbol artifacts for one analyzed file.

    Parameters
    ----------
    request : ArtifactPersistenceRequest
        Artifact persistence request carrying shared file state.

    Returns
    -------
    None
        Declaration symbol rows are inserted in place.
    """
    conn = request.conn
    file_id = request.file_id
    module_name = request.module_name
    analysis = request.analysis
    c_embedding_context = request.c_embedding_context
    embedding_rows = request.embedding_rows
    structural_rows = request.structural_rows
    id_allocator = request.id_allocator
    assert structural_rows is not None
    assert id_allocator is not None

    for decl in analysis.declarations:
        symbol_row_id = _insert_symbol_index_row(
            structural_rows,
            id_allocator,
            SymbolIndexInsertRequest(
                name=decl.name,
                stable_id=decl.stable_id,
                symbol_type=decl.kind,
                module_name=module_name,
                file_id=file_id,
                lineno=decl.lineno,
            ),
        )
        _append_embedding_row(
            embedding_rows,
            EmbeddingRowRequest(
                symbol_row_id=symbol_row_id,
                stable_id=decl.stable_id,
                module_name=module_name,
                symbol_name=decl.name,
                symbol_type=decl.kind,
                signature=decl.signature,
                docstring=decl.docstring,
                extra_context=c_embedding_context,
            ),
        )
        _persist_enum_member_artifacts(
            EnumMemberPersistenceRequest(
                conn=conn,
                file_id=file_id,
                module_name=module_name,
                symbol_name=decl.name,
                symbol_lineno=decl.lineno,
                enum_members=decl.enum_members,
                structural_rows=structural_rows,
            )
        )


def _persist_import_artifacts(
    conn: _DuckDBPersistenceConnection,
    *,
    module_id: int,
    analysis: AnalysisResult,
    pending_rows: list[ImportRow] | None = None,
) -> None:
    """
    Persist import rows for one analyzed file.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    module_id : int
        Inserted module row identifier.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    pending_rows : list[ImportRow] | None, optional
        Session-level import row buffer used to batch inserts across files.

    Returns
    -------
    None
        Import rows are inserted in place.
    """
    import_rows: list[ImportRow] = [
        (module_id, imp.name, imp.alias, imp.kind, imp.lineno)
        for imp in analysis.imports
    ]
    if import_rows:
        if pending_rows is None:
            _flush_import_rows(conn, import_rows)
        else:
            pending_rows.extend(import_rows)


def _flush_persisted_relationship_rows(
    conn: _DuckDBPersistenceConnection,
    *,
    call_rows: list[CallRow],
    ref_rows: list[RefRow],
    pending_call_rows: list[CallRow] | None = None,
    pending_ref_rows: list[RefRow] | None = None,
) -> None:
    """
    Flush pending call and callable-reference rows to DuckDB.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    call_rows : list[CallRow]
        Pending normalized call rows.
    ref_rows : list[RefRow]
        Pending normalized callable-reference rows.
    pending_call_rows : list[CallRow] | None, optional
        Session-level call-record buffer. When supplied, rows are appended for
        one later backend batch.
    pending_ref_rows : list[RefRow] | None, optional
        Session-level callable-reference buffer. When supplied, rows are
        appended for one later backend batch.

    Returns
    -------
    None
        Relationship rows are inserted in deterministic order.
    """
    deduplicated_call_rows = sorted(set(call_rows))
    if deduplicated_call_rows:
        if pending_call_rows is None:
            _flush_call_record_rows(conn, deduplicated_call_rows)
        else:
            pending_call_rows.extend(deduplicated_call_rows)

    deduplicated_ref_rows = sorted(set(ref_rows))
    if deduplicated_ref_rows:
        if pending_ref_rows is None:
            _flush_callable_ref_record_rows(conn, deduplicated_ref_rows)
        else:
            pending_ref_rows.extend(deduplicated_ref_rows)


def _flush_docstring_issue_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[DocstringIssueRow],
) -> None:
    """
    Flush docstring issue rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[DocstringIssueRow]
        Docstring issue rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.
    """
    if not rows:
        return

    import pyarrow as pa

    file_ids: list[int] = []
    function_ids: list[int | None] = []
    class_ids: list[int | None] = []
    module_ids: list[int | None] = []
    issue_types: list[str] = []
    messages: list[str] = []
    audit_languages: list[str] = []
    audit_plugin_names: list[str] = []
    audit_plugin_versions: list[str] = []
    convention_names: list[str] = []
    convention_versions: list[str] = []
    rule_ids: list[str] = []
    severities: list[str] = []
    for (
        file_id,
        function_id,
        class_id,
        module_id,
        issue_type,
        message,
        audit_language,
        audit_plugin_name,
        audit_plugin_version,
        convention_name,
        convention_version,
        rule_id,
        severity,
    ) in rows:
        file_ids.append(file_id)
        function_ids.append(function_id)
        class_ids.append(class_id)
        module_ids.append(module_id)
        issue_types.append(issue_type)
        messages.append(message)
        audit_languages.append(audit_language)
        audit_plugin_names.append(audit_plugin_name)
        audit_plugin_versions.append(audit_plugin_version)
        convention_names.append(convention_name)
        convention_versions.append(convention_version)
        rule_ids.append(rule_id)
        severities.append(severity)

    table = pa.table(
        {
            "file_id": pa.array(file_ids, type=pa.int64()),
            "function_id": pa.array(function_ids, type=pa.int64()),
            "class_id": pa.array(class_ids, type=pa.int64()),
            "module_id": pa.array(module_ids, type=pa.int64()),
            "issue_type": pa.array(issue_types, type=pa.string()),
            "message": pa.array(messages, type=pa.string()),
            "audit_language": pa.array(audit_languages, type=pa.string()),
            "audit_plugin_name": pa.array(audit_plugin_names, type=pa.string()),
            "audit_plugin_version": pa.array(audit_plugin_versions, type=pa.string()),
            "convention_name": pa.array(convention_names, type=pa.string()),
            "convention_version": pa.array(convention_versions, type=pa.string()),
            "rule_id": pa.array(rule_ids, type=pa.string()),
            "severity": pa.array(severities, type=pa.string()),
        }
    )
    view_name = "__codira_pending_docstring_issue_rows"
    conn.register(view_name, table)
    try:
        conn.execute(
            """
            INSERT INTO docstring_issues(
                file_id,
                function_id,
                class_id,
                module_id,
                issue_type,
                message,
                audit_language,
                audit_plugin_name,
                audit_plugin_version,
                convention_name,
                convention_version,
                rule_id,
                severity
            )
            SELECT
                file_id,
                function_id,
                class_id,
                module_id,
                issue_type,
                message,
                audit_language,
                audit_plugin_name,
                audit_plugin_version,
                convention_name,
                convention_version,
                rule_id,
                severity
            FROM __codira_pending_docstring_issue_rows
            """
        )
    finally:
        conn.unregister(view_name)


def _flush_import_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[ImportRow],
) -> None:
    """
    Flush import rows to DuckDB through an Arrow replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[ImportRow]
        Import rows to persist.

    Returns
    -------
    None
        Rows are inserted in place.
    """
    if not rows:
        return

    import pyarrow as pa

    module_ids: list[int] = []
    names: list[str] = []
    aliases: list[str | None] = []
    kinds: list[str] = []
    line_numbers: list[int] = []
    for module_id, name, alias, kind, lineno in rows:
        module_ids.append(module_id)
        names.append(name)
        aliases.append(alias)
        kinds.append(kind)
        line_numbers.append(lineno)

    table = pa.table(
        {
            "module_id": pa.array(module_ids, type=pa.int64()),
            "name": pa.array(names, type=pa.string()),
            "alias": pa.array(aliases, type=pa.string()),
            "kind": pa.array(kinds, type=pa.string()),
            "lineno": pa.array(line_numbers, type=pa.int64()),
        }
    )
    view_name = "__codira_pending_import_rows"
    conn.register(view_name, table)
    try:
        conn.execute(
            """
            INSERT INTO imports(module_id, name, alias, kind, lineno)
            SELECT module_id, name, alias, kind, lineno
            FROM __codira_pending_import_rows
            """
        )
    finally:
        conn.unregister(view_name)


def _flush_call_record_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[CallRow],
    *,
    profiler: DuckDBProfileRecorder | None = None,
) -> None:
    """
    Flush raw call records to DuckDB.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[CallRow]
        Normalized call rows.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for CSV staging spans.

    Returns
    -------
    None
        Call records are inserted in place.
    """
    if not rows:
        return

    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    with active_profiler.span("csv.write.call_records", rows=len(rows)):
        csv_path = _temporary_csv_path_for_rows(rows)
    try:
        with active_profiler.span("csv.read_csv.call_records", rows=len(rows)):
            conn.execute(
                """
                INSERT INTO call_records(
                    file_id,
                    owner_module,
                    owner_name,
                    kind,
                    base,
                    target,
                    external_target_kind,
                    external_target_name,
                    lineno,
                    col_offset
                )
                SELECT *
                FROM read_csv(
                    ?,
                    header=false,
                    nullstr='__CODIRA_NULL_SENTINEL__',
                    columns={
                        'file_id': 'INTEGER',
                        'owner_module': 'VARCHAR',
                        'owner_name': 'VARCHAR',
                        'kind': 'VARCHAR',
                        'base': 'VARCHAR',
                        'target': 'VARCHAR',
                        'external_target_kind': 'VARCHAR',
                        'external_target_name': 'VARCHAR',
                        'lineno': 'INTEGER',
                        'col_offset': 'INTEGER'
                    }
                )
                """,
                (str(csv_path),),
            )
    finally:
        try:
            csv_path.unlink()
        except FileNotFoundError:
            pass


def _flush_callable_ref_record_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[RefRow],
    *,
    profiler: DuckDBProfileRecorder | None = None,
) -> None:
    """
    Flush raw callable-reference records to DuckDB.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[RefRow]
        Normalized callable-reference rows.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for CSV staging spans.

    Returns
    -------
    None
        Callable-reference records are inserted in place.
    """
    if not rows:
        return

    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    with active_profiler.span("csv.write.callable_ref_records", rows=len(rows)):
        csv_path = _temporary_csv_path_for_rows(rows)
    try:
        with active_profiler.span("csv.read_csv.callable_ref_records", rows=len(rows)):
            conn.execute(
                """
                INSERT INTO callable_ref_records(
                    file_id,
                    owner_module,
                    owner_name,
                    kind,
                    ref_kind,
                    base,
                    target,
                    external_target_kind,
                    external_target_name,
                    lineno,
                    col_offset
                )
                SELECT *
                FROM read_csv(
                    ?,
                    header=false,
                    nullstr='__CODIRA_NULL_SENTINEL__',
                    columns={
                        'file_id': 'INTEGER',
                        'owner_module': 'VARCHAR',
                        'owner_name': 'VARCHAR',
                        'kind': 'VARCHAR',
                        'ref_kind': 'VARCHAR',
                        'base': 'VARCHAR',
                        'target': 'VARCHAR',
                        'external_target_kind': 'VARCHAR',
                        'external_target_name': 'VARCHAR',
                        'lineno': 'INTEGER',
                        'col_offset': 'INTEGER'
                    }
                )
                """,
                (str(csv_path),),
            )
    finally:
        try:
            csv_path.unlink()
        except FileNotFoundError:
            pass
