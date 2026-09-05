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

import json
import os
import warnings
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from fnmatch import fnmatch
from functools import partial
from multiprocessing import get_context
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.config import (
    DEFAULT_EMBEDDING_INDEX_MODE,
    IndexConcurrencyConfig,
    load_effective_config,
    with_effective_config_cache,
)
from codira.contracts import (
    BackendError,
    BackendPersistAnalysisRequest,
    BackendPersistFullIndexFile,
    BackendPersistFullIndexRequest,
    BackendQueryConnection,
    BackendRuntimeInventoryRequest,
    ConcurrencyDeclaringAnalyzer,
    EmbeddingIndexingMetrics,
    EmbeddingIndexingPolicy,
    FullIndexBulkBackend,
    IndexBackend,
    PendingEmbeddingRow,
    StoredEmbeddingRow,
    VectorSetIdentity,
    VectorStore,
)
from codira.git import read_head_commit
from codira.index_generation import IndexGenerationStore, transition_record
from codira.models import (
    AnalysisResult,
    FileMetadataSnapshot,
)
from codira.plugin_config import analyzer_inventory_discovery_json
from codira.registry import (
    active_index_backend,
    active_language_analyzers,
    missing_language_analyzer_hint,
    with_active_plugin_instance_cache,
)
from codira.scanner import (
    analyzer_accepts_path,
    file_metadata,
    iter_coverage_project_files,
    iter_project_files,
)
from codira.semantic.embeddings import (
    EmbeddingBackendSpec,
    get_embedding_backend,
)
from codira.similarity_lifecycle import rebuild_active_similarity_index
from codira.storage import (
    _read_metadata_file,
    _write_metadata_file,
    acquire_index_lock,
    get_metadata_path,
)
from codira.vector_store import active_vector_store_context

if TYPE_CHECKING:
    from codira.contracts import IndexWriteSession, LanguageAnalyzer

ParsedFile = tuple[Path, FileMetadataSnapshot, AnalysisResult]
_IGNORED_COVERAGE_SUFFIXES = frozenset({"<no-suffix>", ".md", ".txt", ".typed"})
_BINARY_SNIFF_BYTES = 8192
_ANALYZER_COVERAGE_ROOTS: dict[str, tuple[str, ...]] = {
    "python": ("src", "tests", "scripts"),
    "bash": ("scripts",),
    "c": ("src", "include", "tests"),
    "cpp": ("src", "include", "tests"),
    "json": ("config", ".github", "scripts"),
    "markdown": ("docs", "examples"),
    "text": ("docs", "examples"),
}
_PROCESS_ANALYSIS_ROOT: Path | None = None
_PROCESS_WORKER_ANALYZERS: list[LanguageAnalyzer] | None = None
__all__ = [
    "PendingEmbeddingRow",
    "StoredEmbeddingRow",
    "index_repo",
    "validate_index_concurrency_preflight",
]


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
class IndexConcurrencyReport:
    """
    Describe the scheduler selected for one index run.

    Parameters
    ----------
    requested_strategy : str
        Strategy requested by configuration or CLI override.
    effective_strategy : str
        Scheduler actually used for analysis.
    workers : int
        Effective worker count, with ``1`` representing serial execution.
    reason : str | None
        Stable fallback explanation, when the requested strategy was not used.
    """

    requested_strategy: str
    effective_strategy: str
    workers: int
    reason: str | None = None


@dataclass(frozen=True)
class _AnalysisTask:
    """Serializable one-file analyzer task."""

    ordinal: int
    path: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class _AnalysisTaskResult:
    """Serializable outcome of one analyzer task."""

    ordinal: int
    parsed_file: ParsedFile | None
    failure: IndexFailure | None
    warnings: tuple[IndexWarning, ...]


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
    embeddings_skipped : int
        Number of candidate embeddings intentionally skipped by indexing
        controls.
    embeddings_pending : int
        Number of candidate embeddings left pending for later computation.
    embedding_index_mode : str
        Effective embedding population mode used for the run.
    embedding_complete : bool
        Whether persisted embedding data is complete for the indexed content.
    publication_ready : bool
        Whether the completed index result is safe to publish to readers.
    analysis_concurrency : IndexConcurrencyReport
        Requested and effective analysis scheduling details.
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
    embeddings_skipped: int = 0
    embeddings_pending: int = 0
    embedding_index_mode: str = DEFAULT_EMBEDDING_INDEX_MODE
    embedding_complete: bool = True
    publication_ready: bool = True
    analysis_concurrency: IndexConcurrencyReport = IndexConcurrencyReport(
        requested_strategy="off",
        effective_strategy="off",
        workers=1,
    )


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
    session : codira.contracts.IndexWriteSession
        Active backend write session reused across indexed files.
    parsed_files : list[ParsedFile]
        Analyzed file snapshots in deterministic order.
    embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.
    embedding_indexing : codira.contracts.EmbeddingIndexingPolicy
        Embedding row eligibility policy for the current run.
    defer_embeddings : bool
        Whether eligible embedding rows should be queued for later computation.
    previous_embeddings_by_path : dict[str, dict[str, codira.indexer.StoredEmbeddingRow]]
        Stored symbol embeddings captured before indexed files were replaced.
    vector_store : codira.contracts.VectorStore
        Active separated vector store used for embedding row persistence.
    vector_set_identity : codira.contracts.VectorSetIdentity
        Active vector-set identity for separated vector-store writes.
    vector_store_config : dict[str, object]
        Vector-store-specific configuration table.
    """

    root: Path
    session: IndexWriteSession
    parsed_files: list[ParsedFile]
    embedding_backend: EmbeddingBackendSpec
    embedding_indexing: EmbeddingIndexingPolicy
    defer_embeddings: bool
    previous_embeddings_by_path: dict[str, dict[str, StoredEmbeddingRow]]
    vector_store: VectorStore
    vector_set_identity: VectorSetIdentity
    vector_store_config: dict[str, object]


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
    embeddings_skipped : int
        Number of candidate embeddings intentionally skipped by indexing
        controls.
    embeddings_pending : int
        Number of candidate embeddings left pending for later computation.
    embedding_index_mode : str
        Effective embedding population mode used for the run.
    embedding_complete : bool
        Whether persisted embedding data is complete for the indexed content.
    publication_ready : bool
        Whether the completed index result is safe to publish to readers.
    """

    plan: IndexPlan
    parsed_files: list[ParsedFile]
    failures: list[IndexFailure]
    warnings: list[IndexWarning]
    coverage_issues: list[CoverageIssue]
    embeddings_recomputed: int
    embeddings_reused: int
    embeddings_skipped: int = 0
    embeddings_pending: int = 0
    embedding_index_mode: str = DEFAULT_EMBEDDING_INDEX_MODE
    embedding_complete: bool = True
    publication_ready: bool = True
    analysis_concurrency: IndexConcurrencyReport = IndexConcurrencyReport(
        requested_strategy="off",
        effective_strategy="off",
        workers=1,
    )


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


def _should_ignore_coverage_gap(
    path: Path,
    *,
    exclude_suffixes: tuple[str, ...],
) -> bool:
    """
    Return whether an uncovered canonical file should be excluded from coverage.

    Parameters
    ----------
    path : pathlib.Path
        Repository file that no analyzer claimed.
    exclude_suffixes : tuple[str, ...]
        User-configured suffixes excluded from coverage diagnostics.

    Returns
    -------
    bool
        ``True`` when the file belongs to a deliberately ignored suffix class
        or is conservatively identified as binary content.
    """
    suffix = path.suffix.lower() or "<no-suffix>"
    if suffix in _IGNORED_COVERAGE_SUFFIXES or suffix in exclude_suffixes:
        return True
    return _is_binary_coverage_candidate(path)


def _audit_canonical_directory_coverage(
    root: Path,
    *,
    analyzers: list[LanguageAnalyzer],
) -> list[CoverageIssue]:
    """
    Audit configured or analyzer-default coverage roots for uncovered files.

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

    coverage_config = load_effective_config(root=root).coverage
    configured_roots = coverage_config.roots
    if configured_roots == ("-",):
        return []
    roots = configured_roots or tuple(
        sorted(
            {
                item
                for analyzer in analyzers
                for item in getattr(
                    analyzer,
                    "default_coverage_roots",
                    _ANALYZER_COVERAGE_ROOTS.get(str(analyzer.name), ()),
                )
            }
        )
    )
    for path in iter_coverage_project_files(root, roots):
        rel_text = path.relative_to(root).as_posix()
        if not any(
            fnmatch(rel_text, pattern)
            or rel_text == pattern
            or rel_text.startswith(f"{pattern.rstrip('/')}/")
            for pattern in roots
        ):
            continue
        if any(analyzer_accepts_path(analyzer, path, root) for analyzer in analyzers):
            continue
        rel_path = path.relative_to(root)
        top_dir = rel_path.parts[0] if rel_path.parts else ""
        if _should_ignore_coverage_gap(
            path,
            exclude_suffixes=coverage_config.exclude_suffixes,
        ):
            continue
        suffix = path.suffix.lower() or "<no-suffix>"
        issues.append(
            CoverageIssue(
                path=str(path),
                directory=top_dir,
                suffix=suffix,
                reason="no registered analyzer accepts this file type/content combination",
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
        analyzers=_active_language_analyzers(root=root),
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


def _active_language_analyzers(*, root: Path | None = None) -> list[LanguageAnalyzer]:
    """
    Return the language analyzers participating in the current indexing run.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in analyzer
        selection.

    Returns
    -------
    list[codira.contracts.LanguageAnalyzer]
        Analyzer instances consulted in deterministic order.
    """
    return active_language_analyzers(root=root)


def _current_analyzer_inventory_rows(
    analyzers: list[LanguageAnalyzer],
) -> list[tuple[str, str, str]]:
    """
    Return the active analyzer inventory in persisted comparison form.

    Parameters
    ----------
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Analyzer instances active for the current run.

    Returns
    -------
    list[tuple[str, str, str]]
        Active analyzer rows as ``(name, version, discovery_globs_json)``
        ordered by analyzer name.
    """
    rows: list[tuple[str, str, str]] = []
    for analyzer in sorted(
        analyzers,
        key=lambda item: str(item.name),
    ):
        rows.append(
            (
                str(analyzer.name),
                str(analyzer.version),
                analyzer_inventory_discovery_json(analyzer),
            )
        )
    return rows


def _select_language_analyzer(
    path: Path,
    analyzers: list[LanguageAnalyzer],
    root: Path | None = None,
) -> LanguageAnalyzer:
    """
    Select the analyzer responsible for one source path.

    Parameters
    ----------
    path : pathlib.Path
        Repository file that must be analyzed.
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Analyzer instances consulted in deterministic order.
    root : pathlib.Path | None, optional
        Repository root used by optional analyzer path filters. When omitted,
        ``path.parent`` is used for compatibility with direct unit tests that
        do not exercise repo-relative filters.

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Analyzer responsible for the file.

    Raises
    ------
    ValueError
        If no registered analyzer accepts the path.
    """
    effective_root = path.parent if root is None else root
    for analyzer in analyzers:
        if analyzer_accepts_path(analyzer, path, effective_root):
            return analyzer

    msg = f"No language analyzer registered for path: {path.as_posix()}"
    hint = missing_language_analyzer_hint(path)
    if hint is not None:
        msg = f"{msg}. {hint}"
    raise ValueError(msg)


def _analyze_index_task(
    task: _AnalysisTask,
    root: Path,
    analyzers: list[LanguageAnalyzer],
) -> _AnalysisTaskResult:
    """
    Analyze one selected file without performing backend work.

    Parameters
    ----------
    task : _AnalysisTask
        Serializable selected-file work item.
    root : pathlib.Path
        Repository root being indexed.
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Configured analyzers used for deterministic path routing.

    Returns
    -------
    _AnalysisTaskResult
        Successful parsed file or one normalized failure plus captured warnings.
    """

    path_obj = Path(task.path)
    metadata_snapshot = _snapshot_from_metadata(task.metadata)
    analyzer = _select_language_analyzer(path_obj, analyzers, root=root)
    metadata_snapshot = _snapshot_with_analyzer(metadata_snapshot, analyzer)
    try:
        with warnings.catch_warnings(record=True) as warning_records:
            warnings.simplefilter("always")
            analysis = analyzer.analyze_file(path_obj, root)
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return _AnalysisTaskResult(
            ordinal=task.ordinal,
            parsed_file=None,
            failure=IndexFailure(
                path=task.path,
                analyzer_name=str(analyzer.name),
                error_type=type(exc).__name__,
                reason=str(exc),
            ),
            warnings=(),
        )
    collected_warnings = tuple(
        IndexWarning(
            path=task.path,
            analyzer_name=str(analyzer.name),
            warning_type=warning_record.category.__name__,
            line=warning_record.lineno,
            reason=str(warning_record.message),
        )
        for warning_record in warning_records
    )
    return _AnalysisTaskResult(
        ordinal=task.ordinal,
        parsed_file=(path_obj, metadata_snapshot, analysis),
        failure=None,
        warnings=collected_warnings,
    )


def _initialize_process_analysis_worker(root: Path) -> None:
    """
    Configure one reusable analyzer set for a process-pool worker.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose configuration is loaded in the worker.

    Returns
    -------
    None
        Worker-global analysis state is initialized for subsequent tasks.
    """

    global _PROCESS_ANALYSIS_ROOT, _PROCESS_WORKER_ANALYZERS
    _PROCESS_ANALYSIS_ROOT = root
    _PROCESS_WORKER_ANALYZERS = active_language_analyzers(root=root)


def _analyze_index_task_in_process_worker(task: _AnalysisTask) -> _AnalysisTaskResult:
    """
    Analyze one task with the process-local configured analyzers.

    Parameters
    ----------
    task : _AnalysisTask
        Serializable selected-file work item.

    Returns
    -------
    _AnalysisTaskResult
        Normalized analyzer outcome returned to the parent process.

    Raises
    ------
    RuntimeError
        If the process-pool initializer did not establish worker state.
    """

    if _PROCESS_ANALYSIS_ROOT is None or _PROCESS_WORKER_ANALYZERS is None:
        msg = "Process analysis worker was not initialized."
        raise RuntimeError(msg)
    return _analyze_index_task(task, _PROCESS_ANALYSIS_ROOT, _PROCESS_WORKER_ANALYZERS)


def _resolve_index_concurrency(
    config: IndexConcurrencyConfig,
    analyzers: list[LanguageAnalyzer],
    selected_file_count: int,
) -> IndexConcurrencyReport:
    """
    Resolve deterministic analyzer scheduling for one plan.

    Parameters
    ----------
    config : codira.config.IndexConcurrencyConfig
        Effective scheduling configuration.
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Active analyzers that must all explicitly support concurrent execution.
    selected_file_count : int
        Number of files selected for analysis.

    Returns
    -------
    IndexConcurrencyReport
        Requested strategy and the safe effective scheduler.

    Raises
    ------
    ValueError
        If an explicit process or thread strategy is unsupported by an active
        analyzer.
    """

    requested = config.strategy
    if requested == "off" or selected_file_count <= 1:
        return IndexConcurrencyReport(requested, "off", 1)
    if requested == "auto" and selected_file_count < config.min_files:
        return IndexConcurrencyReport(requested, "off", 1, "below_min_files")
    candidates = ("process", "thread") if requested == "auto" else (requested,)
    for strategy in candidates:
        incompatible: str | None = None
        for analyzer in analyzers:
            if not isinstance(analyzer, ConcurrencyDeclaringAnalyzer):
                incompatible = str(analyzer.name)
                break
            declaration = analyzer.analyzer_concurrency_declaration()
            valid_identity = (
                declaration.analyzer_name == analyzer.name
                and declaration.analyzer_version == analyzer.version
            )
            supported = (
                declaration.supports_process_workers
                if strategy == "process"
                else (
                    declaration.supports_thread_workers
                    and declaration.reentrant_after_configure
                )
            )
            if not valid_identity or not supported:
                incompatible = str(analyzer.name)
                break
        if incompatible is None:
            automatic = min(4, max(1, os.process_cpu_count() or 1), selected_file_count)
            workers = min(selected_file_count, config.max_workers or automatic)
            return IndexConcurrencyReport(requested, strategy, workers)
        if requested != "auto":
            msg = (
                f"Index concurrency strategy {requested!r} requires all active "
                f"analyzers to declare support; incompatible analyzer: {incompatible}."
            )
            raise ValueError(msg)
    return IndexConcurrencyReport(requested, "off", 1, "incompatible_analyzer")


def validate_index_concurrency_preflight(
    root: Path,
    config: IndexConcurrencyConfig,
) -> None:
    """
    Reject unsupported explicit schedulers before backend initialization.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose active analyzers are inspected.
    config : codira.config.IndexConcurrencyConfig
        Effective or CLI-overridden scheduling configuration.

    Returns
    -------
    None
        Explicit process and thread modes are accepted only when every active
        analyzer declares support.

    Raises
    ------
    ValueError
        If the requested explicit strategy is incompatible with an analyzer.
    """

    if config.strategy in {"process", "thread"}:
        _resolve_index_concurrency(
            config,
            active_language_analyzers(root=root),
            max(2, config.min_files),
        )


def _collect_indexed_file_analyses(
    root: Path,
    indexed_paths: list[str],
    current_metadata: dict[str, dict[str, object]],
    analyzers: list[LanguageAnalyzer],
    concurrency: IndexConcurrencyReport | None = None,
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
    tasks = [
        _AnalysisTask(ordinal, path, current_metadata[path])
        for ordinal, path in enumerate(indexed_paths)
    ]
    effective = concurrency or IndexConcurrencyReport("off", "off", 1)
    if effective.effective_strategy == "off":
        results = [_analyze_index_task(task, root, analyzers) for task in tasks]
    elif effective.effective_strategy == "process":
        with ProcessPoolExecutor(
            max_workers=effective.workers,
            mp_context=get_context("spawn"),
            initializer=_initialize_process_analysis_worker,
            initargs=(root,),
        ) as executor:
            results = list(executor.map(_analyze_index_task_in_process_worker, tasks))
    else:
        analyze_task = partial(_analyze_index_task, root=root, analyzers=analyzers)
        with ThreadPoolExecutor(max_workers=effective.workers) as executor:
            results = list(executor.map(analyze_task, tasks))

    parsed_files: list[ParsedFile] = []
    failures: list[IndexFailure] = []
    collected_warnings: list[IndexWarning] = []
    for result in sorted(results, key=lambda item: item.ordinal):
        if result.parsed_file is not None:
            parsed_files.append(result.parsed_file)
        if result.failure is not None:
            failures.append(result.failure)
        collected_warnings.extend(result.warnings)

    return parsed_files, failures, collected_warnings


def _analysis_status_coverage_issues(
    parsed_files: list[ParsedFile],
) -> list[CoverageIssue]:
    """Return strict-coverage issues for degraded analyzed files.

    Parameters
    ----------
    parsed_files : list[codira.indexer.ParsedFile]
        Successfully returned analyzer results before backend persistence.

    Returns
    -------
    list[codira.indexer.CoverageIssue]
        Deterministic provenance-aware coverage diagnostics.
    """
    issues: list[CoverageIssue] = []
    for path, _metadata, analysis in parsed_files:
        status = analysis.status
        if status is None or status.coverage_state.value == "complete":
            continue
        reason = "; ".join(diagnostic.message for diagnostic in status.diagnostics)
        issues.append(
            CoverageIssue(
                path=str(path),
                directory=path.parts[0] if path.parts else ".",
                suffix=path.suffix,
                reason=reason or "analysis is partial",
            )
        )
    return issues


def persisted_analysis_coverage_issues(
    root: Path,
    backend: IndexBackend,
) -> list[CoverageIssue]:
    """Load persisted partial-analysis coverage diagnostics from one backend.

    Parameters
    ----------
    root : pathlib.Path
        Repository root owning the index.
    backend : codira.contracts.IndexBackend
        Active structural backend containing analysis-status rows.

    Returns
    -------
    list[codira.indexer.CoverageIssue]
        Deterministic degraded-analysis issues persisted by completed indexing.
    """
    conn = cast("BackendQueryConnection", backend.open_connection(root))
    try:
        rows = conn.execute(
            "SELECT path, diagnostics FROM analysis_status "
            "WHERE coverage_state = 'partial' ORDER BY path"
        ).fetchall()
    finally:
        backend.close_connection(conn)
    issues: list[CoverageIssue] = []
    for path_text, diagnostics_text in rows:
        path = Path(str(path_text))
        try:
            directory = path.relative_to(root).parts[0]
        except ValueError:
            directory = path.parts[0] if path.parts else "."
        diagnostics = json.loads(str(diagnostics_text))
        reasons = [item.get("message", "analysis is partial") for item in diagnostics]
        issues.append(
            CoverageIssue(
                path=str(path),
                directory=directory,
                suffix=path.suffix,
                reason="; ".join(str(reason) for reason in reasons),
            )
        )
    return issues


def _duplicate_analysis_stable_ids(analysis: AnalysisResult) -> list[str]:
    """
    Return duplicate artifact stable IDs emitted by one analysis result.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for one file.

    Returns
    -------
    list[str]
        Sorted duplicate stable IDs, or an empty list when the analysis
        artifacts are internally unique.
    """
    stable_ids = [analysis.module.stable_id]
    stable_ids.extend(cls.stable_id for cls in analysis.classes)
    for cls in analysis.classes:
        stable_ids.extend(method.stable_id for method in cls.methods)
    stable_ids.extend(fn.stable_id for fn in analysis.functions)
    stable_ids.extend(overload.stable_id for overload in analysis.iter_overloads())
    stable_ids.extend(decl.stable_id for decl in analysis.declarations)
    stable_ids.extend(artifact.stable_id for artifact in analysis.documentation)
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
) -> tuple[int, int, int, int, list[ParsedFile], list[IndexFailure]]:
    """
    Persist analyzed file snapshots through the selected index backend.

    Parameters
    ----------
    request : PersistIndexedFileAnalysesRequest
        File persistence request carrying backend and embedding state.

    Returns
    -------
    tuple[int, int, int, int, list[ParsedFile], list[IndexFailure]]
        ``(recomputed, reused, skipped, pending, persisted_files, failures)`` for
        analyzed files.
    """
    embeddings_recomputed = 0
    embeddings_reused = 0
    embedding_metrics = EmbeddingIndexingMetrics()
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
            recomputed, reused = request.session.persist_analysis(
                BackendPersistAnalysisRequest(
                    root=request.root,
                    file_metadata=file_metadata_snapshot,
                    analysis=analysis,
                    embedding_backend=request.embedding_backend,
                    embedding_indexing=request.embedding_indexing,
                    embedding_metrics=embedding_metrics,
                    defer_embeddings=request.defer_embeddings,
                    previous_embeddings=request.previous_embeddings_by_path.get(
                        str(file_metadata_snapshot.path),
                        {},
                    ),
                    vector_store=request.vector_store,
                    vector_set_identity=request.vector_set_identity,
                    vector_store_config=request.vector_store_config,
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
        embedding_metrics.skipped,
        embedding_metrics.pending,
        persisted_files,
        failures,
    )


def _persist_full_index_bulk(  # noqa: PLR0913
    *,
    root: Path,
    backend: FullIndexBulkBackend,
    parsed_files: list[ParsedFile],
    embedding_backend: EmbeddingBackendSpec,
    embedding_indexing: EmbeddingIndexingPolicy,
    defer_embeddings: bool,
    vector_store: VectorStore,
    vector_set_identity: VectorSetIdentity,
    vector_store_config: dict[str, object],
    coverage_complete: bool,
    analyzers: list[LanguageAnalyzer],
) -> tuple[int, int, int, int, list[ParsedFile], list[IndexFailure]]:
    """
    Persist a full index through an optional backend-native bulk contract.

    Parameters
    ----------
    root : pathlib.Path
        Repository root being indexed.
    backend : codira.contracts.FullIndexBulkBackend
        Backend implementing the optional full-index bulk contract.
    parsed_files : list[ParsedFile]
        Analyzed file snapshots in deterministic order.
    embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.
    embedding_indexing : codira.contracts.EmbeddingIndexingPolicy
        Embedding row eligibility policy for the current run.
    defer_embeddings : bool
        Whether eligible embedding rows should be queued for later computation.
    vector_store : codira.contracts.VectorStore
        Active separated vector store used for embedding row persistence.
    vector_set_identity : codira.contracts.VectorSetIdentity
        Active vector-set identity for separated vector-store writes.
    vector_store_config : dict[str, object]
        Vector-store-specific configuration table.
    coverage_complete : bool
        Whether canonical-directory coverage had no gaps.
    analyzers : list[codira.contracts.LanguageAnalyzer]
        Active analyzers for the current run.

    Returns
    -------
    tuple[int, int, int, int, list[ParsedFile], list[IndexFailure]]
        ``(recomputed, reused, skipped, pending, persisted_files, failures)`` for
        analyzed files.
    """
    persisted_files: list[ParsedFile] = []
    failures: list[IndexFailure] = []
    request_files: list[BackendPersistFullIndexFile] = []

    for path, file_metadata_snapshot, analysis in parsed_files:
        duplicate_stable_ids = _duplicate_analysis_stable_ids(analysis)
        if duplicate_stable_ids:
            try:
                _raise_duplicate_stable_ids(
                    file_metadata_snapshot.path,
                    root,
                    duplicate_stable_ids,
                )
            except ValueError as exc:
                failures.append(
                    IndexFailure(
                        path=str(path),
                        analyzer_name=file_metadata_snapshot.analyzer_name,
                        error_type=type(exc).__name__,
                        reason=str(exc),
                    )
                )
                continue
        persisted_files.append((path, file_metadata_snapshot, analysis))
        request_files.append(
            BackendPersistFullIndexFile(
                path=path,
                file_metadata=file_metadata_snapshot,
                analysis=analysis,
            )
        )

    try:
        result = backend.persist_full_index(
            BackendPersistFullIndexRequest(
                root=root,
                files=request_files,
                embedding_backend=embedding_backend,
                embedding_indexing=embedding_indexing,
                defer_embeddings=defer_embeddings,
                vector_store=vector_store,
                vector_set_identity=vector_set_identity,
                vector_store_config=vector_store_config,
                coverage_complete=coverage_complete,
                analyzers=analyzers,
            )
        )
    except (OSError, BackendError, RuntimeError, ValueError) as exc:
        failures.extend(
            IndexFailure(
                path=str(path),
                analyzer_name=file_metadata_snapshot.analyzer_name,
                error_type=type(exc).__name__,
                reason=str(exc),
            )
            for path, file_metadata_snapshot, _analysis in persisted_files
        )
        return (0, 0, 0, 0, [], failures)

    return (
        result.embeddings_recomputed,
        result.embeddings_reused,
        result.embeddings_skipped,
        result.embeddings_pending,
        persisted_files,
        failures,
    )


def _embedding_indexing_policy(root: Path) -> EmbeddingIndexingPolicy:
    """
    Build the backend-neutral embedding indexing policy for one root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose effective config should be resolved.

    Returns
    -------
    EmbeddingIndexingPolicy
        Policy derived from ``embeddings.indexing`` config values.
    """

    indexing = load_effective_config(root=root).embeddings.indexing
    return EmbeddingIndexingPolicy(
        object_types=frozenset(indexing.object_types),
        max_text_chars=indexing.max_text_chars,
        include_paths=indexing.include_paths,
        exclude_paths=indexing.exclude_paths,
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
    analyzers_by_path: dict[str, LanguageAnalyzer] = {}
    metadata_by_path: dict[str, dict[str, object]] = {}

    for path in sorted(iter_project_files(root, analyzers=analyzers)):
        path_str = str(path)
        try:
            metadata_by_path[path_str] = file_metadata(path)
        except FileNotFoundError:
            # Git-backed discovery can briefly enumerate a tracked path that
            # has already been removed from the working tree but not staged yet.
            continue
        analyzers_by_path[path_str] = _select_language_analyzer(
            path,
            analyzers,
            root=root,
        )

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
    conn: object | None = None,
) -> ExistingIndexState:
    """
    Load the persisted state needed for incremental index planning.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose persisted backend state should be loaded.
    backend : object
        Active backend exposing the incremental-planning read surface.
    embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.
    conn : object | None, optional
        Existing backend connection to reuse for read-side planning.

    Returns
    -------
    ExistingIndexState
        Deterministic persisted state used for reuse decisions.
    """
    file_hashes = backend.load_existing_file_hashes(root, conn=conn)
    return ExistingIndexState(
        file_hashes=file_hashes,
        file_ownership=backend.load_existing_file_ownership(root, conn=conn),
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
    *,
    full: bool,
    plan: IndexPlan,
    session: IndexWriteSession,
) -> None:
    """
    Delete persisted rows that the current index plan will replace.

    Parameters
    ----------
    full : bool
        Whether the current run is a full rebuild.
    plan : IndexPlan
        Deterministic indexing plan for the current run.
    session : codira.contracts.IndexWriteSession
        Active backend write session receiving deletion requests.

    Returns
    -------
    None
        Persisted rows are removed in place before fresh analysis is stored.
    """
    session.prepare(
        full=full,
        indexed_paths=plan.indexed_paths,
        deleted_paths=plan.deleted_paths,
    )


def _index_run_mutated_graph_inputs(
    *,
    full: bool,
    plan: IndexPlan,
    existing_state: ExistingIndexState,
    persisted_files: list[ParsedFile],
) -> bool:
    """
    Return whether the completed run changed graph-derived source rows.

    Parameters
    ----------
    full : bool
        Whether the current run cleared all indexed storage.
    plan : IndexPlan
        Deterministic indexing plan for the current run.
    existing_state : ExistingIndexState
        Persisted state observed before the current run.
    persisted_files : list[ParsedFile]
        Successfully persisted parsed-file rows.

    Returns
    -------
    bool
        ``True`` when derived graph indexes may need rebuilding.
    """
    if full or plan.deleted_paths or persisted_files:
        return True

    existing_paths = set(existing_state.paths)
    return any(path in existing_paths for path in plan.indexed_paths)


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
        embeddings_skipped=request.embeddings_skipped,
        embeddings_pending=request.embeddings_pending,
        embedding_index_mode=request.embedding_index_mode,
        embedding_complete=request.embedding_complete,
        publication_ready=request.publication_ready,
        analysis_concurrency=request.analysis_concurrency,
    )


@with_effective_config_cache
@with_active_plugin_instance_cache
def index_repo(
    root: Path,
    *,
    full: bool = False,
    embedding_index_mode: str | None = None,
    analysis_concurrency: IndexConcurrencyConfig | None = None,
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
    embedding_index_mode : str | None, optional
        Embedding population mode override supplied by the CLI. ``None`` uses
        the effective configuration.
    analysis_concurrency : codira.config.IndexConcurrencyConfig | None, optional
        Scheduler override supplied by the CLI. ``None`` uses effective
        configuration.

    Returns
    -------
    IndexReport
        Deterministic summary of the indexing run.

    Raises
    ------
    BackendError
        If the active backend rejects one repository-scoped mutation outside
        per-file persistence failure handling.
    OSError
        If repository scanning or backend-owned file mutation fails.
    RuntimeError
        If one backend-owned runtime operation cannot complete.
    ValueError
        If validated indexing inputs are semantically inconsistent.
    """
    with acquire_index_lock(root):
        store = IndexGenerationStore(root)
        previous = store.read()
        generation = (previous.generation if previous else 0) + 1
        last_successful = previous.last_successful_generation if previous else 0
        store.write(
            transition_record(
                generation=generation,
                state="updating",
                last_successful_generation=last_successful,
            )
        )
        report = _index_repo_unlocked(
            root,
            full=full,
            embedding_index_mode=embedding_index_mode,
            analysis_concurrency=analysis_concurrency,
        )
        if (
            report.publication_ready
            and report.embedding_complete
            and (report.indexed > 0 or report.deleted > 0)
        ):
            rebuild_active_similarity_index(root)
        if not report.publication_ready:
            store.write(
                transition_record(
                    generation=generation,
                    state="failed",
                    last_successful_generation=last_successful,
                )
            )
            return report
        backend = active_index_backend(root=root)
        analyzers = _active_language_analyzers(root=root)
        metadata = _read_metadata_file(get_metadata_path(root))
        metadata.update(
            {
                "schema_version": str(backend.version),
                "backend_name": str(backend.name),
                "backend_version": str(backend.version),
                "analyzer_inventory": json.dumps(
                    _current_analyzer_inventory_rows(analyzers)
                ),
                "indexed_file_count": str(report.indexed + report.reused),
            }
        )
        commit = read_head_commit(root)
        if commit:
            metadata["commit"] = commit
        _write_metadata_file(get_metadata_path(root), metadata)
        if (
            previous is not None
            and previous.state == "ready"
            and report.indexed == 0
            and report.deleted == 0
            and report.failed == 0
        ):
            store.write(previous)
            return report
        store.write(
            transition_record(
                generation=generation,
                state="ready",
                last_successful_generation=generation,
                git_commit=read_head_commit(root),
                backend_name=str(backend.name),
                backend_version=str(backend.version),
                analyzer_inventory=[
                    {"name": str(analyzer.name), "version": str(analyzer.version)}
                    for analyzer in analyzers
                ],
                indexed_file_count=report.indexed + report.reused,
            )
        )
        return report


def _index_repo_unlocked(
    root: Path,
    *,
    full: bool = False,
    embedding_index_mode: str | None = None,
    analysis_concurrency: IndexConcurrencyConfig | None = None,
) -> IndexReport:
    """
    Incrementally update the index while the caller owns its mutation lock.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose tracked analyzer-supported files should be
        indexed.
    full : bool, optional
        When ``True``, force a full rebuild instead of reusing unchanged files.
    embedding_index_mode : str | None, optional
        Embedding population mode override supplied by the public coordinator.
    analysis_concurrency : codira.config.IndexConcurrencyConfig | None, optional
        Scheduler override supplied by the public coordinator.

    Returns
    -------
    IndexReport
        Deterministic summary of the indexing run.

    Notes
    -----
    ``index_repo()`` is the public mutation coordinator. This implementation
    assumes its caller already holds ``acquire_index_lock(root)``.
    """
    index_backend = active_index_backend(root=root)
    vector_store_context = active_vector_store_context(root)
    effective_config = load_effective_config(root=root)
    analyzers = _active_language_analyzers(root=root)
    backend = get_embedding_backend(root=root)
    embedding_indexing = _embedding_indexing_policy(root)
    effective_embedding_index_mode = (
        effective_config.embeddings.indexing.mode
        if embedding_index_mode is None
        else embedding_index_mode
    )
    concurrency_config = (
        effective_config.index if analysis_concurrency is None else analysis_concurrency
    )
    coverage_issues = _audit_canonical_directory_coverage(root, analyzers=analyzers)
    current_state = _collect_project_scan_state(root, analyzers=analyzers)
    planning_conn = index_backend.open_connection(root)
    try:
        existing_state = _load_existing_index_state(
            root,
            backend=index_backend,
            embedding_backend=backend,
            conn=planning_conn,
        )
        plan = _plan_index_run(
            full=full,
            current_state=current_state,
            existing_state=existing_state,
        )
        current_runtime_inventory = (
            str(index_backend.name),
            str(index_backend.version),
            int(not coverage_issues),
        )
        runtime_inventory_matches = (
            index_backend.load_runtime_inventory(root, conn=planning_conn)
            == current_runtime_inventory
        )
        analyzer_inventory_matches = index_backend.load_analyzer_inventory(
            root,
            conn=planning_conn,
        ) == _current_analyzer_inventory_rows(analyzers)
        needs_maintenance = getattr(
            index_backend,
            "needs_maintenance",
            lambda _root, *, conn=None: True,
        )
        backend_needs_maintenance = bool(needs_maintenance(root, conn=planning_conn))
        unchanged_embeddings_reused = (
            0
            if full
            else index_backend.count_reusable_embeddings(
                root,
                paths=plan.reused_paths,
                conn=planning_conn,
            )
        )
    finally:
        index_backend.close_connection(planning_conn)
    resolved_analysis_concurrency = _resolve_index_concurrency(
        concurrency_config,
        analyzers,
        len(plan.indexed_paths),
    )
    if (
        not plan.indexed_paths
        and not plan.deleted_paths
        and runtime_inventory_matches
        and analyzer_inventory_matches
        and not backend_needs_maintenance
    ):
        return _finalize_index_report(
            FinalizeIndexReportRequest(
                plan=plan,
                parsed_files=[],
                failures=[],
                warnings=[],
                coverage_issues=coverage_issues,
                embeddings_recomputed=0,
                embeddings_reused=unchanged_embeddings_reused,
                embedding_index_mode=effective_embedding_index_mode,
                analysis_concurrency=resolved_analysis_concurrency,
            )
        )

    parsed_files, failures, collected_warnings = _collect_indexed_file_analyses(
        root,
        plan.indexed_paths,
        current_state.metadata_by_path,
        analyzers,
        resolved_analysis_concurrency,
    )
    coverage_issues.extend(_analysis_status_coverage_issues(parsed_files))
    if full and isinstance(index_backend, FullIndexBulkBackend):
        (
            embeddings_recomputed,
            changed_file_embeddings_reused,
            changed_file_embeddings_skipped,
            changed_file_embeddings_pending,
            persisted_files,
            persistence_failures,
        ) = _persist_full_index_bulk(
            root=root,
            backend=index_backend,
            parsed_files=parsed_files,
            embedding_backend=backend,
            embedding_indexing=embedding_indexing,
            defer_embeddings=effective_embedding_index_mode == "deferred",
            vector_store=vector_store_context.store,
            vector_set_identity=vector_store_context.identity,
            vector_store_config=vector_store_context.config,
            coverage_complete=not coverage_issues,
            analyzers=analyzers,
        )
        failures.extend(persistence_failures)
        embeddings_reused = unchanged_embeddings_reused + changed_file_embeddings_reused
        return _finalize_index_report(
            FinalizeIndexReportRequest(
                plan=plan,
                parsed_files=persisted_files,
                failures=failures,
                warnings=collected_warnings,
                coverage_issues=coverage_issues,
                embeddings_recomputed=embeddings_recomputed,
                embeddings_reused=embeddings_reused,
                embeddings_skipped=changed_file_embeddings_skipped,
                embeddings_pending=changed_file_embeddings_pending,
                embedding_index_mode=effective_embedding_index_mode,
                embedding_complete=changed_file_embeddings_pending == 0,
                publication_ready=not persistence_failures,
                analysis_concurrency=resolved_analysis_concurrency,
            )
        )

    session = index_backend.begin_index_session(root)
    try:
        session.purge_skipped_docstring_issues()
        session.prune_orphaned_embeddings()
        previous_embeddings_by_path = (
            {}
            if full
            else session.load_previous_embeddings_by_path(
                paths=plan.indexed_paths,
                embedding_backend=backend,
            )
        )
        _prepare_index_storage(
            full=full,
            plan=plan,
            session=session,
        )

        (
            embeddings_recomputed,
            changed_file_embeddings_reused,
            changed_file_embeddings_skipped,
            changed_file_embeddings_pending,
            persisted_files,
            persistence_failures,
        ) = _persist_indexed_file_analyses(
            PersistIndexedFileAnalysesRequest(
                root=root,
                session=session,
                parsed_files=parsed_files,
                embedding_backend=backend,
                embedding_indexing=embedding_indexing,
                defer_embeddings=effective_embedding_index_mode == "deferred",
                previous_embeddings_by_path=previous_embeddings_by_path,
                vector_store=vector_store_context.store,
                vector_set_identity=vector_store_context.identity,
                vector_store_config=vector_store_context.config,
            )
        )
        failures.extend(persistence_failures)
        embeddings_reused = unchanged_embeddings_reused + changed_file_embeddings_reused

        if _index_run_mutated_graph_inputs(
            full=full,
            plan=plan,
            existing_state=existing_state,
            persisted_files=persisted_files,
        ):
            session.rebuild_derived_indexes()
        session.persist_runtime_inventory(
            BackendRuntimeInventoryRequest(
                root=root,
                backend_name=str(index_backend.name),
                backend_version=str(index_backend.version),
                coverage_complete=not coverage_issues,
                analyzers=analyzers,
            )
        )
        session.commit()

        return _finalize_index_report(
            FinalizeIndexReportRequest(
                plan=plan,
                parsed_files=persisted_files,
                failures=failures,
                warnings=collected_warnings,
                coverage_issues=coverage_issues,
                embeddings_recomputed=embeddings_recomputed,
                embeddings_reused=embeddings_reused,
                embeddings_skipped=changed_file_embeddings_skipped,
                embeddings_pending=changed_file_embeddings_pending,
                embedding_index_mode=effective_embedding_index_mode,
                embedding_complete=changed_file_embeddings_pending == 0,
                analysis_concurrency=resolved_analysis_concurrency,
            )
        )
    except BaseException:
        session.abort()
        raise
    finally:
        session.close()
