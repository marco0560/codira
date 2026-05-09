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

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from codira.docstring import DocstringValidationRequest, validate_docstring
from codira.semantic.embeddings import embed_texts as embed_texts, serialize_vector

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer
    from codira.models import (
        AnalysisResult,
        CallableReference,
        CallSite,
        EnumMemberArtifact,
        FileMetadataSnapshot,
        FunctionArtifact,
        OverloadArtifact,
    )
    from codira.semantic.embeddings import EmbeddingBackendSpec
    from codira.types import ReferenceSearchRow

CallRecord = dict[str, str | int]
CallRow = tuple[int, str, str, str, str, str, int, int]
RefRow = tuple[int, str, str, str, str, str, str, int, int]


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
    conn : sqlite3.Connection
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
    """

    conn: sqlite3.Connection
    file_id: int
    module_id: int
    module_name: str
    analysis: AnalysisResult
    c_embedding_context: tuple[str, ...]
    embedding_rows: list[PendingEmbeddingRow]
    call_rows: list[CallRow]
    ref_rows: list[RefRow]


@dataclass(frozen=True)
class EnumMemberPersistenceRequest:
    """
    Request parameters for enum-member metadata persistence.

    Parameters
    ----------
    conn : sqlite3.Connection
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
    """

    conn: sqlite3.Connection
    file_id: int
    module_name: str
    symbol_name: str
    symbol_lineno: int
    enum_members: tuple[EnumMemberArtifact, ...]


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
    conn.execute("DELETE FROM symbol_index")
    conn.execute("DELETE FROM imports")
    conn.execute("DELETE FROM functions")
    conn.execute("DELETE FROM classes")
    conn.execute("DELETE FROM modules")
    conn.execute("DELETE FROM files")


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
    return f"{class_name}.{name}"


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


def _load_module_functions(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """
    Load known top-level functions from indexed structural tables.

    Parameters
    ----------
    conn : sqlite3.Connection
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


def _load_class_methods(conn: sqlite3.Connection) -> dict[tuple[str, str], set[str]]:
    """
    Load known methods from indexed structural tables.

    Parameters
    ----------
    conn : sqlite3.Connection
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


def _load_import_aliases(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """
    Load import alias maps for indexed modules.

    Parameters
    ----------
    conn : sqlite3.Connection
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


def _rebuild_graph_indexes(conn: sqlite3.Connection) -> None:
    """
    Rebuild derived call and callable-reference edges from stored raw records.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.

    Returns
    -------
    None
        The derived edge tables are replaced in place.
    """
    module_functions = _load_module_functions(conn)
    class_methods = _load_class_methods(conn)
    import_aliases_by_module = _load_import_aliases(conn)

    conn.execute("DELETE FROM call_edges")
    conn.execute("DELETE FROM callable_refs")

    edges: set[tuple[int, str, str, str | None, str | None, int]] = set()
    refs: set[tuple[int, str, str, str | None, str | None, int]] = set()

    call_rows = conn.execute("""
        SELECT
            file_id,
            owner_module,
            owner_name,
            kind,
            base,
            target,
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
        edges.add(
            (
                int(file_id),
                caller_module,
                caller_name,
                callee_module,
                callee_name,
                resolved,
            )
        )

    ref_rows = conn.execute("""
        SELECT file_id, owner_module, owner_name, kind, base, target, lineno, col_offset
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
        refs.add(
            (
                int(file_id),
                caller_module,
                caller_name,
                target_module,
                target_name,
                resolved,
            )
        )

    for edge in sorted(
        edges,
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3] or "",
            item[4] or "",
            item[5],
        ),
    ):
        conn.execute(
            "INSERT OR IGNORE INTO call_edges"
            "(caller_file_id, caller_module, caller_name, callee_module, "
            "callee_name, resolved) VALUES (?, ?, ?, ?, ?, ?)",
            edge,
        )

    for ref_row in sorted(
        refs,
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3] or "",
            item[4] or "",
            item[5],
        ),
    ):
        conn.execute(
            "INSERT OR IGNORE INTO callable_refs"
            "(owner_file_id, owner_module, owner_name, target_module, "
            "target_name, resolved) VALUES (?, ?, ?, ?, ?, ?)",
            ref_row,
        )


def _record_tuple(
    file_id: int,
    owner_module: str,
    owner_name: str,
    record: CallSite,
) -> tuple[int, str, str, str, str, str, int, int]:
    """
    Normalize one raw call-style record for SQLite persistence.

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
    tuple[int, str, str, str, str, str, int, int]
        Normalized SQLite row values.
    """
    return (
        file_id,
        owner_module,
        owner_name,
        record.kind,
        record.base,
        record.target,
        record.lineno,
        record.col_offset,
    )


def _reference_tuple(
    file_id: int,
    owner_module: str,
    owner_name: str,
    record: CallableReference,
) -> tuple[int, str, str, str, str, str, str, int, int]:
    """
    Normalize one callable-reference record for SQLite persistence.

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
    tuple[int, str, str, str, str, str, str, int, int]
        Normalized SQLite row values.
    """
    return (
        file_id,
        owner_module,
        owner_name,
        record.kind,
        record.ref_kind,
        record.base,
        record.target,
        record.lineno,
        record.col_offset,
    )


def _insert_symbol_index_row(
    conn: sqlite3.Connection,
    request: SymbolIndexInsertRequest,
) -> int:
    """
    Insert one symbol-index row and return its integer identifier.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    request : SymbolIndexInsertRequest
        Symbol-index row insert request.

    Returns
    -------
    int
        Inserted symbol row identifier.
    """
    cur = conn.execute(
        "INSERT INTO symbol_index"
        "(name, stable_id, type, module_name, file_id, lineno) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            request.name,
            request.stable_id,
            request.symbol_type,
            request.module_name,
            request.file_id,
            request.lineno,
        ),
    )
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


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


def _persist_docstring_issues(
    conn: sqlite3.Connection,
    request: DocstringIssueRequest,
) -> None:
    """
    Persist docstring-audit findings for one indexed artifact.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    request : DocstringIssueRequest
        Docstring issue persistence request.

    Returns
    -------
    None
        Matching docstring issues are inserted in place.
    """
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
    ):
        conn.execute(
            "INSERT INTO docstring_issues"
            "(file_id, function_id, class_id, module_id, issue_type, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                request.file_id,
                request.function_id,
                request.class_id,
                request.module_id,
                issue_type,
                f"{request.label}: {message}",
            ),
        )


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
    return source_path.suffix not in {".sh", ".bash"}


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
    conn: sqlite3.Connection,
    *,
    file_id: int,
    analysis: AnalysisResult,
    embedding_rows: list[PendingEmbeddingRow],
) -> tuple[str, int, tuple[str, ...]]:
    """
    Persist module-level rows for one analyzed file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    file_id : int
        Integer identifier of the owner file.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    embedding_rows : list[codira.indexer.PendingEmbeddingRow]
        Pending embedding rows collected for the file.

    Returns
    -------
    tuple[str, int, tuple[str, ...]]
        Module name, inserted module row identifier, and C-family embedding
        context for downstream artifacts.
    """
    module = analysis.module
    module_name = module.name
    c_embedding_context = _c_embedding_context(analysis)
    cur = conn.execute(
        "INSERT INTO modules"
        "(file_id, name, docstring, has_docstring) VALUES (?, ?, ?, ?)",
        (
            file_id,
            module_name,
            module.docstring,
            module.has_docstring,
        ),
    )
    assert cur.lastrowid is not None
    module_id = int(cur.lastrowid)
    symbol_row_id = _insert_symbol_index_row(
        conn,
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

    for cls in analysis.classes:
        cur = conn.execute(
            "INSERT INTO classes"
            "(module_id, name, lineno, end_lineno, docstring, has_docstring) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                module_id,
                cls.name,
                cls.lineno,
                cls.end_lineno,
                cls.docstring,
                cls.has_docstring,
            ),
        )
        assert cur.lastrowid is not None
        class_id = int(cur.lastrowid)
        symbol_row_id = _insert_symbol_index_row(
            conn,
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
            )

        for method in cls.methods:
            logical_name = _qualified_callable_name(method.name, cls.name)
            python_embedding_context = _python_embedding_context(
                analysis,
                method,
                class_name=cls.name,
            )
            cur = conn.execute(
                "INSERT INTO functions"
                "(module_id, class_id, name, lineno, end_lineno, signature, "
                "docstring, has_docstring, is_method, is_public) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
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
                ),
            )
            assert cur.lastrowid is not None
            function_id = int(cur.lastrowid)
            symbol_row_id = _insert_symbol_index_row(
                conn,
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
                )
            _persist_overload_artifacts(
                conn,
                function_id=function_id,
                overloads=method.overloads,
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

    for fn in analysis.functions:
        python_embedding_context = _python_embedding_context(analysis, fn)
        cur = conn.execute(
            "INSERT INTO functions"
            "(module_id, class_id, name, lineno, end_lineno, signature, "
            "docstring, has_docstring, is_method, is_public) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
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
            ),
        )
        assert cur.lastrowid is not None
        function_id = int(cur.lastrowid)
        symbol_row_id = _insert_symbol_index_row(
            conn,
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
            )
        _persist_overload_artifacts(
            conn,
            function_id=function_id,
            overloads=fn.overloads,
        )
        for call in fn.calls:
            call_rows.append(_record_tuple(file_id, module_name, fn.name, call))
        for ref in fn.callable_refs:
            ref_rows.append(_reference_tuple(file_id, module_name, fn.name, ref))


def _persist_overload_artifacts(
    conn: sqlite3.Connection,
    *,
    function_id: int,
    overloads: tuple[OverloadArtifact, ...],
) -> None:
    """
    Persist overload metadata rows for one canonical callable.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    function_id : int
        Inserted function row identifier that owns the overloads.
    overloads : tuple[codira.models.OverloadArtifact, ...]
        Ordered overload declarations attached to the callable.

    Returns
    -------
    None
        Overload rows are inserted in place.
    """
    for overload in overloads:
        conn.execute(
            "INSERT INTO overloads"
            "(function_id, stable_id, parent_stable_id, ordinal, signature, "
            "docstring, lineno, end_lineno) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                function_id,
                overload.stable_id,
                overload.parent_stable_id,
                overload.ordinal,
                overload.signature,
                overload.docstring,
                overload.lineno,
                overload.end_lineno,
            ),
        )


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
    for enum_member in request.enum_members:
        request.conn.execute(
            "INSERT INTO enum_members"
            "(file_id, module_name, symbol_name, symbol_lineno, stable_id, "
            "parent_stable_id, ordinal, name, signature, lineno) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            ),
        )


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

    for decl in analysis.declarations:
        symbol_row_id = _insert_symbol_index_row(
            conn,
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
            )
        )


def _persist_import_artifacts(
    conn: sqlite3.Connection,
    *,
    module_id: int,
    analysis: AnalysisResult,
) -> None:
    """
    Persist import rows for one analyzed file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    module_id : int
        Inserted module row identifier.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.

    Returns
    -------
    None
        Import rows are inserted in place.
    """
    for imp in analysis.imports:
        conn.execute(
            "INSERT INTO imports(module_id, name, alias, kind, lineno) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                module_id,
                imp.name,
                imp.alias,
                imp.kind,
                imp.lineno,
            ),
        )


def _flush_persisted_relationship_rows(
    conn: sqlite3.Connection,
    *,
    call_rows: list[tuple[int, str, str, str, str, str, int, int]],
    ref_rows: list[tuple[int, str, str, str, str, str, str, int, int]],
) -> None:
    """
    Flush pending call and callable-reference rows to SQLite.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    call_rows : list[tuple[int, str, str, str, str, str, int, int]]
        Pending normalized call rows.
    ref_rows : list[tuple[int, str, str, str, str, str, str, int, int]]
        Pending normalized callable-reference rows.

    Returns
    -------
    None
        Relationship rows are inserted in deterministic order.
    """
    for row in sorted(set(call_rows)):
        conn.execute(
            "INSERT INTO call_records"
            "(file_id, owner_module, owner_name, kind, base, target, "
            "lineno, col_offset) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )

    for ref_row in sorted(set(ref_rows)):
        conn.execute(
            "INSERT INTO callable_ref_records"
            "(file_id, owner_module, owner_name, kind, ref_kind, base, "
            "target, lineno, col_offset) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ref_row,
        )


def _flush_embedding_rows(
    conn: sqlite3.Connection,
    *,
    embedding_rows: list[PendingEmbeddingRow],
    backend: EmbeddingBackendSpec,
    previous_embeddings: dict[str, StoredEmbeddingRow] | None = None,
) -> tuple[int, int]:
    """
    Persist pending embedding payloads for one analyzed file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    embedding_rows : list[codira.indexer.PendingEmbeddingRow]
        Pending embedding payloads keyed by object type and identifier.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    previous_embeddings : dict[str, codira.indexer.StoredEmbeddingRow] | None, optional
        Stored symbol embeddings keyed by stable identity before the owner file
        was replaced.

    Returns
    -------
    tuple[int, int]
        ``(recomputed, reused)`` embedding counts for the file.
    """
    recomputed = 0
    reused = 0
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]] = []
    texts_to_encode: dict[str, str] = {}

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
            texts_to_encode.setdefault(content_hash, row.text)
            recomputed += 1

    encoded_vectors: dict[str, bytes] = {}
    if texts_to_encode:
        ordered_content_hashes = list(texts_to_encode)
        encoded_rows = embed_texts(
            [texts_to_encode[content_hash] for content_hash in ordered_content_hashes]
        )
        for content_hash, vector in zip(
            ordered_content_hashes,
            encoded_rows,
            strict=True,
        ):
            encoded_vectors[content_hash] = serialize_vector(vector)

    insert_rows: list[tuple[str, int, str, str, str, int, bytes]] = []
    for row, content_hash, stored_vector in prepared_rows:
        resolved_blob = stored_vector
        if resolved_blob is None:
            resolved_blob = encoded_vectors[content_hash]

        insert_rows.append(
            (
                row.object_type,
                row.object_id,
                backend.name,
                backend.version,
                content_hash,
                backend.dim,
                resolved_blob,
            )
        )
    conn.executemany(
        "INSERT INTO embeddings"
        "(object_type, object_id, backend, version, content_hash, dim, vector) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        insert_rows,
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
    file_metadata: FileMetadataSnapshot,
    analysis: AnalysisResult,
    *,
    backend: EmbeddingBackendSpec,
    previous_embeddings: dict[str, StoredEmbeddingRow] | None = None,
) -> tuple[int, int]:
    """
    Persist one parsed file snapshot into the index.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    file_metadata : codira.models.FileMetadataSnapshot
        Stable file metadata for the analyzed file.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    backend : EmbeddingBackendSpec
        Active embedding backend metadata.
    previous_embeddings : dict[str, codira.indexer.StoredEmbeddingRow] | None, optional
        Stored symbol embeddings captured before replacing file-owned rows.

    Returns
    -------
    tuple[int, int]
        ``(recomputed, reused)`` embedding counts for the file.
    """
    embedding_rows: list[PendingEmbeddingRow] = []
    call_rows: list[tuple[int, str, str, str, str, str, int, int]] = []
    ref_rows: list[tuple[int, str, str, str, str, str, str, int, int]] = []

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
    module_name, module_id, c_embedding_context = _persist_module_artifacts(
        conn,
        file_id=file_id,
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
    return _flush_embedding_rows(
        conn,
        embedding_rows=embedding_rows,
        backend=backend,
        previous_embeddings=previous_embeddings,
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
                json.dumps(tuple(analyzer.discovery_globs)),
            ),
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
    conn.execute("DELETE FROM reference_scan_lines WHERE file_id = ?", (file_id,))
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
