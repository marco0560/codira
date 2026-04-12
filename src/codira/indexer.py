"""Index repository symbols and docstring diagnostics into SQLite.

Responsibilities
----------------
- Coordinate file scanning, analyzer invocation, and backend persistence for each repository root.
- Collect docstring diagnostics, coverage reports, and embedding payloads while respecting analyzer inventory.
- Emit structured index reports consumed by CLI commands and regression tests.

Design principles
-----------------
Indexing maintains determinism by locking the repository, reusing analyzers/backends, and hashing files to avoid ephemeral rearrangements.

Architectural role
------------------
This module belongs to the **indexing layer** and glues together analyzers, storage, docstring validation, and embedding persistence.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.docstring import validate_docstring
from codira.models import (
    AnalysisResult,
    CallableReference,
    CallSite,
    FileMetadataSnapshot,
    FunctionArtifact,
)
from codira.registry import (
    active_index_backend,
    active_language_analyzers,
    missing_language_analyzer_hint,
)
from codira.scanner import (
    CANONICAL_SOURCE_DIRS,
    file_metadata,
    iter_canonical_project_files,
    iter_project_files,
)
from codira.semantic.embeddings import (
    EmbeddingBackendSpec,
    embed_texts,
    get_embedding_backend,
    serialize_vector,
)
from codira.sqlite_backend_support import (
    PendingEmbeddingRow,
    StoredEmbeddingRow,
    _load_previous_embeddings_by_path,
)

if TYPE_CHECKING:
    from codira_backend_sqlite import SQLiteIndexBackend as SQLiteIndexBackend

    from codira.contracts import IndexBackend, LanguageAnalyzer

CallRecord = dict[str, str | int]
ReferenceRecord = dict[str, str | int]
ParsedFile = tuple[Path, FileMetadataSnapshot, AnalysisResult]
_IGNORED_COVERAGE_SUFFIXES = frozenset({"<no-suffix>", ".md", ".txt", ".tyed"})
_BINARY_SNIFF_BYTES = 8192
__all__ = [
    "PendingEmbeddingRow",
    "StoredEmbeddingRow",
    "SQLiteIndexBackend",
    "_flush_embedding_rows",
    "index_repo",
]


def __getattr__(name: str) -> object:
    """
    Resolve historical module exports lazily during the backend packaging split.

    Parameters
    ----------
    name : str
        Module attribute requested from ``codira.indexer``.

    Returns
    -------
    object
        Lazily imported compatibility export.

    Raises
    ------
    AttributeError
        If ``name`` is not a supported compatibility export.
    """
    if name == "SQLiteIndexBackend":
        from codira_backend_sqlite import SQLiteIndexBackend

        return SQLiteIndexBackend
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


@dataclass(frozen=True)
class IndexDecision:
    """
    Deterministic per-file indexing decision.

    Parameters
    ----------
    path : str
        Absolute file path considered by the indexer.
    action : str
        Decision category such as ``indexed``, ``reused``, or ``deleted``.
    reason : str
        Stable explanation for the decision.
    """

    path: str
    action: str
    reason: str


@dataclass(frozen=True)
class CoverageIssue:
    """
    Deterministic canonical-directory coverage gap.

    Parameters
    ----------
    path : str
        Absolute path to the uncovered file.
    directory : str
        Canonical top-level directory containing the file.
    suffix : str
        File suffix reported for grouping and diagnostics.
    reason : str
        Stable explanation for why the file is uncovered.
    """

    path: str
    directory: str
    suffix: str
    reason: str


@dataclass(frozen=True)
class IndexFailure:
    """
    Deterministic per-file indexing failure diagnostic.

    Parameters
    ----------
    path : str
        Absolute path to the file that could not be indexed.
    analyzer_name : str
        Analyzer selected for the file.
    error_type : str
        Exception class name raised during analysis.
    reason : str
        Stable human-readable failure summary.
    """

    path: str
    analyzer_name: str
    error_type: str
    reason: str


@dataclass(frozen=True)
class IndexWarning:
    """
    Deterministic per-file indexing warning diagnostic.

    Parameters
    ----------
    path : str
        Absolute path to the file that emitted the warning.
    analyzer_name : str
        Analyzer selected for the file.
    warning_type : str
        Warning category class name raised during analysis.
    line : int | None
        Source line associated with the warning when available.
    reason : str
        Stable human-readable warning summary.
    """

    path: str
    analyzer_name: str
    warning_type: str
    line: int | None
    reason: str


@dataclass(frozen=True)
class IndexReport:
    """
    Summary of one indexing run.

    Parameters
    ----------
    indexed : int
        Number of files reparsed and successfully reindexed.
    reused : int
        Number of files reused without reparsing.
    deleted : int
        Number of deleted files removed from the index.
    failed : int
        Number of files skipped because analysis failed.
    embeddings_recomputed : int
        Number of embeddings written during the run.
    embeddings_reused : int
        Number of existing embeddings preserved for unchanged files.
    decisions : list[IndexDecision]
        Deterministic per-file decisions for explain mode.
    failures : list[IndexFailure]
        Deterministic per-file analysis failures recorded during the run.
    warnings : list[IndexWarning]
        Deterministic per-file analysis warnings recorded during the run.
    coverage_issues : list[CoverageIssue]
        Uncovered canonical-directory files detected during the run.
    """

    indexed: int
    reused: int
    deleted: int
    failed: int
    embeddings_recomputed: int
    embeddings_reused: int
    decisions: list[IndexDecision]
    failures: list[IndexFailure]
    warnings: list[IndexWarning]
    coverage_issues: list[CoverageIssue]


@dataclass(frozen=True)
class ProjectScanState:
    """
    Current repository scan state used for incremental planning.

    Parameters
    ----------
    analyzers_by_path : dict[str, codira.contracts.LanguageAnalyzer]
        Active analyzer selected for each tracked project file.
    metadata_by_path : dict[str, dict[str, object]]
        Current raw file metadata snapshots keyed by absolute path.
    paths : list[str]
        Deterministically ordered tracked project paths.
    """

    analyzers_by_path: dict[str, LanguageAnalyzer]
    metadata_by_path: dict[str, dict[str, object]]
    paths: list[str]


@dataclass(frozen=True)
class ExistingIndexState:
    """
    Persisted index state used to determine reuse decisions.

    Parameters
    ----------
    file_hashes : dict[str, str]
        Indexed content hashes keyed by absolute file path.
    file_ownership : dict[str, tuple[str, str]]
        Persisted analyzer ownership keyed by absolute file path.
    paths : list[str]
        Deterministically ordered indexed file paths.
    embedding_backend_matches : bool
        Whether persisted embeddings match the active embedding backend.
    """

    file_hashes: dict[str, str]
    file_ownership: dict[str, tuple[str, str]]
    paths: list[str]
    embedding_backend_matches: bool


@dataclass(frozen=True)
class IndexPlan:
    """
    Deterministic plan for one indexing pass.

    Parameters
    ----------
    indexed_paths : list[str]
        Files that must be reparsed and persisted.
    reused_paths : list[str]
        Files whose persisted data can be reused unchanged.
    deleted_paths : list[str]
        Files to remove from the persisted index.
    decisions : list[IndexDecision]
        Per-file explanations for indexed, reused, and deleted outcomes.
    """

    indexed_paths: list[str]
    reused_paths: list[str]
    deleted_paths: list[str]
    decisions: list[IndexDecision]


def _is_binary_coverage_candidate(path: Path) -> bool:
    """
    Return whether a coverage candidate should be treated as binary.

    Parameters
    ----------
    path : pathlib.Path
        Repository file to inspect conservatively.

    Returns
    -------
    bool
        ``True`` when the initial file chunk contains a NUL byte, which is
        sufficient for codira cov suppression of obvious binary files.
    """
    with path.open("rb") as handle:
        return b"\x00" in handle.read(_BINARY_SNIFF_BYTES)


def _should_ignore_coverage_gap(path: Path) -> bool:
    """
    Return whether an uncovered canonical file should be excluded from coverage.

    Parameters
    ----------
    path : pathlib.Path
        Repository file that no analyzer claimed.

    Returns
    -------
    bool
        ``True`` when the file belongs to a deliberately ignored suffix class
        or is conservatively identified as binary content.
    """
    suffix = path.suffix.lower() or "<no-suffix>"
    if suffix in _IGNORED_COVERAGE_SUFFIXES:
        return True
    return _is_binary_coverage_candidate(path)


def _audit_canonical_directory_coverage(
    root: Path,
    *,
    analyzers: list[LanguageAnalyzer],
) -> list[CoverageIssue]:
    """
    Audit canonical source directories for uncovered tracked files.

    Parameters
    ----------
    root : pathlib.Path
        Repository root being indexed.
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Active analyzers available for file routing.

    Returns
    -------
    list[CoverageIssue]
        Deterministic uncovered-file diagnostics for canonical directories.
    """
    issues: list[CoverageIssue] = []

    for path in iter_canonical_project_files(root):
        if any(analyzer.supports_path(path) for analyzer in analyzers):
            continue
        rel_path = path.relative_to(root)
        top_dir = rel_path.parts[0] if rel_path.parts else ""
        if top_dir not in CANONICAL_SOURCE_DIRS:
            continue
        if _should_ignore_coverage_gap(path):
            continue
        suffix = path.suffix.lower() or "<no-suffix>"
        issues.append(
            CoverageIssue(
                path=str(path),
                directory=top_dir,
                suffix=suffix,
                reason="no registered analyzer covers this canonical file",
            )
        )

    issues.sort(
        key=lambda issue: (
            issue.directory,
            issue.suffix,
            issue.path,
        )
    )
    return issues


def audit_repo_coverage(root: Path) -> list[CoverageIssue]:
    """
    Audit canonical-directory coverage for the active analyzer environment.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose tracked canonical files should be checked.

    Returns
    -------
    list[CoverageIssue]
        Deterministic uncovered-file diagnostics for the current analyzer set.
    """
    return _audit_canonical_directory_coverage(
        root,
        analyzers=_active_language_analyzers(),
    )


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
    call: dict[str, str | int],
    *,
    caller_module: str,
    caller_class: str | None,
    import_aliases: dict[str, str],
    module_functions: dict[str, set[str]],
    class_methods: dict[tuple[str, str], set[str]],
) -> tuple[str | None, str | None, int]:
    """
    Resolve one parsed call-site record into a stored call edge.

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

    Returns
    -------
    tuple[str | None, str | None, int]
        ``(callee_module, callee_name, resolved)`` for the call edge.
    """
    kind = str(call.get("kind", "unresolved"))
    target = str(call.get("target", ""))

    candidates: set[tuple[str, str]] = set()

    if kind == "name" and target:
        imported = import_aliases.get(target)
        if imported is not None:
            resolved_import = _resolve_imported_function(imported, module_functions)
            if resolved_import is not None:
                candidates.add(resolved_import)

        if target in module_functions.get(caller_module, set()):
            candidates.add((caller_module, target))

    elif kind == "attribute" and target:
        base = str(call.get("base", ""))
        if caller_class is not None and base in {"self", "cls"}:
            methods = class_methods.get((caller_module, caller_class), set())
            if target in methods:
                candidates.add(
                    (caller_module, _qualified_callable_name(target, caller_class))
                )

        methods = class_methods.get((caller_module, base), set())
        if target in methods:
            candidates.add((caller_module, _qualified_callable_name(target, base)))

        resolved_module_call = _resolve_module_attribute_call(
            base,
            target,
            import_aliases,
            module_functions,
        )
        if resolved_module_call is not None:
            candidates.add(resolved_module_call)

    if len(candidates) == 1:
        callee_module, callee_name = next(iter(candidates))
        return (callee_module, callee_name, 1)

    return (None, None, 0)


def _embedding_text(
    *,
    module_name: str,
    symbol_name: str,
    symbol_type: str,
    signature: str | None = None,
    docstring: str | None = None,
    extra_context: tuple[str, ...] = (),
) -> str:
    """
    Build the deterministic text payload embedded for one symbol.

    Parameters
    ----------
    module_name : str
        Dotted module name that owns the symbol.
    symbol_name : str
        Logical symbol name.
    symbol_type : str
        Indexed symbol type.
    signature : str | None, optional
        Callable signature when present.
    docstring : str | None, optional
        Symbol docstring when present.
    extra_context : tuple[str, ...], optional
        Additional deterministic semantic context lines.

    Returns
    -------
    str
        Joined text payload used for embedding generation.
    """
    parts = [symbol_type, module_name, symbol_name]
    if signature:
        parts.append(signature)
    if docstring:
        parts.append(docstring)
    parts.extend(line for line in extra_context if line)
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
            record,
            caller_module=caller_module,
            caller_class=_caller_class_from_owner(caller_name),
            import_aliases=import_aliases_by_module.get(caller_module, {}),
            module_functions=module_functions,
            class_methods=class_methods,
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
            record,
            caller_module=caller_module,
            caller_class=_caller_class_from_owner(caller_name),
            import_aliases=import_aliases_by_module.get(caller_module, {}),
            module_functions=module_functions,
            class_methods=class_methods,
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
    *,
    name: str,
    stable_id: str,
    symbol_type: str,
    module_name: str,
    file_id: int,
    lineno: int,
) -> int:
    """
    Insert one symbol-index row and return its integer identifier.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
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

    Returns
    -------
    int
        Inserted symbol row identifier.
    """
    cur = conn.execute(
        "INSERT INTO symbol_index"
        "(name, stable_id, type, module_name, file_id, lineno) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, stable_id, symbol_type, module_name, file_id, lineno),
    )
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


def _append_embedding_row(
    embedding_rows: list[PendingEmbeddingRow],
    *,
    symbol_row_id: int,
    stable_id: str,
    module_name: str,
    symbol_name: str,
    symbol_type: str,
    signature: str | None = None,
    docstring: str | None = None,
    extra_context: tuple[str, ...] = (),
) -> None:
    """
    Append one normalized symbol embedding payload to the pending batch.

    Parameters
    ----------
    embedding_rows : list[codira.indexer.PendingEmbeddingRow]
        Pending embedding rows collected for the current file.
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
    signature : str | None, optional
        Callable or declaration signature when available.
    docstring : str | None, optional
        Symbol docstring when available.
    extra_context : tuple[str, ...], optional
        Additional analyzer-specific context lines.

    Returns
    -------
    None
        The embedding row is appended in place.
    """
    embedding_rows.append(
        PendingEmbeddingRow(
            object_type="symbol",
            object_id=symbol_row_id,
            stable_id=stable_id,
            text=_embedding_text(
                module_name=module_name,
                symbol_name=symbol_name,
                symbol_type=symbol_type,
                signature=signature,
                docstring=docstring,
                extra_context=extra_context,
            ),
        )
    )


def _persist_docstring_issues(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    label: str,
    docstring: str | None,
    is_public: int,
    function_id: int | None = None,
    class_id: int | None = None,
    module_id: int | None = None,
    parameters: list[str] | None = None,
    require_callable_sections: bool = False,
    yields_value: bool = False,
    returns_value: bool = False,
    raises_exception: bool = False,
) -> None:
    """
    Persist docstring-audit findings for one indexed artifact.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    file_id : int
        Integer identifier of the owner file.
    label : str
        Stable artifact label prefixed onto each issue message.
    docstring : str | None
        Artifact docstring to validate.
    is_public : int
        Public-visibility flag passed to the validator.
    function_id : int | None, optional
        Function row identifier when the issues belong to a callable.
    class_id : int | None, optional
        Class row identifier when the issues belong to a class.
    module_id : int | None, optional
        Module row identifier when the issues belong to a module.
    parameters : list[str] | None, optional
        Callable parameters used by the validator.
    require_callable_sections : bool, optional
        Whether callable-specific sections must be present.
    yields_value : bool, optional
        Whether the callable yields values.
    returns_value : bool, optional
        Whether the callable returns values.
    raises_exception : bool, optional
        Whether the callable raises exceptions.

    Returns
    -------
    None
        Matching docstring issues are inserted in place.
    """
    for issue_type, message in validate_docstring(
        docstring,
        is_public=is_public,
        parameters=parameters or [],
        require_callable_sections=require_callable_sections,
        yields_value=yields_value,
        returns_value=returns_value,
        raises_exception=raises_exception,
    ):
        conn.execute(
            "INSERT INTO docstring_issues"
            "(file_id, function_id, class_id, module_id, issue_type, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                file_id,
                function_id,
                class_id,
                module_id,
                issue_type,
                f"{label}: {message}",
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
        name=module_name,
        stable_id=module.stable_id,
        symbol_type="module",
        module_name=module_name,
        file_id=file_id,
        lineno=1,
    )
    _append_embedding_row(
        embedding_rows,
        symbol_row_id=symbol_row_id,
        stable_id=module.stable_id,
        module_name=module_name,
        symbol_name=module_name,
        symbol_type="module",
        docstring=module.docstring,
        extra_context=c_embedding_context,
    )
    _persist_docstring_issues(
        conn,
        file_id=file_id,
        module_id=module_id,
        label=f"Module {module_name}",
        docstring=module.docstring,
        is_public=int(_should_audit_docstrings(analysis.source_path)),
    )
    return module_name, module_id, c_embedding_context


def _persist_class_artifacts(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    module_id: int,
    module_name: str,
    analysis: AnalysisResult,
    c_embedding_context: tuple[str, ...],
    embedding_rows: list[PendingEmbeddingRow],
    call_rows: list[tuple[int, str, str, str, str, str, int, int]],
    ref_rows: list[tuple[int, str, str, str, str, str, str, int, int]],
) -> None:
    """
    Persist classes and methods for one analyzed file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    file_id : int
        Integer identifier of the owner file.
    module_id : int
        Inserted module row identifier.
    module_name : str
        Module name owning the classes.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    c_embedding_context : tuple[str, ...]
        C-family embedding context reused by declarations and classes.
    embedding_rows : list[codira.indexer.PendingEmbeddingRow]
        Pending embedding rows collected for the file.
    call_rows : list[tuple[int, str, str, str, str, str, int, int]]
        Pending call rows collected for the file.
    ref_rows : list[tuple[int, str, str, str, str, str, str, int, int]]
        Pending callable-reference rows collected for the file.

    Returns
    -------
    None
        Class and method rows are inserted in place.
    """
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
            name=cls.name,
            stable_id=cls.stable_id,
            symbol_type="class",
            module_name=module_name,
            file_id=file_id,
            lineno=cls.lineno,
        )
        _append_embedding_row(
            embedding_rows,
            symbol_row_id=symbol_row_id,
            stable_id=cls.stable_id,
            module_name=module_name,
            symbol_name=cls.name,
            symbol_type="class",
            docstring=cls.docstring,
            extra_context=c_embedding_context,
        )
        if _should_audit_docstrings(analysis.source_path):
            _persist_docstring_issues(
                conn,
                file_id=file_id,
                class_id=class_id,
                label=f"Class {cls.name}",
                docstring=cls.docstring,
                is_public=1,
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
                name=method.name,
                stable_id=method.stable_id,
                symbol_type="method",
                module_name=module_name,
                file_id=file_id,
                lineno=method.lineno,
            )
            _append_embedding_row(
                embedding_rows,
                symbol_row_id=symbol_row_id,
                stable_id=method.stable_id,
                module_name=module_name,
                symbol_name=logical_name,
                symbol_type="method",
                signature=method.signature,
                docstring=method.docstring,
                extra_context=python_embedding_context or c_embedding_context,
            )
            if _should_audit_docstrings(analysis.source_path):
                _persist_docstring_issues(
                    conn,
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
                )
            for call in method.calls:
                call_rows.append(
                    _record_tuple(file_id, module_name, logical_name, call)
                )
            for ref in method.callable_refs:
                ref_rows.append(
                    _reference_tuple(file_id, module_name, logical_name, ref)
                )


def _persist_function_artifacts(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    module_id: int,
    module_name: str,
    analysis: AnalysisResult,
    c_embedding_context: tuple[str, ...],
    embedding_rows: list[PendingEmbeddingRow],
    call_rows: list[tuple[int, str, str, str, str, str, int, int]],
    ref_rows: list[tuple[int, str, str, str, str, str, str, int, int]],
) -> None:
    """
    Persist top-level functions for one analyzed file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    file_id : int
        Integer identifier of the owner file.
    module_id : int
        Inserted module row identifier.
    module_name : str
        Module name owning the functions.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    c_embedding_context : tuple[str, ...]
        C-family embedding context reused by declarations and functions.
    embedding_rows : list[codira.indexer.PendingEmbeddingRow]
        Pending embedding rows collected for the file.
    call_rows : list[tuple[int, str, str, str, str, str, int, int]]
        Pending call rows collected for the file.
    ref_rows : list[tuple[int, str, str, str, str, str, str, int, int]]
        Pending callable-reference rows collected for the file.

    Returns
    -------
    None
        Function rows are inserted in place.
    """
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
            name=fn.name,
            stable_id=fn.stable_id,
            symbol_type="function",
            module_name=module_name,
            file_id=file_id,
            lineno=fn.lineno,
        )
        _append_embedding_row(
            embedding_rows,
            symbol_row_id=symbol_row_id,
            stable_id=fn.stable_id,
            module_name=module_name,
            symbol_name=fn.name,
            symbol_type="function",
            signature=fn.signature,
            docstring=fn.docstring,
            extra_context=python_embedding_context or c_embedding_context,
        )
        if _should_audit_docstrings(analysis.source_path):
            _persist_docstring_issues(
                conn,
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
            )
        for call in fn.calls:
            call_rows.append(_record_tuple(file_id, module_name, fn.name, call))
        for ref in fn.callable_refs:
            ref_rows.append(_reference_tuple(file_id, module_name, fn.name, ref))


def _persist_declaration_artifacts(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    module_name: str,
    analysis: AnalysisResult,
    c_embedding_context: tuple[str, ...],
    embedding_rows: list[PendingEmbeddingRow],
) -> None:
    """
    Persist declaration-style symbol artifacts for one analyzed file.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    file_id : int
        Integer identifier of the owner file.
    module_name : str
        Module name owning the declarations.
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for the file.
    c_embedding_context : tuple[str, ...]
        C-family embedding context reused by declaration embeddings.
    embedding_rows : list[codira.indexer.PendingEmbeddingRow]
        Pending embedding rows collected for the file.

    Returns
    -------
    None
        Declaration symbol rows are inserted in place.
    """
    for decl in analysis.declarations:
        symbol_row_id = _insert_symbol_index_row(
            conn,
            name=decl.name,
            stable_id=decl.stable_id,
            symbol_type=decl.kind,
            module_name=module_name,
            file_id=file_id,
            lineno=decl.lineno,
        )
        _append_embedding_row(
            embedding_rows,
            symbol_row_id=symbol_row_id,
            stable_id=decl.stable_id,
            module_name=module_name,
            symbol_name=decl.name,
            symbol_type=decl.kind,
            signature=decl.signature,
            docstring=decl.docstring,
            extra_context=c_embedding_context,
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

    for row, content_hash, stored_vector in prepared_rows:
        resolved_blob = stored_vector
        if resolved_blob is None:
            resolved_blob = encoded_vectors[content_hash]

        conn.execute(
            "INSERT INTO embeddings"
            "(object_type, object_id, backend, version, content_hash, dim, vector) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row.object_type,
                row.object_id,
                backend.name,
                backend.version,
                content_hash,
                backend.dim,
                resolved_blob,
            ),
        )

    return (recomputed, reused)


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
    _persist_class_artifacts(
        conn,
        file_id=file_id,
        module_id=module_id,
        module_name=module_name,
        analysis=analysis,
        c_embedding_context=c_embedding_context,
        embedding_rows=embedding_rows,
        call_rows=call_rows,
        ref_rows=ref_rows,
    )
    _persist_function_artifacts(
        conn,
        file_id=file_id,
        module_id=module_id,
        module_name=module_name,
        analysis=analysis,
        c_embedding_context=c_embedding_context,
        embedding_rows=embedding_rows,
        call_rows=call_rows,
        ref_rows=ref_rows,
    )
    _persist_declaration_artifacts(
        conn,
        file_id=file_id,
        module_name=module_name,
        analysis=analysis,
        c_embedding_context=c_embedding_context,
        embedding_rows=embedding_rows,
    )
    _persist_import_artifacts(
        conn,
        module_id=module_id,
        analysis=analysis,
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


def _snapshot_from_metadata(meta: dict[str, object]) -> FileMetadataSnapshot:
    """
    Convert scanner metadata into the normalized file snapshot model.

    Parameters
    ----------
    meta : dict[str, object]
        Scanner metadata mapping.

    Returns
    -------
    codira.models.FileMetadataSnapshot
        Normalized file metadata snapshot.
    """
    mtime = cast("float | int", meta["mtime"])
    size = cast("int | str", meta["size"])
    return FileMetadataSnapshot(
        path=Path(str(meta["path"])),
        sha256=str(meta["hash"]),
        mtime=float(mtime),
        size=int(size),
    )


def _snapshot_with_analyzer(
    snapshot: FileMetadataSnapshot,
    analyzer: LanguageAnalyzer,
) -> FileMetadataSnapshot:
    """
    Attach analyzer ownership metadata to a file snapshot.

    Parameters
    ----------
    snapshot : codira.models.FileMetadataSnapshot
        Base file metadata snapshot.
    analyzer : codira.contracts.LanguageAnalyzer
        Analyzer responsible for the file.

    Returns
    -------
    codira.models.FileMetadataSnapshot
        Snapshot carrying analyzer ownership information.
    """
    return FileMetadataSnapshot(
        path=snapshot.path,
        sha256=snapshot.sha256,
        mtime=snapshot.mtime,
        size=snapshot.size,
        analyzer_name=str(analyzer.name),
        analyzer_version=str(analyzer.version),
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


def _active_language_analyzers() -> list[LanguageAnalyzer]:
    """
    Return the language analyzers participating in the current indexing run.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.contracts.LanguageAnalyzer]
        Analyzer instances consulted in deterministic order.
    """
    return active_language_analyzers()


def _select_language_analyzer(
    path: Path,
    analyzers: list[LanguageAnalyzer],
) -> LanguageAnalyzer:
    """
    Select the analyzer responsible for one source path.

    Parameters
    ----------
    path : pathlib.Path
        Repository file that must be analyzed.
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Analyzer instances consulted in deterministic order.

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Analyzer responsible for the file.

    Raises
    ------
    ValueError
        If no registered analyzer accepts the path.
    """
    for analyzer in analyzers:
        if analyzer.supports_path(path):
            return analyzer

    msg = f"No language analyzer registered for path: {path}"
    hint = missing_language_analyzer_hint(path)
    if hint is not None:
        msg = f"{msg}. {hint}"
    raise ValueError(msg)


def _collect_indexed_file_analyses(
    root: Path,
    indexed_paths: list[str],
    current_metadata: dict[str, dict[str, object]],
    analyzers: list[LanguageAnalyzer],
) -> tuple[list[ParsedFile], list[IndexFailure], list[IndexWarning]]:
    """
    Analyze reindexed files and collect normalized artifacts.

    Parameters
    ----------
    root : pathlib.Path
        Repository root being indexed.
    indexed_paths : list[str]
        Absolute file paths selected for reindexing.
    current_metadata : dict[str, dict[str, object]]
        Scanner metadata keyed by absolute file path.
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Analyzer instances available for path routing.

    Returns
    -------
    tuple[list[ParsedFile], list[IndexFailure], list[IndexWarning]]
        Successful analyzed file snapshots plus deterministic failures and
        warnings.
    """
    parsed_files: list[ParsedFile] = []
    failures: list[IndexFailure] = []
    collected_warnings: list[IndexWarning] = []

    for path in indexed_paths:
        path_obj = Path(path)
        metadata_snapshot = _snapshot_from_metadata(current_metadata[path])
        analyzer = _select_language_analyzer(path_obj, analyzers)
        metadata_snapshot = _snapshot_with_analyzer(metadata_snapshot, analyzer)
        try:
            with warnings.catch_warnings(record=True) as warning_records:
                warnings.simplefilter("always")
                analysis = analyzer.analyze_file(path_obj, root)
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            failures.append(
                IndexFailure(
                    path=path,
                    analyzer_name=str(analyzer.name),
                    error_type=type(exc).__name__,
                    reason=str(exc),
                )
            )
            continue
        for warning_record in warning_records:
            collected_warnings.append(
                IndexWarning(
                    path=path,
                    analyzer_name=str(analyzer.name),
                    warning_type=warning_record.category.__name__,
                    line=warning_record.lineno,
                    reason=str(warning_record.message),
                )
            )
        parsed_files.append((path_obj, metadata_snapshot, analysis))

    return parsed_files, failures, collected_warnings


def _duplicate_analysis_stable_ids(analysis: AnalysisResult) -> list[str]:
    """
    Return duplicate symbol stable IDs emitted by one analysis result.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for one file.

    Returns
    -------
    list[str]
        Sorted duplicate stable IDs, or an empty list when the analysis is
        internally unique.
    """
    stable_ids = [analysis.module.stable_id]
    stable_ids.extend(cls.stable_id for cls in analysis.classes)
    for cls in analysis.classes:
        stable_ids.extend(method.stable_id for method in cls.methods)
    stable_ids.extend(fn.stable_id for fn in analysis.functions)
    stable_ids.extend(decl.stable_id for decl in analysis.declarations)
    counts = Counter(stable_ids)
    return sorted(stable_id for stable_id, count in counts.items() if count > 1)


def _raise_duplicate_stable_ids(path: Path, root: Path, stable_ids: list[str]) -> None:
    """
    Raise one duplicate-stable-id validation error for a file analysis.

    Parameters
    ----------
    path : pathlib.Path
        File path whose analysis emitted duplicate symbol identities.
    root : pathlib.Path
        Repository root used for relative diagnostic labels.
    stable_ids : list[str]
        Duplicate stable IDs detected in the file analysis.

    Returns
    -------
    None
        The function does not return.

    Raises
    ------
    ValueError
        Always raised with a file-scoped duplicate stable-id message.
    """
    try:
        rel_label = path.relative_to(root).as_posix()
    except ValueError:
        rel_label = str(path)
    duplicates_text = ", ".join(stable_ids)
    msg = f"duplicate stable_id(s) in {rel_label}: {duplicates_text}"
    raise ValueError(msg)


def _persist_indexed_file_analyses(
    root: Path,
    *,
    conn: sqlite3.Connection,
    sqlite_backend: IndexBackend,
    parsed_files: list[ParsedFile],
    embedding_backend: EmbeddingBackendSpec,
    previous_embeddings_by_path: dict[str, dict[str, StoredEmbeddingRow]],
) -> tuple[int, int, list[ParsedFile], list[IndexFailure]]:
    """
    Persist analyzed file snapshots through the selected index backend.

    Parameters
    ----------
    root : pathlib.Path
        Repository root being indexed.
    conn : sqlite3.Connection
        Open backend connection reused across writes.
    sqlite_backend : codira.contracts.IndexBackend
        Concrete backend receiving normalized artifacts.
    parsed_files : list[ParsedFile]
        Analyzed file snapshots in deterministic order.
    embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.
    previous_embeddings_by_path : dict[str, dict[str, codira.indexer.StoredEmbeddingRow]]
        Stored symbol embeddings captured before indexed files were replaced.

    Returns
    -------
    tuple[int, int, list[ParsedFile], list[IndexFailure]]
        ``(recomputed, reused, persisted_files, failures)`` for analyzed files.
    """
    embeddings_recomputed = 0
    embeddings_reused = 0
    persisted_files: list[ParsedFile] = []
    failures: list[IndexFailure] = []

    for path, file_metadata_snapshot, analysis in parsed_files:
        try:
            duplicate_stable_ids = _duplicate_analysis_stable_ids(analysis)
            if duplicate_stable_ids:
                _raise_duplicate_stable_ids(
                    file_metadata_snapshot.path,
                    root,
                    duplicate_stable_ids,
                )
            recomputed, reused = sqlite_backend.persist_analysis(
                root,
                file_metadata=file_metadata_snapshot,
                analysis=analysis,
                embedding_backend=embedding_backend,
                previous_embeddings=previous_embeddings_by_path.get(
                    str(file_metadata_snapshot.path),
                    {},
                ),
                conn=conn,
            )
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
            failures.append(
                IndexFailure(
                    path=str(path),
                    analyzer_name=file_metadata_snapshot.analyzer_name,
                    error_type=type(exc).__name__,
                    reason=str(exc),
                )
            )
            continue
        embeddings_recomputed += recomputed
        embeddings_reused += reused
        persisted_files.append((path, file_metadata_snapshot, analysis))

    return (
        embeddings_recomputed,
        embeddings_reused,
        persisted_files,
        failures,
    )


def _collect_project_scan_state(
    root: Path,
    *,
    analyzers: list[LanguageAnalyzer],
) -> ProjectScanState:
    """
    Collect the current tracked file state used by index planning.

    Parameters
    ----------
    root : pathlib.Path
        Repository root being indexed.
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Active analyzers available for file routing.

    Returns
    -------
    ProjectScanState
        Deterministic scan state for the current working tree.
    """
    analyzers_by_path = {
        str(path): _select_language_analyzer(path, analyzers)
        for path in sorted(iter_project_files(root, analyzers=analyzers))
    }
    metadata_by_path = {
        path: file_metadata(Path(path)) for path in sorted(analyzers_by_path)
    }
    return ProjectScanState(
        analyzers_by_path=analyzers_by_path,
        metadata_by_path=metadata_by_path,
        paths=sorted(metadata_by_path),
    )


def _load_existing_index_state(
    root: Path,
    *,
    sqlite_backend: IndexBackend,
    embedding_backend: EmbeddingBackendSpec,
    conn: sqlite3.Connection,
) -> ExistingIndexState:
    """
    Load the persisted state needed for incremental index planning.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be queried.
    sqlite_backend : codira.contracts.IndexBackend
        Concrete backend providing the persisted state.
    embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.
    conn : sqlite3.Connection
        Open backend connection reused across reads.

    Returns
    -------
    ExistingIndexState
        Deterministic persisted state used for reuse decisions.
    """
    file_hashes = sqlite_backend.load_existing_file_hashes(root, conn=conn)
    return ExistingIndexState(
        file_hashes=file_hashes,
        file_ownership=sqlite_backend.load_existing_file_ownership(
            root,
            conn=conn,
        ),
        paths=sorted(file_hashes),
        embedding_backend_matches=sqlite_backend.current_embedding_state_matches(
            root,
            embedding_backend=embedding_backend,
            conn=conn,
        ),
    )


def _plan_index_run(
    *,
    full: bool,
    current_state: ProjectScanState,
    existing_state: ExistingIndexState,
) -> IndexPlan:
    """
    Build the deterministic indexing plan for one repository pass.

    Parameters
    ----------
    full : bool
        Whether a full rebuild was requested.
    current_state : ProjectScanState
        Current tracked-file scan state.
    existing_state : ExistingIndexState
        Persisted index state used for reuse comparisons.

    Returns
    -------
    IndexPlan
        Planned indexed, reused, and deleted paths with stable reasons.
    """
    deleted_paths = [
        path
        for path in existing_state.paths
        if path not in current_state.metadata_by_path
    ]
    reused_paths: list[str] = []
    indexed_paths: list[str] = []
    decisions: list[IndexDecision] = []

    if full:
        indexed_paths = list(current_state.paths)
        for path in current_state.paths:
            decisions.append(IndexDecision(path, "indexed", "full rebuild requested"))
    else:
        for path in current_state.paths:
            existing_hash = existing_state.file_hashes.get(path)
            current_analyzer = current_state.analyzers_by_path[path]
            current_owner = (
                str(current_analyzer.name),
                str(current_analyzer.version),
            )
            current_hash = str(current_state.metadata_by_path[path]["hash"])
            if existing_hash is None:
                indexed_paths.append(path)
                decisions.append(IndexDecision(path, "indexed", "new file"))
            elif existing_hash != current_hash:
                indexed_paths.append(path)
                decisions.append(IndexDecision(path, "indexed", "file content changed"))
            elif existing_state.file_ownership.get(path) != current_owner:
                indexed_paths.append(path)
                decisions.append(
                    IndexDecision(
                        path,
                        "indexed",
                        "analyzer plugin or version changed",
                    )
                )
            elif not existing_state.embedding_backend_matches:
                indexed_paths.append(path)
                decisions.append(
                    IndexDecision(
                        path,
                        "indexed",
                        "embedding backend or version changed",
                    )
                )
            else:
                reused_paths.append(path)
                decisions.append(IndexDecision(path, "reused", "file hash unchanged"))

    for path in deleted_paths:
        decisions.append(IndexDecision(path, "deleted", "file removed"))

    return IndexPlan(
        indexed_paths=indexed_paths,
        reused_paths=reused_paths,
        deleted_paths=deleted_paths,
        decisions=decisions,
    )


def _prepare_index_storage(
    root: Path,
    *,
    full: bool,
    plan: IndexPlan,
    sqlite_backend: IndexBackend,
    conn: sqlite3.Connection,
) -> None:
    """
    Delete persisted rows that the current index plan will replace.

    Parameters
    ----------
    root : pathlib.Path
        Repository root being indexed.
    full : bool
        Whether the current run is a full rebuild.
    plan : IndexPlan
        Deterministic indexing plan for the current run.
    sqlite_backend : codira.contracts.IndexBackend
        Concrete backend receiving deletion requests.
    conn : sqlite3.Connection
        Open backend connection reused across writes.

    Returns
    -------
    None
        Persisted rows are removed in place before fresh analysis is stored.
    """
    if full:
        _clear_index_tables(conn)
        return

    sqlite_backend.delete_paths(
        root,
        paths=sorted(set(plan.indexed_paths) | set(plan.deleted_paths)),
        conn=conn,
    )


def _finalize_index_report(
    *,
    plan: IndexPlan,
    parsed_files: list[ParsedFile],
    failures: list[IndexFailure],
    warnings: list[IndexWarning],
    coverage_issues: list[CoverageIssue],
    embeddings_recomputed: int,
    embeddings_reused: int,
) -> IndexReport:
    """
    Build the deterministic report returned from one index run.

    Parameters
    ----------
    plan : IndexPlan
        Deterministic file-level plan executed during the run.
    parsed_files : list[ParsedFile]
        Successfully analyzed files persisted during the run.
    failures : list[IndexFailure]
        Per-file analysis failures collected during parsing.
    warnings : list[IndexWarning]
        Per-file analysis warnings collected during parsing.
    coverage_issues : list[CoverageIssue]
        Uncovered canonical-directory files detected during the run.
    embeddings_recomputed : int
        Number of embeddings written during persistence.
    embeddings_reused : int
        Number of existing embeddings preserved for reused files.

    Returns
    -------
    IndexReport
        Deterministic report sorted for stable rendering and tests.
    """
    decisions = sorted(
        plan.decisions,
        key=lambda decision: (
            decision.action,
            decision.path,
            decision.reason,
        ),
    )
    sorted_failures = sorted(
        failures,
        key=lambda failure: (
            failure.path,
            failure.analyzer_name,
            failure.error_type,
            failure.reason,
        ),
    )
    sorted_warnings = sorted(
        warnings,
        key=lambda warning: (
            warning.path,
            warning.analyzer_name,
            warning.warning_type,
            -1 if warning.line is None else warning.line,
            warning.reason,
        ),
    )
    return IndexReport(
        indexed=len(parsed_files),
        reused=len(plan.reused_paths),
        deleted=len(plan.deleted_paths),
        failed=len(sorted_failures),
        embeddings_recomputed=embeddings_recomputed,
        embeddings_reused=embeddings_reused,
        decisions=decisions,
        failures=sorted_failures,
        warnings=sorted_warnings,
        coverage_issues=coverage_issues,
    )


def index_repo(
    root: Path,
    *,
    full: bool = False,
) -> IndexReport:
    """
    Incrementally scan repository files and update the SQLite index.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose tracked analyzer-supported files should be
        indexed.
    full : bool, optional
        When ``True``, force a full rebuild instead of reusing unchanged files.

    Returns
    -------
    IndexReport
        Deterministic summary of the indexing run.
    """
    sqlite_backend = active_index_backend()
    analyzers = _active_language_analyzers()
    conn = sqlite_backend.open_connection(root)
    backend = get_embedding_backend()
    coverage_issues = _audit_canonical_directory_coverage(root, analyzers=analyzers)

    try:
        _purge_skipped_docstring_issues(conn)
        sqlite_backend.prune_orphaned_embeddings(root, conn=conn)
        current_state = _collect_project_scan_state(root, analyzers=analyzers)
        existing_state = _load_existing_index_state(
            root,
            sqlite_backend=sqlite_backend,
            embedding_backend=backend,
            conn=conn,
        )
        plan = _plan_index_run(
            full=full,
            current_state=current_state,
            existing_state=existing_state,
        )
        previous_embeddings_by_path = (
            {}
            if full
            else _load_previous_embeddings_by_path(
                conn,
                plan.indexed_paths,
                backend=backend,
            )
        )
        _prepare_index_storage(
            root,
            full=full,
            plan=plan,
            sqlite_backend=sqlite_backend,
            conn=conn,
        )

        unchanged_embeddings_reused = (
            0
            if full
            else sqlite_backend.count_reusable_embeddings(
                root,
                paths=plan.reused_paths,
                conn=conn,
            )
        )

        parsed_files, failures, collected_warnings = _collect_indexed_file_analyses(
            root,
            plan.indexed_paths,
            current_state.metadata_by_path,
            analyzers,
        )
        (
            embeddings_recomputed,
            changed_file_embeddings_reused,
            persisted_files,
            persistence_failures,
        ) = _persist_indexed_file_analyses(
            root,
            conn=conn,
            sqlite_backend=sqlite_backend,
            parsed_files=parsed_files,
            embedding_backend=backend,
            previous_embeddings_by_path=previous_embeddings_by_path,
        )
        failures.extend(persistence_failures)
        embeddings_reused = unchanged_embeddings_reused + changed_file_embeddings_reused

        sqlite_backend.rebuild_derived_indexes(root, conn=conn)
        _persist_runtime_inventory(
            conn,
            backend_name=str(sqlite_backend.name),
            backend_version=str(sqlite_backend.version),
            coverage_complete=not coverage_issues,
            analyzers=analyzers,
        )
        conn.commit()

        return _finalize_index_report(
            plan=plan,
            parsed_files=persisted_files,
            failures=failures,
            warnings=collected_warnings,
            coverage_issues=coverage_issues,
            embeddings_recomputed=embeddings_recomputed,
            embeddings_reused=embeddings_reused,
        )
    finally:
        conn.close()
