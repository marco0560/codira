"""Index repository symbols and docstring diagnostics through a backend.

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

import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.contracts import (
    BackendError,
    BackendPersistAnalysisRequest,
    BackendRuntimeInventoryRequest,
)
from codira.models import (
    AnalysisResult,
    FileMetadataSnapshot,
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
    get_embedding_backend,
)
from codira.sqlite_backend_support import (
    PendingEmbeddingRow,
    StoredEmbeddingRow,
    _flush_embedding_rows,
)

if TYPE_CHECKING:
    from codira_backend_sqlite import SQLiteIndexBackend as SQLiteIndexBackend

    from codira.contracts import IndexBackend, LanguageAnalyzer

ParsedFile = tuple[Path, FileMetadataSnapshot, AnalysisResult]
_IGNORED_COVERAGE_SUFFIXES = frozenset({"<no-suffix>", ".md", ".txt", ".typed"})
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
    if name == "_flush_embedding_rows":
        from codira.sqlite_backend_support import _flush_embedding_rows

        return _flush_embedding_rows
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


@dataclass(frozen=True)
class PersistIndexedFileAnalysesRequest:
    """
    Request parameters for persisting analyzed files.

    Parameters
    ----------
    root : pathlib.Path
        Repository root being indexed.
    conn : object
        Open backend connection reused across writes.
    backend : codira.contracts.IndexBackend
        Concrete backend receiving normalized artifacts.
    parsed_files : list[ParsedFile]
        Analyzed file snapshots in deterministic order.
    embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.
    previous_embeddings_by_path : dict[str, dict[str, codira.indexer.StoredEmbeddingRow]]
        Stored symbol embeddings captured before indexed files were replaced.
    """

    root: Path
    conn: object
    backend: IndexBackend
    parsed_files: list[ParsedFile]
    embedding_backend: EmbeddingBackendSpec
    previous_embeddings_by_path: dict[str, dict[str, StoredEmbeddingRow]]


@dataclass(frozen=True)
class FinalizeIndexReportRequest:
    """
    Request parameters for building an index report.

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
    """

    plan: IndexPlan
    parsed_files: list[ParsedFile]
    failures: list[IndexFailure]
    warnings: list[IndexWarning]
    coverage_issues: list[CoverageIssue]
    embeddings_recomputed: int
    embeddings_reused: int


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
    request: PersistIndexedFileAnalysesRequest,
) -> tuple[int, int, list[ParsedFile], list[IndexFailure]]:
    """
    Persist analyzed file snapshots through the selected index backend.

    Parameters
    ----------
    request : PersistIndexedFileAnalysesRequest
        File persistence request carrying backend and embedding state.

    Returns
    -------
    tuple[int, int, list[ParsedFile], list[IndexFailure]]
        ``(recomputed, reused, persisted_files, failures)`` for analyzed files.
    """
    embeddings_recomputed = 0
    embeddings_reused = 0
    persisted_files: list[ParsedFile] = []
    failures: list[IndexFailure] = []

    for path, file_metadata_snapshot, analysis in request.parsed_files:
        try:
            duplicate_stable_ids = _duplicate_analysis_stable_ids(analysis)
            if duplicate_stable_ids:
                _raise_duplicate_stable_ids(
                    file_metadata_snapshot.path,
                    request.root,
                    duplicate_stable_ids,
                )
            recomputed, reused = request.backend.persist_analysis(
                BackendPersistAnalysisRequest(
                    root=request.root,
                    file_metadata=file_metadata_snapshot,
                    analysis=analysis,
                    embedding_backend=request.embedding_backend,
                    previous_embeddings=request.previous_embeddings_by_path.get(
                        str(file_metadata_snapshot.path),
                        {},
                    ),
                    conn=request.conn,
                )
            )
        except (OSError, BackendError, RuntimeError, ValueError) as exc:
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
    backend: IndexBackend,
    embedding_backend: EmbeddingBackendSpec,
    conn: object,
) -> ExistingIndexState:
    """
    Load the persisted state needed for incremental index planning.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be queried.
    backend : codira.contracts.IndexBackend
        Concrete backend providing the persisted state.
    embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.
    conn : object
        Open backend connection reused across reads.

    Returns
    -------
    ExistingIndexState
        Deterministic persisted state used for reuse decisions.
    """
    file_hashes = backend.load_existing_file_hashes(root, conn=conn)
    return ExistingIndexState(
        file_hashes=file_hashes,
        file_ownership=backend.load_existing_file_ownership(
            root,
            conn=conn,
        ),
        paths=sorted(file_hashes),
        embedding_backend_matches=backend.current_embedding_state_matches(
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
    backend: IndexBackend,
    conn: object,
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
    backend : codira.contracts.IndexBackend
        Concrete backend receiving deletion requests.
    conn : object
        Open backend connection reused across writes.

    Returns
    -------
    None
        Persisted rows are removed in place before fresh analysis is stored.
    """
    if full:
        backend.clear_index(root, conn=conn)
        return

    backend.delete_paths(
        root,
        paths=sorted(set(plan.indexed_paths) | set(plan.deleted_paths)),
        conn=conn,
    )


def _finalize_index_report(request: FinalizeIndexReportRequest) -> IndexReport:
    """
    Build the deterministic report returned from one index run.

    Parameters
    ----------
    request : FinalizeIndexReportRequest
        Index report request carrying plan, diagnostics, and embedding counts.

    Returns
    -------
    IndexReport
        Deterministic report sorted for stable rendering and tests.
    """
    decisions = sorted(
        request.plan.decisions,
        key=lambda decision: (
            decision.action,
            decision.path,
            decision.reason,
        ),
    )
    sorted_failures = sorted(
        request.failures,
        key=lambda failure: (
            failure.path,
            failure.analyzer_name,
            failure.error_type,
            failure.reason,
        ),
    )
    sorted_warnings = sorted(
        request.warnings,
        key=lambda warning: (
            warning.path,
            warning.analyzer_name,
            warning.warning_type,
            -1 if warning.line is None else warning.line,
            warning.reason,
        ),
    )
    return IndexReport(
        indexed=len(request.parsed_files),
        reused=len(request.plan.reused_paths),
        deleted=len(request.plan.deleted_paths),
        failed=len(sorted_failures),
        embeddings_recomputed=request.embeddings_recomputed,
        embeddings_reused=request.embeddings_reused,
        decisions=decisions,
        failures=sorted_failures,
        warnings=sorted_warnings,
        coverage_issues=request.coverage_issues,
    )


def index_repo(
    root: Path,
    *,
    full: bool = False,
) -> IndexReport:
    """
    Incrementally scan repository files and update the backend-neutral index.

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
    index_backend = active_index_backend()
    analyzers = _active_language_analyzers()
    conn = index_backend.open_connection(root)
    backend = get_embedding_backend()
    coverage_issues = _audit_canonical_directory_coverage(root, analyzers=analyzers)

    try:
        index_backend.purge_skipped_docstring_issues(root, conn=conn)
        index_backend.prune_orphaned_embeddings(root, conn=conn)
        current_state = _collect_project_scan_state(root, analyzers=analyzers)
        existing_state = _load_existing_index_state(
            root,
            backend=index_backend,
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
            else cast(
                "dict[str, dict[str, StoredEmbeddingRow]]",
                index_backend.load_previous_embeddings_by_path(
                    root,
                    paths=plan.indexed_paths,
                    embedding_backend=backend,
                    conn=conn,
                ),
            )
        )
        _prepare_index_storage(
            root,
            full=full,
            plan=plan,
            backend=index_backend,
            conn=conn,
        )

        unchanged_embeddings_reused = (
            0
            if full
            else index_backend.count_reusable_embeddings(
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
            PersistIndexedFileAnalysesRequest(
                root=root,
                conn=conn,
                backend=index_backend,
                parsed_files=parsed_files,
                embedding_backend=backend,
                previous_embeddings_by_path=previous_embeddings_by_path,
            )
        )
        failures.extend(persistence_failures)
        embeddings_reused = unchanged_embeddings_reused + changed_file_embeddings_reused

        index_backend.rebuild_derived_indexes(root, conn=conn)
        index_backend.persist_runtime_inventory(
            BackendRuntimeInventoryRequest(
                root=root,
                backend_name=str(index_backend.name),
                backend_version=str(index_backend.version),
                coverage_complete=not coverage_issues,
                analyzers=analyzers,
                conn=conn,
            )
        )
        index_backend.commit(root, conn=conn)

        return _finalize_index_report(
            FinalizeIndexReportRequest(
                plan=plan,
                parsed_files=persisted_files,
                failures=failures,
                warnings=collected_warnings,
                coverage_issues=coverage_issues,
                embeddings_recomputed=embeddings_recomputed,
                embeddings_reused=embeddings_reused,
            )
        )
    finally:
        index_backend.close_connection(conn)
