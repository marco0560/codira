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
from collections.abc import Iterator, Mapping, Sequence
import csv
import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeVar, cast

from codira.contracts import (
    BackendError,
    EmbeddingIndexingMetrics,
    EmbeddingIndexingPolicy,
    PendingEmbeddingRow,
    PreparedVectorRow,
    StoredEmbeddingRow,
    filter_embedding_rows_for_policy,
)
from codira.docstring import DocstringValidationRequest, validate_docstring
from codira.plugin_config import analyzer_inventory_discovery_json
from codira.repository_scope import path_has_excluded_tree_name
from codira.semantic.embeddings import (
    deserialize_vector,
    embed_texts as embed_texts,
    embeddings_enabled,
    serialize_vector,
)
from .profiling import DuckDBProfileRecorder

if TYPE_CHECKING:
    from codira.contracts import LanguageAnalyzer, VectorSetIdentity, VectorStore
    from codira.models import (
        AnalysisResult,
        CallableReference,
        CallSite,
        DocumentationArtifact,
        EnumMemberArtifact,
        FileMetadataSnapshot,
        FunctionArtifact,
        OverloadArtifact,
    )
    from codira.semantic.embeddings import EmbeddingBackendSpec
    from codira.types import ReferenceSearchRow

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
DocstringIssueRow = tuple[int, int | None, int | None, int | None, str, str]
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
    """

    file_id: int
    label: str
    docstring: str | None
    is_public: int
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


def _clear_index_tables(conn: _DuckDBPersistenceConnection) -> None:
    """
    Remove all indexed rows from the database tables.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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


def _purge_skipped_docstring_issues(conn: _DuckDBPersistenceConnection) -> None:
    """
    Remove persisted docstring issues for files excluded from audit policy.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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


def _qualified_callable_name(name: str, class_name: str | None = None) -> str:
    """
    Build the logical name used for call-graph identity.

    Parameters
    ----------
    name : str
        Unqualified function or method name.
    class_name : str | None, optional
        Owning class name for methods.

    Returns
    -------
    str
        ``Class.method`` for methods and the bare function name otherwise.
    """
    if class_name is None:
        return name
    return f"{class_name}.{name}"  # nosemgrep: python.flask.security.audit.directly-returned-format-string.directly-returned-format-string


def _import_alias_map(imports: list[dict[str, object]]) -> dict[str, str]:
    """
    Build a deterministic alias map for imported names.

    Parameters
    ----------
    imports : list[dict[str, object]]
        Parsed import rows from a module.

    Returns
    -------
    dict[str, str]
        Mapping from the locally bound import name to the imported dotted
        target.
    """
    aliases: dict[str, str] = {}

    for imp in imports:
        imported = str(imp["name"])
        alias = imp["alias"]
        local_name = str(alias) if alias is not None else imported.split(".")[-1]

        if "." in imported and alias is None and "." not in local_name:
            aliases[imported] = imported

        aliases[local_name] = imported

    return aliases


def _resolve_imported_function(
    imported: str,
    module_functions: dict[str, set[str]],
) -> tuple[str, str] | None:
    """
    Resolve a directly imported same-repo function target.

    Parameters
    ----------
    imported : str
        Imported dotted target as recorded by the parser.
    module_functions : dict[str, set[str]]
        Known top-level functions keyed by module name.

    Returns
    -------
    tuple[str, str] | None
        Resolved ``(callee_module, callee_name)`` pair, or ``None`` when the
        import does not name a straightforward same-repo function.
    """
    if "." not in imported:
        return None

    module_name, function_name = imported.rsplit(".", 1)
    if function_name in module_functions.get(module_name, set()):
        return (module_name, function_name)
    return None


def _resolve_module_attribute_call(
    base: str,
    target: str,
    import_aliases: dict[str, str],
    module_functions: dict[str, set[str]],
) -> tuple[str, str] | None:
    """
    Resolve a module-qualified same-repo function call.

    Parameters
    ----------
    base : str
        Static base expression of the attribute call.
    target : str
        Attribute name being called.
    import_aliases : dict[str, str]
        Mapping of locally bound import names to imported dotted targets.
    module_functions : dict[str, set[str]]
        Known top-level functions keyed by module name.

    Returns
    -------
    tuple[str, str] | None
        Resolved ``(callee_module, callee_name)`` pair, or ``None`` when the
        call cannot be resolved conservatively.
    """
    imported = import_aliases.get(base)
    if imported is None:
        return None

    if target in module_functions.get(imported, set()):
        return (imported, target)
    return None


def _resolve_call_record(
    request: CallResolutionRequest,
) -> tuple[str | None, str | None, int]:
    """
    Resolve one parsed call-site record into a stored call edge.

    Parameters
    ----------
    request : CallResolutionRequest
        Call resolution request carrying caller context and symbol maps.

    Returns
    -------
    tuple[str | None, str | None, int]
        ``(callee_module, callee_name, resolved)`` for the call edge.
    """
    kind = str(request.call.get("kind", "unresolved"))
    target = str(request.call.get("target", ""))

    candidates: set[tuple[str, str]] = set()

    if kind == "name" and target:
        imported = request.import_aliases.get(target)
        if imported is not None:
            resolved_import = _resolve_imported_function(
                imported,
                request.module_functions,
            )
            if resolved_import is not None:
                candidates.add(resolved_import)

        if target in request.module_functions.get(request.caller_module, set()):
            candidates.add((request.caller_module, target))

    elif kind == "attribute" and target:
        base = str(request.call.get("base", ""))
        if request.caller_class is not None and base in {"self", "cls"}:
            methods = request.class_methods.get(
                (request.caller_module, request.caller_class),
                set(),
            )
            if target in methods:
                candidates.add(
                    (
                        request.caller_module,
                        _qualified_callable_name(target, request.caller_class),
                    )
                )

        methods = request.class_methods.get((request.caller_module, base), set())
        if target in methods:
            candidates.add(
                (request.caller_module, _qualified_callable_name(target, base))
            )

        resolved_module_call = _resolve_module_attribute_call(
            base,
            target,
            request.import_aliases,
            request.module_functions,
        )
        if resolved_module_call is not None:
            candidates.add(resolved_module_call)

    if len(candidates) == 1:
        callee_module, callee_name = next(iter(candidates))
        return (callee_module, callee_name, 1)

    return (None, None, 0)


def _unresolved_identity(record: CallRecord, *, resolved: int) -> str:
    """
    Return the stable unresolved-target identity for one derived edge.

    Parameters
    ----------
    record : CallRecord
        Raw call-style record that produced the derived relation.
    resolved : int
        Stored relation resolution flag.

    Returns
    -------
    str
        Empty string for resolved relations, otherwise a deterministic raw
        target identity that distinguishes different unresolved callees owned
        by the same caller.
    """
    if resolved:
        return ""
    return json.dumps(
        (
            str(record.get("kind", "")),
            str(record.get("base", "")),
            str(record.get("target", "")),
        ),
        separators=(",", ":"),
    )


def _embedding_text(request: EmbeddingTextRequest) -> str:
    """
    Build the deterministic text payload embedded for one symbol.

    Parameters
    ----------
    request : EmbeddingTextRequest
        Embedding text construction request.

    Returns
    -------
    str
        Joined text payload used for embedding generation.
    """
    parts = [request.symbol_type, request.module_name, request.symbol_name]
    if request.signature:
        parts.append(request.signature)
    if request.docstring:
        parts.append(request.docstring)
    parts.extend(line for line in request.extra_context if line)
    return "\n".join(parts)


def _embedding_content_hash(text: str) -> str:
    """
    Return the deterministic content hash for one embedding payload.

    Parameters
    ----------
    text : str
        Exact semantic payload used for embedding generation.

    Returns
    -------
    str
        Hex-encoded SHA-256 digest of ``text``.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _c_embedding_context(analysis: AnalysisResult) -> tuple[str, ...]:
    """
    Build extra semantic context lines for C-family embedding payloads.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for one indexed source file.

    Returns
    -------
    tuple[str, ...]
        Deterministic C-specific semantic context lines.
    """
    if analysis.source_path.suffix.lower() not in {".c", ".h"}:
        return ()

    context: list[str] = []

    if analysis.module.docstring:
        context.append(f"module summary: {analysis.module.docstring}")

    local_includes = tuple(
        imp.name for imp in analysis.imports if imp.kind == "include_local"
    )
    system_includes = tuple(
        imp.name for imp in analysis.imports if imp.kind == "include_system"
    )

    if local_includes:
        context.append("local includes: " + ", ".join(local_includes))
    if system_includes:
        context.append("system includes: " + ", ".join(system_includes))

    source_path = analysis.source_path
    suffix = source_path.suffix.lower()
    paired_path: Path | None = None

    if suffix == ".c":
        candidate = source_path.with_suffix(".h")
        if candidate.exists():
            paired_path = candidate
    elif suffix == ".h":
        candidate = source_path.with_suffix(".c")
        if candidate.exists():
            paired_path = candidate

    if paired_path is not None:
        pair_label = "paired header" if suffix == ".c" else "paired source"
        try:
            pair_rel_path = paired_path.relative_to(source_path.parents[1])
        except ValueError:
            pair_rel_path = paired_path
        context.append(f"{pair_label}: {pair_rel_path.as_posix()}")

    return tuple(context)


def _python_embedding_context(
    analysis: AnalysisResult,
    function: FunctionArtifact,
    *,
    class_name: str | None = None,
) -> tuple[str, ...]:
    """
    Build extra semantic context lines for Python callable embedding payloads.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for one indexed source file.
    function : codira.models.FunctionArtifact
        Function or method artifact receiving the embedding payload.
    class_name : str | None, optional
        Owning class name for method artifacts.

    Returns
    -------
    tuple[str, ...]
        Deterministic Python-specific semantic context lines.
    """
    if analysis.source_path.suffix.lower() != ".py":
        return ()

    context: list[str] = []

    if analysis.module.docstring:
        context.append(f"module summary: {analysis.module.docstring}")

    if class_name is not None:
        context.append(f"owner class: {class_name}")

    if function.has_asserts:
        context.append("assertions: present")

    decorators = function.decorators
    if decorators:
        context.append("decorators: " + ", ".join(decorators))

    if any(name in {"fixture", "pytest.fixture"} for name in decorators):
        context.append("fixture context: pytest fixture")

    if function.name in {
        "setup",
        "setUp",
        "setup_class",
        "setup_method",
        "setup_function",
        "tearDown",
        "teardown",
        "teardown_class",
        "teardown_method",
        "teardown_function",
    }:
        context.append(f"setup context: {function.name}")

    return tuple(context)


def _load_module_functions(conn: _DuckDBPersistenceConnection) -> dict[str, set[str]]:
    """
    Load known top-level functions from indexed structural tables.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    dict[str, set[str]]
        Top-level function names keyed by module name.
    """
    rows = conn.execute("""
        SELECT m.name, f.name
        FROM functions f
        JOIN modules m
          ON f.module_id = m.id
        WHERE f.class_id IS NULL
        ORDER BY m.name, f.name
        """).fetchall()
    module_functions: dict[str, set[str]] = {}
    for module_name, function_name in rows:
        module_functions.setdefault(str(module_name), set()).add(str(function_name))
    return module_functions


def _load_class_methods(
    conn: _DuckDBPersistenceConnection,
) -> dict[tuple[str, str], set[str]]:
    """
    Load known methods from indexed structural tables.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    dict[tuple[str, str], set[str]]
        Method names keyed by ``(module_name, class_name)``.
    """
    rows = conn.execute("""
        SELECT m.name, c.name, f.name
        FROM functions f
        JOIN classes c
          ON f.class_id = c.id
        JOIN modules m
          ON f.module_id = m.id
        ORDER BY m.name, c.name, f.name
        """).fetchall()
    class_methods: dict[tuple[str, str], set[str]] = {}
    for module_name, class_name, method_name in rows:
        key = (str(module_name), str(class_name))
        class_methods.setdefault(key, set()).add(str(method_name))
    return class_methods


def _load_import_aliases(
    conn: _DuckDBPersistenceConnection,
) -> dict[str, dict[str, str]]:
    """
    Load import alias maps for indexed modules.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    dict[str, dict[str, str]]
        Alias maps keyed by owning module name.
    """
    rows = conn.execute("""
        SELECT m.name, i.name, i.alias
        FROM imports i
        JOIN modules m
          ON i.module_id = m.id
        WHERE i.kind = 'import'
        ORDER BY m.name, i.lineno, i.name, COALESCE(i.alias, '')
        """).fetchall()
    imports_by_module: dict[str, list[dict[str, object]]] = {}
    for module_name, import_name, alias in rows:
        imports_by_module.setdefault(str(module_name), []).append(
            {
                "name": str(import_name),
                "alias": None if alias is None else str(alias),
            }
        )

    return {
        module_name: _import_alias_map(imports)
        for module_name, imports in imports_by_module.items()
    }


def _caller_class_from_owner(owner_name: str) -> str | None:
    """
    Derive the owning class name from a logical callable owner.

    Parameters
    ----------
    owner_name : str
        Logical callable owner name.

    Returns
    -------
    str | None
        Owning class name for methods, or ``None`` for top-level functions.
    """
    if "." not in owner_name:
        return None
    class_name, _method_name = owner_name.rsplit(".", 1)
    return class_name


def _rebuild_graph_indexes(conn: _DuckDBPersistenceConnection) -> None:
    """
    Rebuild derived call and callable-reference edges from stored raw records.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    None
        The derived edge tables are replaced in place.
    """
    module_functions = _load_module_functions(conn)
    class_methods = _load_class_methods(conn)
    import_aliases_by_module = _load_import_aliases(conn)

    conn.execute("DROP TABLE IF EXISTS temp_call_edges_rebuild")
    conn.execute("DROP TABLE IF EXISTS temp_callable_refs_rebuild")
    conn.execute("""
        CREATE TEMP TABLE temp_call_edges_rebuild (
            caller_file_id INTEGER NOT NULL,
            caller_module TEXT NOT NULL,
            caller_name TEXT NOT NULL,
            callee_module TEXT,
            callee_name TEXT,
            unresolved_identity TEXT NOT NULL,
            external_target_kind TEXT,
            external_target_name TEXT,
            resolved INTEGER NOT NULL
        )
        """)
    conn.execute("""
        CREATE TEMP TABLE temp_callable_refs_rebuild (
            owner_file_id INTEGER NOT NULL,
            owner_module TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            target_module TEXT,
            target_name TEXT,
            unresolved_identity TEXT NOT NULL,
            external_target_kind TEXT,
            external_target_name TEXT,
            resolved INTEGER NOT NULL
        )
        """)

    edges: set[
        tuple[
            int,
            str,
            str,
            str | None,
            str | None,
            str,
            str | None,
            str | None,
            int,
        ]
    ] = set()
    refs: set[
        tuple[
            int,
            str,
            str,
            str | None,
            str | None,
            str,
            str | None,
            str | None,
            int,
        ]
    ] = set()

    call_rows = conn.execute("""
        SELECT
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
        FROM call_records
        ORDER BY
            file_id,
            owner_module,
            owner_name,
            lineno,
            col_offset,
            kind,
            base,
            target
        """).fetchall()
    for (
        file_id,
        owner_module,
        owner_name,
        kind,
        base,
        target,
        external_target_kind,
        external_target_name,
        _lineno,
        _col_offset,
    ) in call_rows:
        record = cast(
            "CallRecord",
            {
                "kind": str(kind),
                "base": str(base),
                "target": str(target),
            },
        )
        caller_module = str(owner_module)
        caller_name = str(owner_name)
        callee_module, callee_name, resolved = _resolve_call_record(
            CallResolutionRequest(
                call=record,
                caller_module=caller_module,
                caller_class=_caller_class_from_owner(caller_name),
                import_aliases=import_aliases_by_module.get(caller_module, {}),
                module_functions=module_functions,
                class_methods=class_methods,
            )
        )
        edge_external_target_kind = (
            None
            if resolved or external_target_kind is None
            else str(external_target_kind)
        )
        edge_external_target_name = (
            None
            if resolved or external_target_name is None
            else str(external_target_name)
        )
        edges.add(
            (
                _duckdb_int(file_id),
                caller_module,
                caller_name,
                callee_module,
                callee_name,
                _unresolved_identity(record, resolved=resolved),
                edge_external_target_kind,
                edge_external_target_name,
                resolved,
            )
        )

    ref_rows = conn.execute("""
        SELECT
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
        FROM callable_ref_records
        ORDER BY
            file_id,
            owner_module,
            owner_name,
            lineno,
            col_offset,
            kind,
            base,
            target
        """).fetchall()
    for (
        file_id,
        owner_module,
        owner_name,
        kind,
        base,
        target,
        external_target_kind,
        external_target_name,
        _lineno,
        _col_offset,
    ) in ref_rows:
        record = cast(
            "CallRecord",
            {
                "kind": str(kind),
                "base": str(base),
                "target": str(target),
            },
        )
        caller_module = str(owner_module)
        caller_name = str(owner_name)
        target_module, target_name, resolved = _resolve_call_record(
            CallResolutionRequest(
                call=record,
                caller_module=caller_module,
                caller_class=_caller_class_from_owner(caller_name),
                import_aliases=import_aliases_by_module.get(caller_module, {}),
                module_functions=module_functions,
                class_methods=class_methods,
            )
        )
        ref_external_target_kind = (
            None
            if resolved or external_target_kind is None
            else str(external_target_kind)
        )
        ref_external_target_name = (
            None
            if resolved or external_target_name is None
            else str(external_target_name)
        )
        refs.add(
            (
                _duckdb_int(file_id),
                caller_module,
                caller_name,
                target_module,
                target_name,
                _unresolved_identity(record, resolved=resolved),
                ref_external_target_kind,
                ref_external_target_name,
                resolved,
            )
        )

    sorted_edges = sorted(
        edges,
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3] or "",
            item[4] or "",
            item[5],
            item[6] or "",
            item[7] or "",
            item[8],
        ),
    )
    if sorted_edges:
        import pyarrow as pa

        table = pa.table(
            {
                "caller_file_id": pa.array(
                    [row[0] for row in sorted_edges],
                    type=pa.int64(),
                ),
                "caller_module": pa.array(
                    [row[1] for row in sorted_edges],
                    type=pa.string(),
                ),
                "caller_name": pa.array(
                    [row[2] for row in sorted_edges],
                    type=pa.string(),
                ),
                "callee_module": pa.array(
                    [row[3] for row in sorted_edges],
                    type=pa.string(),
                ),
                "callee_name": pa.array(
                    [row[4] for row in sorted_edges],
                    type=pa.string(),
                ),
                "unresolved_identity": pa.array(
                    [row[5] for row in sorted_edges],
                    type=pa.string(),
                ),
                "external_target_kind": pa.array(
                    [row[6] for row in sorted_edges],
                    type=pa.string(),
                ),
                "external_target_name": pa.array(
                    [row[7] for row in sorted_edges],
                    type=pa.string(),
                ),
                "resolved": pa.array([row[8] for row in sorted_edges], type=pa.int64()),
            }
        )
        _flush_registered_arrow_table(
            conn,
            view_name="__codira_temp_call_edge_rows",
            table=table,
            insert_sql="""
                INSERT INTO temp_call_edges_rebuild(
                    caller_file_id,
                    caller_module,
                    caller_name,
                    callee_module,
                    callee_name,
                    unresolved_identity,
                    external_target_kind,
                    external_target_name,
                    resolved
                )
                SELECT
                    caller_file_id,
                    caller_module,
                    caller_name,
                    callee_module,
                    callee_name,
                    unresolved_identity,
                    external_target_kind,
                    external_target_name,
                    resolved
                FROM __codira_temp_call_edge_rows
                """,
        )

    sorted_refs = sorted(
        refs,
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3] or "",
            item[4] or "",
            item[5],
            item[6] or "",
            item[7] or "",
            item[8],
        ),
    )
    if sorted_refs:
        import pyarrow as pa

        table = pa.table(
            {
                "owner_file_id": pa.array(
                    [row[0] for row in sorted_refs],
                    type=pa.int64(),
                ),
                "owner_module": pa.array(
                    [row[1] for row in sorted_refs],
                    type=pa.string(),
                ),
                "owner_name": pa.array(
                    [row[2] for row in sorted_refs],
                    type=pa.string(),
                ),
                "target_module": pa.array(
                    [row[3] for row in sorted_refs],
                    type=pa.string(),
                ),
                "target_name": pa.array(
                    [row[4] for row in sorted_refs],
                    type=pa.string(),
                ),
                "unresolved_identity": pa.array(
                    [row[5] for row in sorted_refs],
                    type=pa.string(),
                ),
                "external_target_kind": pa.array(
                    [row[6] for row in sorted_refs],
                    type=pa.string(),
                ),
                "external_target_name": pa.array(
                    [row[7] for row in sorted_refs],
                    type=pa.string(),
                ),
                "resolved": pa.array([row[8] for row in sorted_refs], type=pa.int64()),
            }
        )
        _flush_registered_arrow_table(
            conn,
            view_name="__codira_temp_callable_ref_rows",
            table=table,
            insert_sql="""
                INSERT INTO temp_callable_refs_rebuild(
                    owner_file_id,
                    owner_module,
                    owner_name,
                    target_module,
                    target_name,
                    unresolved_identity,
                    external_target_kind,
                    external_target_name,
                    resolved
                )
                SELECT
                    owner_file_id,
                    owner_module,
                    owner_name,
                    target_module,
                    target_name,
                    unresolved_identity,
                    external_target_kind,
                    external_target_name,
                    resolved
                FROM __codira_temp_callable_ref_rows
                """,
        )

    for statement in _DERIVED_GRAPH_INDEX_DROP_DDL:
        conn.execute(statement)
    conn.execute("DROP TABLE call_edges")
    conn.execute("DROP TABLE callable_refs")
    conn.execute(_CALL_EDGES_REBUILD_TABLE_DDL)
    conn.execute(_CALLABLE_REFS_REBUILD_TABLE_DDL)
    conn.execute("""
        INSERT INTO call_edges(
            caller_file_id,
            caller_module,
            caller_name,
            callee_module,
            callee_name,
            unresolved_identity,
            external_target_kind,
            external_target_name,
            resolved
        )
        SELECT
            caller_file_id,
            caller_module,
            caller_name,
            callee_module,
            callee_name,
            unresolved_identity,
            external_target_kind,
            external_target_name,
            resolved
        FROM temp_call_edges_rebuild
        """)
    conn.execute("""
        INSERT INTO callable_refs(
            owner_file_id,
            owner_module,
            owner_name,
            target_module,
            target_name,
            unresolved_identity,
            external_target_kind,
            external_target_name,
            resolved
        )
        SELECT
            owner_file_id,
            owner_module,
            owner_name,
            target_module,
            target_name,
            unresolved_identity,
            external_target_kind,
            external_target_name,
            resolved
        FROM temp_callable_refs_rebuild
        """)
    for statement in _DERIVED_GRAPH_INDEX_DDL:
        conn.execute(statement)
    conn.execute("DROP TABLE temp_call_edges_rebuild")
    conn.execute("DROP TABLE temp_callable_refs_rebuild")


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
            issue_type,
            f"{request.label}: {message}",
        )
        for issue_type, message in validate_docstring(
            DocstringValidationRequest(
                doc=request.docstring,
                is_public=request.is_public,
                parameters=request.parameters or [],
                require_callable_sections=request.require_callable_sections,
                yields_value=request.yields_value,
                returns_value=request.returns_value,
                raises_exception=request.raises_exception,
            )
        )
    ]
    if issue_rows:
        if pending_rows is None:
            _flush_docstring_issue_rows(conn, issue_rows)
        else:
            pending_rows.extend(issue_rows)


def _should_audit_docstrings(source_path: Path) -> bool:
    """
    Decide whether one source file participates in docstring auditing.

    Parameters
    ----------
    source_path : pathlib.Path
        Source file path whose indexed artifacts are being audited.

    Returns
    -------
    bool
        ``True`` when docstring issues should be emitted for the file.

    Notes
    -----
    Shell scripts and shell functions do not follow the project's NumPy-style
    docstring contract. Treating Bash artifacts like Python callables produces
    deterministic but semantically invalid audit noise, so they are excluded.
    """
    return source_path.suffix not in {
        ".sh",
        ".bash",
    } and not path_has_excluded_tree_name(source_path)


def _should_require_raises_section(source_path: Path, function_name: str) -> bool:
    """
    Decide whether a callable should require a ``Raises`` docstring section.

    Parameters
    ----------
    source_path : pathlib.Path
        Source file path owning the callable.
    function_name : str
        Callable name as stored in the index.

    Returns
    -------
    bool
        ``True`` when explicit raises should require a ``Raises`` section.

    Notes
    -----
    Pytest-style ``test_*`` callables often use local ``raise`` statements as
    assertion fallbacks. Requiring ``Raises`` sections for those tests creates
    audit noise without improving user-facing documentation quality.
    """
    return not (
        "tests" in source_path.parts
        and source_path.suffix == ".py"
        and function_name.startswith("test_")
    )


def _persist_module_artifacts(
    conn: _DuckDBPersistenceConnection,
    *,
    file_id: int,
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
    assert structural_rows is not None
    assert id_allocator is not None

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
    assert structural_rows is not None
    assert id_allocator is not None

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


def _temporary_csv_path_for_rows(
    rows: Sequence[Sequence[object]],
) -> Path:
    """
    Write rows to a temporary CSV file for DuckDB bulk import.

    Parameters
    ----------
    rows : collections.abc.Sequence[collections.abc.Sequence[object]]
        Row values to serialize.

    Returns
    -------
    pathlib.Path
        Temporary CSV path owned by the caller.
    """
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        prefix="codira-duckdb-bulk-",
        suffix=".csv",
        delete=False,
    ) as handle:
        csv_path = Path(handle.name)
        writer = csv.writer(handle)
        writer.writerows(rows)
    return csv_path


def _flush_registered_arrow_table(
    conn: _DuckDBPersistenceConnection,
    *,
    view_name: str,
    table: object,
    insert_sql: str,
) -> None:
    """
    Insert one Arrow table through a temporary DuckDB replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    view_name : str
        Temporary replacement-scan name.
    table : object
        Arrow table accepted by DuckDB's Python replacement-scan API.
    insert_sql : str
        ``INSERT ... SELECT`` statement reading from ``view_name``.

    Returns
    -------
    None
        Rows are inserted in place and the replacement scan is unregistered.
    """
    conn.register(view_name, table)
    try:
        conn.execute(insert_sql)
    finally:
        conn.unregister(view_name)


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
    for file_id, function_id, class_id, module_id, issue_type, message in rows:
        file_ids.append(file_id)
        function_ids.append(function_id)
        class_ids.append(class_id)
        module_ids.append(module_id)
        issue_types.append(issue_type)
        messages.append(message)

    table = pa.table(
        {
            "file_id": pa.array(file_ids, type=pa.int64()),
            "function_id": pa.array(function_ids, type=pa.int64()),
            "class_id": pa.array(class_ids, type=pa.int64()),
            "module_id": pa.array(module_ids, type=pa.int64()),
            "issue_type": pa.array(issue_types, type=pa.string()),
            "message": pa.array(messages, type=pa.string()),
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
                message
            )
            SELECT
                file_id,
                function_id,
                class_id,
                module_id,
                issue_type,
                message
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
            prepared_rows.append((row, content_hash, reusable_row.vector))
            reused += 1
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

    missing_hashes = [
        content_hash
        for row, content_hash, stored_vector in prepared_rows
        if stored_vector is None
    ]
    cached_vectors = _load_cached_embedding_vectors(
        conn,
        backend=backend,
        content_hashes=missing_hashes,
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


def _load_cached_embedding_vectors(
    conn: _DuckDBPersistenceConnection,
    *,
    backend: EmbeddingBackendSpec,
    content_hashes: list[str],
) -> dict[str, bytes]:
    """
    Load reusable vectors from the persistent embedding vector cache.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    content_hashes : list[str]
        Candidate content hashes to load.

    Returns
    -------
    dict[str, bytes]
        Cached serialized vectors keyed by content hash.
    """

    ordered_hashes = list(dict.fromkeys(content_hashes))
    if not ordered_hashes:
        return {}
    placeholders = ",".join("?" for _item in ordered_hashes)
    rows = conn.execute(
        f"""
        SELECT content_hash, vector
        FROM embedding_vector_cache
        WHERE backend = ?
          AND version = ?
          AND dim = ?
          AND content_hash IN ({placeholders})
        """,
        (backend.name, backend.version, backend.dim, *ordered_hashes),
    ).fetchall()
    return {
        str(content_hash): bytes(cast("bytes", vector)) for content_hash, vector in rows
    }


def _store_cached_embedding_vectors(
    conn: _DuckDBPersistenceConnection,
    *,
    backend: EmbeddingBackendSpec,
    encoded_vectors: dict[str, bytes],
    profiler: DuckDBProfileRecorder | None = None,
) -> None:
    """
    Persist newly encoded vectors in the embedding vector cache.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    encoded_vectors : dict[str, bytes]
        Serialized vectors keyed by content hash.

    Returns
    -------
    None
        Cache rows are inserted or replaced in place.

    Raises
    ------
    codira.contracts.BackendError
        Raised when DuckDB or Arrow rejects one vector-cache batch.
    """

    if not encoded_vectors:
        return

    import pyarrow as pa

    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    ordered_vectors = sorted(encoded_vectors.items())
    for batch in _chunked_embedding_batches(ordered_vectors):
        backends: list[str] = []
        versions: list[str] = []
        dims: list[int] = []
        content_hashes: list[str] = []
        vectors: list[bytes] = []
        for content_hash, vector in batch:
            backends.append(backend.name)
            versions.append(backend.version)
            dims.append(backend.dim)
            content_hashes.append(content_hash)
            vectors.append(vector)

        try:
            with active_profiler.span(
                "arrow.build.embedding_vector_cache",
                rows=len(batch),
                payload_bytes=_cached_vector_payload_bytes(dict(batch)),
            ):
                table = pa.table(
                    {
                        "backend": pa.array(backends, type=pa.string()),
                        "version": pa.array(versions, type=pa.string()),
                        "dim": pa.array(dims, type=pa.int64()),
                        "content_hash": pa.array(content_hashes, type=pa.string()),
                        "vector": pa.array(vectors, type=pa.binary()),
                    }
                )
            with active_profiler.span(
                "arrow.flush.embedding_vector_cache",
                rows=len(batch),
                payload_bytes=_cached_vector_payload_bytes(dict(batch)),
            ):
                _flush_registered_arrow_table(
                    conn,
                    view_name="__codira_embedding_vector_cache_rows",
                    table=table,
                    insert_sql="""
                        INSERT OR REPLACE INTO embedding_vector_cache(
                            backend,
                            version,
                            dim,
                            content_hash,
                            vector
                        )
                        SELECT
                            backend,
                            version,
                            dim,
                            content_hash,
                            vector
                        FROM __codira_embedding_vector_cache_rows
                        """,
                )
        except _duckdb_batch_error_types() as exc:
            msg = _embedding_batch_backend_error(
                operation="embedding_vector_cache_insert",
                row_count=len(batch),
                payload_bytes=_cached_vector_payload_bytes(dict(batch)),
            )
            raise BackendError(msg) from exc


def _store_vector_store_materialized_rows(
    *,
    vector_store: VectorStore | None,
    vector_set_identity: VectorSetIdentity | None,
    vector_store_config: Mapping[str, object],
    root: Path | None,
    prepared_rows: list[PreparedVectorRow],
    encoded_vectors: dict[str, bytes],
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
    encoded_vectors : dict[str, bytes]
        Newly encoded vectors keyed by content hash.

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
    with active_profiler.span("vector_store.store_vectors", rows=len(prepared_rows)):
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


def _flush_prepared_embedding_rows(
    conn: _DuckDBPersistenceConnection,
    root: Path | None = None,
    *,
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
    profiler: DuckDBProfileRecorder | None = None,
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
        _store_cached_embedding_vectors(
            conn,
            backend=backend,
            encoded_vectors={
                content_hash: vector_blob
                for content_hash, (
                    vector_blob,
                    _vector_values,
                ) in encoded_vectors.items()
            },
            profiler=active_profiler,
        )

    object_types: list[str] = []
    object_ids: list[int] = []
    backends: list[str] = []
    versions: list[str] = []
    content_hashes: list[str] = []
    dims: list[int] = []
    vectors: list[bytes] = []
    vector_values_rows: list[list[float]] = []
    row_ordinals: list[int] = []
    materialized_rows: list[PreparedVectorRow] = []
    for row_ordinal, (row, content_hash, stored_vector) in enumerate(deduplicated_rows):
        resolved_blob = stored_vector
        vector_values: list[float]
        if resolved_blob is None:
            resolved_blob, vector_values = encoded_vectors[content_hash]
        else:
            vector_values = deserialize_vector(resolved_blob, dim=backend.dim)

        object_types.append(row.object_type)
        object_ids.append(row.object_id)
        backends.append(backend.name)
        versions.append(backend.version)
        content_hashes.append(content_hash)
        dims.append(backend.dim)
        vectors.append(resolved_blob)
        vector_values_rows.append(vector_values)
        row_ordinals.append(row_ordinal)
        materialized_rows.append(
            PreparedVectorRow(
                row=row,
                content_hash=content_hash,
                vector=resolved_blob,
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
        encoded_vectors={
            content_hash: vector_blob
            for content_hash, (
                vector_blob,
                _vector_values,
            ) in encoded_vectors.items()
        },
        profiler=active_profiler,
    )


def _flush_pending_embedding_rows(
    conn: _DuckDBPersistenceConnection,
    root: Path | None = None,
    *,
    pending_embedding_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
    backend: EmbeddingBackendSpec,
    vector_store: VectorStore | None = None,
    vector_set_identity: VectorSetIdentity | None = None,
    vector_store_config: Mapping[str, object] | None = None,
    profiler: DuckDBProfileRecorder | None = None,
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
    _flush_prepared_embedding_rows(
        conn,
        root,
        prepared_rows=pending_embedding_rows,
        backend=backend,
        vector_store=vector_store,
        vector_set_identity=vector_set_identity,
        vector_store_config={} if vector_store_config is None else vector_store_config,
        profiler=profiler,
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
    cached_vectors = _load_cached_embedding_vectors(
        conn,
        backend=backend,
        content_hashes=[content_hash for _row, content_hash, _vector in pending_rows],
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
    conn: _DuckDBPersistenceConnection,
    *,
    file_id: int,
    path: Path,
    pending_rows: list[tuple[int, int, str]] | None = None,
) -> None:
    """
    Persist the stored reference-search surface for one indexed file.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    file_id : int
        Owning indexed file identifier.
    path : pathlib.Path
        Source file whose text should be stored for later query-time scans.
    pending_rows : list[tuple[int, int, str]] | None, optional
        Session-level reference row buffer. When supplied, rows are appended to
        the buffer and flushed by the caller in one backend batch.

    Returns
    -------
    None
        Matching non-import lines are inserted in deterministic order.
    """
    reference_rows = _reference_scan_rows(path)
    if not reference_rows:
        return

    rows = [
        (file_id, lineno, line_text) for _file_path, lineno, line_text in reference_rows
    ]
    if pending_rows is not None:
        pending_rows.extend(rows)
        return

    _flush_pending_reference_scan_rows(conn, rows)


def _flush_pending_reference_scan_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[tuple[int, int, str]],
    *,
    profiler: DuckDBProfileRecorder | None = None,
) -> None:
    """
    Flush pending reference-search rows to DuckDB in one batch.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[tuple[int, int, str]]
        Stored reference rows as ``(file_id, lineno, line_text)``.

    Returns
    -------
    None
        Pending reference rows are inserted in place.
    """
    if not rows:
        return

    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    with active_profiler.span("csv.write.reference_scan_lines", rows=len(rows)):
        csv_path = _temporary_csv_path_for_rows(rows)
    try:
        with active_profiler.span("csv.read_csv.reference_scan_lines", rows=len(rows)):
            conn.execute(
                """
                INSERT INTO reference_scan_lines(file_id, lineno, line_text)
                SELECT *
                FROM read_csv(
                    ?,
                    header=false,
                    nullstr='__CODIRA_NULL_SENTINEL__',
                    columns={
                        'file_id': 'INTEGER',
                        'lineno': 'INTEGER',
                        'line_text': 'VARCHAR'
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
        )
    module_name, module_id, c_embedding_context = _persist_module_artifacts(
        conn,
        file_id=file_id,
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


def _dot_similarity(left: list[float], right: list[float]) -> float:
    """
    Compute a dot-product similarity between normalized vectors.

    Parameters
    ----------
    left : list[float]
        Left embedding vector.
    right : list[float]
        Right embedding vector.

    Returns
    -------
    float
        Dot-product similarity score.
    """
    return sum(a * b for a, b in zip(left, right, strict=True))


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


def _load_previous_symbol_embeddings(
    conn: _DuckDBPersistenceConnection,
    file_path: str,
    *,
    backend: EmbeddingBackendSpec,
) -> dict[str, StoredEmbeddingRow]:
    """
    Load reusable stored symbol embeddings for one indexed file.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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
            dim=_duckdb_int(dim),
            vector=_duckdb_bytes(vector),
        )
        for stable_id, content_hash, dim, vector in rows
    }


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


def _prune_orphaned_embeddings(conn: _DuckDBPersistenceConnection) -> None:
    """
    Remove embedding rows whose indexed symbol owner no longer exists.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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
    return _duckdb_int(row[0])


def _load_previous_embeddings_by_path(
    conn: _DuckDBPersistenceConnection,
    paths: list[str],
    *,
    backend: EmbeddingBackendSpec,
) -> dict[str, dict[str, StoredEmbeddingRow]]:
    """
    Load reusable stored symbol embeddings for the supplied file paths.

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
    dict[str, dict[str, StoredEmbeddingRow]]
        Stored embeddings grouped by absolute file path and stable symbol
        identity.
    """
    result: dict[str, dict[str, StoredEmbeddingRow]] = {path: {} for path in paths}
    if not paths:
        return result

    rows = conn.execute(
        f"""
        SELECT
            f.path,
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
        WHERE f.path IN ({_placeholders(paths)})
          AND e.backend = ?
          AND e.version = ?
        ORDER BY f.path, s.stable_id
        """,
        (*paths, backend.name, backend.version),
    ).fetchall()
    rows.extend(
        conn.execute(
            f"""
            SELECT
                f.path,
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
            WHERE f.path IN ({_placeholders(paths)})
              AND e.backend = ?
              AND e.version = ?
            ORDER BY f.path, d.stable_id
            """,
            (*paths, backend.name, backend.version),
        ).fetchall()
    )
    for file_path, stable_id, content_hash, dim, vector in rows:
        path_key = str(file_path)
        result.setdefault(path_key, {})[str(stable_id)] = StoredEmbeddingRow(
            stable_id=str(stable_id),
            content_hash=str(content_hash),
            dim=_duckdb_int(dim),
            vector=_duckdb_bytes(vector),
        )
    return result


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


def _count_reused_embeddings(
    conn: _DuckDBPersistenceConnection,
    reused_paths: list[str],
) -> int:
    """
    Count preserved embedding rows for unchanged files.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
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

    if len(reused_paths) == _count_indexed_files(conn):
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM embeddings
            WHERE object_type IN ('symbol', 'documentation')
            """
        ).fetchone()
        assert row is not None
        return _duckdb_int(row[0])

    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT e.id
            FROM embeddings e
            JOIN symbol_index s
              ON e.object_type = 'symbol'
             AND e.object_id = s.id
            JOIN files f
              ON s.file_id = f.id
            WHERE f.path IN (SELECT * FROM unnest(?))
            UNION ALL
            SELECT e.id
            FROM embeddings e
            JOIN documentation_artifacts d
              ON e.object_type = 'documentation'
             AND e.object_id = d.id
            JOIN files f
              ON d.file_id = f.id
            WHERE f.path IN (SELECT * FROM unnest(?))
        )
        """,
        (reused_paths, reused_paths),
    ).fetchone()
    assert row is not None
    return _duckdb_int(row[0])
