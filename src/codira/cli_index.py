"""Index execution, coverage reporting, and index-freshness operations."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.cli_render import _emit_json, _query_payload
from codira.cli_requests import (
    IndexCommandRequest,
    IndexPayloadRequest,
    IndexRebuildRequest,
)
from codira.config import (
    IndexConcurrencyConfig,
    load_effective_config,
)
from codira.contracts import (
    BackendError,
)
from codira.git import read_head_commit
from codira.indexer import (
    CoverageIssue,
    IndexFailure,
    IndexReport,
    IndexWarning,
    audit_repo_coverage,
    index_repo,
    persisted_analysis_coverage_issues,
    validate_index_concurrency_preflight,
)
from codira.plugin_config import analyzer_inventory_discovery_json
from codira.prefix import normalize_prefix
from codira.registry import (
    active_index_backend,
    active_language_analyzers,
)
from codira.repository_scope import is_repository_scope_excluded
from codira.scanner import analyzer_accepts_path, file_metadata, iter_project_files
from codira.semantic.embeddings import (
    get_embedding_backend,
)
from codira.similarity_lifecycle import (
    rebuild_active_similarity_index,
)
from codira.storage import (
    _read_metadata_file,
    _write_metadata_file,
    acquire_index_lock,
    get_metadata_path,
)
from codira.vector_store import (
    active_vector_store_context,
)
from codira.version import package_version


def _current_analyzer_inventory(
    *, root: Path | None = None
) -> list[tuple[str, str, str]]:
    """Return active analyzer rows in persisted comparison form.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose effective configuration selects analyzers.

    Returns
    -------
    list[tuple[str, str, str]]
        Deterministic ``(name, version, discovery_globs_json)`` rows.
    """
    return [
        (
            str(analyzer.name),
            str(analyzer.version),
            analyzer_inventory_discovery_json(analyzer),
        )
        for analyzer in sorted(
            active_language_analyzers(root=root), key=lambda item: str(item.name)
        )
    ]


if TYPE_CHECKING:
    import argparse
    from typing import Protocol

    import codira.indexer as indexer_types

    class _IndexedFileHashLoader(Protocol):
        """
        Backend read surface used by CLI freshness fallback checks.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Protocol definitions are only evaluated by type checkers.
        """

        def load_existing_file_hashes(
            self,
            root: Path,
            *,
            conn: object | None = None,
        ) -> dict[str, str]: ...


GIT_EXE = shutil.which("git") or "git"
__version__ = package_version()

QUERY_JSON_SCHEMA_VERSION = "2.0"
INDEX_METADATA_ANALYZER_INVENTORY = "analyzer_inventory"
INDEX_METADATA_BACKEND_NAME = "backend_name"
INDEX_METADATA_BACKEND_VERSION = "backend_version"
INDEX_METADATA_FILE_COUNT = "indexed_file_count"
_REPO_PATH_COMMANDS = frozenset(
    {
        "index",
        "cov",
        "sym",
        "symlist",
        "arch",
        "emb",
        "docs",
        "calls",
        "refs",
        "audit",
        "ctx",
        "config",
        "daemon",
        "query-daemon",
        "setup",
    }
)
_CONFIG_INSPECTION_ACTIONS = frozenset({"dump", "explain", "validate"})


def _run_index(request: IndexCommandRequest) -> int:  # noqa: C901, PLR0912
    """
    Build or refresh the repository index.

    Parameters
    ----------
    request : IndexCommandRequest
        Parsed command options for the indexing run.

    Returns
    -------
    int
        Process exit status for a successful indexing run.
    """
    root = request.root
    full = request.full
    explain = request.explain
    require_full_coverage = request.require_full_coverage
    defer_embeddings = request.defer_embeddings
    embeddings_only = request.embeddings_only
    concurrency = request.concurrency
    jobs = request.jobs
    as_json = request.as_json
    if defer_embeddings and embeddings_only:
        msg = "--defer-embeddings and --embeddings-only are mutually exclusive."
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="invalid_arguments",
                        report=None,
                        coverage_issues=[],
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            print(f"[codira] ValueError: {msg}", file=sys.stderr)
        return 2

    config = load_effective_config(root=root)
    if jobs is not None and jobs < 1:
        msg = "--jobs must be a positive integer."
        print(f"[codira] ValueError: {msg}", file=sys.stderr)
        return 2
    if concurrency == "off" and jobs is not None:
        msg = "--jobs cannot be combined with --concurrency off."
        print(f"[codira] ValueError: {msg}", file=sys.stderr)
        return 2
    analysis_concurrency = (
        None
        if concurrency is None and jobs is None
        else IndexConcurrencyConfig(
            strategy="auto"
            if jobs is not None and concurrency is None
            else (concurrency or config.index.strategy),
            max_workers=config.index.max_workers if jobs is None else jobs,
            min_files=config.index.min_files,
        )
    )
    effective_analysis_concurrency = analysis_concurrency or config.index
    try:
        validate_index_concurrency_preflight(root, effective_analysis_concurrency)
    except ValueError as exc:
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="invalid_concurrency",
                        report=None,
                        coverage_issues=[],
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            print(f"[codira] ValueError: {exc}", file=sys.stderr)
        return 2
    if not config.embeddings.enabled and (defer_embeddings or embeddings_only):
        msg = "Embedding index mode flags require embeddings.enabled = true."
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="embeddings_disabled",
                        report=None,
                        coverage_issues=[],
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            print(f"[codira] ConfigError: {msg}", file=sys.stderr)
        return 2

    effective_embedding_index_mode = (
        "deferred" if defer_embeddings else config.embeddings.indexing.mode
    )
    if embeddings_only:
        vector_store_context = active_vector_store_context(root)
        active_backend = active_index_backend(root=root)
        with acquire_index_lock(root):
            active_backend.initialize(root)
            recomputed, reused = active_backend.process_pending_embeddings(
                root,
                embedding_backend=get_embedding_backend(root=root),
                vector_store=vector_store_context.store,
                vector_set_identity=vector_store_context.identity,
                vector_store_config=vector_store_context.config,
            )
            vector_store_context.store.clear_pending_vectors(
                root,
                vector_store_context.identity,
                vector_store_context.config,
            )
            if recomputed:
                rebuild_active_similarity_index(root)
        report = IndexReport(
            indexed=0,
            reused=0,
            deleted=0,
            failed=0,
            embeddings_recomputed=recomputed,
            embeddings_reused=reused,
            decisions=[],
            failures=[],
            warnings=[],
            coverage_issues=[],
            embeddings_pending=0,
            embedding_index_mode=effective_embedding_index_mode,
            embedding_complete=True,
        )
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="ok",
                        report=report,
                        coverage_issues=[],
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            _render_index_report(root, report)
        return 0

    coverage_issues = audit_repo_coverage(root)
    if require_full_coverage and coverage_issues:
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="coverage_incomplete",
                        report=None,
                        coverage_issues=coverage_issues,
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            _render_required_coverage_failure(root, coverage_issues)
        return 2

    with acquire_index_lock(root):
        active_index_backend(root=root).initialize(root)
        if analysis_concurrency is None:
            report = index_repo(
                root,
                full=full,
                embedding_index_mode=effective_embedding_index_mode,
            )
        else:
            report = index_repo(
                root,
                full=full,
                embedding_index_mode=effective_embedding_index_mode,
                analysis_concurrency=analysis_concurrency,
            )
    if as_json:
        _emit_json(
            _index_payload(
                IndexPayloadRequest(
                    full=full,
                    explain=explain,
                    require_full_coverage=require_full_coverage,
                    status="ok",
                    report=report,
                    coverage_issues=report.coverage_issues,
                    defer_embeddings=defer_embeddings,
                    embeddings_only=embeddings_only,
                )
            )
        )
        return 2 if require_full_coverage and report.coverage_issues else 0
    _render_index_report(root, report)
    if require_full_coverage and report.coverage_issues:
        return 2
    if explain:
        for decision in report.decisions:
            rel_path = Path(decision.path)
            try:
                rel_label = rel_path.relative_to(root).as_posix()
            except ValueError:
                rel_label = decision.path
            print(f"{decision.action}: {rel_label} ({decision.reason})")
    return 0


def _index_payload(
    request: IndexPayloadRequest,
) -> dict[str, object]:
    """
    Build the structured JSON payload for one index command run.

    Parameters
    ----------
    request : IndexPayloadRequest
        Structured index payload request.

    Returns
    -------
    dict[str, object]
        JSON-serializable payload for ``codira index --json``.
    """
    report = request.report
    return {
        "schema_version": QUERY_JSON_SCHEMA_VERSION,
        "command": "index",
        "status": request.status,
        "query": {
            "full": request.full,
            "explain": request.explain,
            "require_full_coverage": request.require_full_coverage,
            "defer_embeddings": request.defer_embeddings,
            "embeddings_only": request.embeddings_only,
        },
        "results": [],
        "summary": {
            "indexed": 0 if report is None else report.indexed,
            "reused": 0 if report is None else report.reused,
            "deleted": 0 if report is None else report.deleted,
            "failed": 0 if report is None else report.failed,
            "embeddings_recomputed": (
                0 if report is None else report.embeddings_recomputed
            ),
            "embeddings_reused": 0 if report is None else report.embeddings_reused,
            "embeddings_skipped": 0 if report is None else report.embeddings_skipped,
            "embeddings_pending": 0 if report is None else report.embeddings_pending,
            "embedding_index_mode": (
                "unknown" if report is None else report.embedding_index_mode
            ),
            "embedding_complete": False
            if report is None
            else report.embedding_complete,
            "analysis_concurrency": {
                "requested_strategy": "unknown"
                if report is None
                else report.analysis_concurrency.requested_strategy,
                "effective_strategy": "unknown"
                if report is None
                else report.analysis_concurrency.effective_strategy,
                "workers": 0 if report is None else report.analysis_concurrency.workers,
                "reason": None
                if report is None
                else report.analysis_concurrency.reason,
            },
        },
        "coverage_issues": [
            {
                "path": issue.path,
                "directory": issue.directory,
                "suffix": issue.suffix,
                "reason": issue.reason,
            }
            for issue in request.coverage_issues
        ],
        "warnings": [] if report is None else _index_warning_payload(report.warnings),
        "failures": [] if report is None else _index_failure_payload(report.failures),
        "decisions": (
            []
            if report is None or not request.explain
            else _index_decision_payload(report.decisions)
        ),
    }


def _index_decision_payload(
    decisions: list[indexer_types.IndexDecision],
) -> list[dict[str, object]]:
    """
    Serialize per-file index decisions for JSON output.

    Parameters
    ----------
    decisions : list[codira.indexer.IndexDecision]
        Deterministic per-file decisions emitted by the indexer.

    Returns
    -------
    list[dict[str, object]]
        JSON rows describing indexed, reused, and deleted files.
    """
    return [
        {
            "path": decision.path,
            "action": decision.action,
            "reason": decision.reason,
        }
        for decision in decisions
    ]


def _index_warning_payload(
    warnings: list[IndexWarning],
) -> list[dict[str, object]]:
    """
    Serialize index warning diagnostics for JSON output.

    Parameters
    ----------
    warnings : list[codira.indexer.IndexWarning]
        Warning diagnostics recorded during indexing.

    Returns
    -------
    list[dict[str, object]]
        JSON rows for warning diagnostics.
    """
    return [
        {
            "path": warning.path,
            "analyzer_name": warning.analyzer_name,
            "warning_type": warning.warning_type,
            "line": warning.line,
            "reason": warning.reason,
        }
        for warning in warnings
    ]


def _index_failure_payload(
    failures: list[IndexFailure],
) -> list[dict[str, object]]:
    """
    Serialize index failure diagnostics for JSON output.

    Parameters
    ----------
    failures : list[codira.indexer.IndexFailure]
        Failure diagnostics recorded during indexing.

    Returns
    -------
    list[dict[str, object]]
        JSON rows for failure diagnostics.
    """
    return [
        {
            "path": failure.path,
            "analyzer_name": failure.analyzer_name,
            "error_type": failure.error_type,
            "reason": failure.reason,
        }
        for failure in failures
    ]


def _render_required_coverage_failure(
    root: Path,
    coverage_issues: list[CoverageIssue],
) -> bool:
    """
    Render strict coverage failure output when indexing must stop early.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative path labels.
    coverage_issues : list[codira.indexer.CoverageIssue]
        Coverage-issue rows discovered before indexing.

    Returns
    -------
    bool
        ``True`` when strict coverage mode should abort indexing.
    """
    if not coverage_issues:
        return False
    print(
        "[codira] Coverage incomplete — install the missing analyzer "
        "plugins or rerun without --require-full-coverage",
        file=sys.stderr,
    )
    _render_coverage_issues(root, coverage_issues)
    return True


def _write_index_head_metadata(
    root: Path,
    *,
    indexed_file_count: int | None = None,
) -> None:
    """
    Persist index metadata derived from the current repository head.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose metadata should be updated.
    indexed_file_count : int | None, optional
        Number of indexed file rows known after a successful index run.

    Returns
    -------
    None
        Index metadata is updated in place.
    """
    metadata = _read_index_metadata(root)
    metadata.update(_build_index_metadata(root, indexed_file_count=indexed_file_count))
    _write_index_metadata(root, metadata)


def _relative_report_path(root: Path, path: str) -> str:
    """
    Convert one absolute diagnostic path into a repo-relative label.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for path relativization.
    path : str
        Absolute or already-relative path to render.

    Returns
    -------
    str
        Repo-relative diagnostic label when possible.
    """
    path_obj = Path(path)
    try:
        return path_obj.relative_to(root).as_posix()
    except ValueError:
        return path


def _render_index_report(root: Path, report: IndexReport) -> None:
    """
    Render the deterministic summary and diagnostics for one index run.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative diagnostic labels.
    report : codira.indexer.IndexReport
        Completed index-run report to render.

    Returns
    -------
    None
        Summary lines and diagnostics are printed to standard output.
    """
    print(f"Indexed: {report.indexed}")
    print(f"Reused: {report.reused}")
    print(f"Deleted: {report.deleted}")
    print(f"Failed: {report.failed}")
    print(f"Embeddings recomputed: {report.embeddings_recomputed}")
    print(f"Embeddings reused: {report.embeddings_reused}")
    print(f"Embeddings skipped: {report.embeddings_skipped}")
    print(f"Embeddings pending: {report.embeddings_pending}")
    print(f"Embedding index mode: {report.embedding_index_mode}")
    print(f"Embedding complete: {str(report.embedding_complete).lower()}")
    concurrency = report.analysis_concurrency
    suffix = "" if concurrency.reason is None else f" ({concurrency.reason})"
    print(
        "Analysis concurrency: "
        f"{concurrency.effective_strategy}, workers={concurrency.workers}{suffix}"
    )
    _render_coverage_issues(root, report.coverage_issues)
    _render_index_warnings(root, report.warnings)
    _render_index_failures(root, report.failures)


def _render_index_warnings(root: Path, warnings: list[IndexWarning]) -> None:
    """
    Render file-scoped analysis warnings from one index run.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative diagnostic labels.
    warnings : list[codira.indexer.IndexWarning]
        Recorded warning diagnostics to print.

    Returns
    -------
    None
        Warning diagnostics are printed to standard output.
    """
    for warning in warnings:
        rel_label = _relative_report_path(root, warning.path)
        line_suffix = f", line {warning.line}" if warning.line is not None else ""
        print(
            "warning: "
            f"{rel_label} ({warning.analyzer_name}, {warning.warning_type}"
            f"{line_suffix}, {warning.reason})"
        )


def _render_index_failures(root: Path, failures: list[IndexFailure]) -> None:
    """
    Render file-scoped analysis failures from one index run.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative diagnostic labels.
    failures : list[codira.indexer.IndexFailure]
        Recorded failure diagnostics to print.

    Returns
    -------
    None
        Failure diagnostics are printed to standard output.
    """
    for failure in failures:
        rel_label = _relative_report_path(root, failure.path)
        print(
            "failure: "
            f"{rel_label} ({failure.analyzer_name}, {failure.error_type}, "
            f"{failure.reason})"
        )


def _render_coverage_issues(root: Path, issues: list[CoverageIssue]) -> None:
    """
    Render canonical-directory coverage issues in deterministic text form.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative path labels.
    issues : list[codira.indexer.CoverageIssue]
        Coverage-issue rows to print.

    Returns
    -------
    None
        Coverage diagnostics are printed to standard output.
    """
    print(f"Coverage issues: {len(issues)}")
    grouped: OrderedDict[tuple[str, str], tuple[int, OrderedDict[str, None]]] = (
        OrderedDict()
    )
    for issue in issues:
        rel_path = Path(str(issue.path))
        try:
            rel_text = rel_path.relative_to(root).as_posix()
        except ValueError:
            rel_text = str(issue.path)
        top_level_directory = rel_text.split("/", 1)[0]
        key = (issue.suffix, issue.reason)
        count, directories = grouped.setdefault(key, (0, OrderedDict()))
        directories[top_level_directory] = None
        grouped[key] = (count + 1, directories)
    for (suffix, reason), (count, directories) in grouped.items():
        directory_list = ", ".join(directories)
        print(f"coverage: {suffix} x{count} in {directory_list} ({suffix}, {reason})")


def _run_coverage(root: Path, *, as_json: bool = False) -> int:
    """
    Inspect canonical-directory coverage for the active analyzer set.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose canonical tracked files should be inspected.
    as_json : bool, optional
        Whether to render structured JSON output.

    Returns
    -------
    int
        Zero when coverage is complete. JSON output also returns zero for
        incomplete coverage so automation can consume the structured findings.
    """
    analyzers = sorted(
        active_language_analyzers(root=root),
        key=lambda item: str(item.name),
    )
    issues = audit_repo_coverage(root)
    if get_metadata_path(root).exists():
        issues.extend(
            persisted_analysis_coverage_issues(root, active_index_backend(root=root))
        )
    coverage_config = load_effective_config(root=root).coverage
    configured_roots = coverage_config.roots
    if configured_roots == ("-",):
        coverage = {
            "source": "disabled",
            "patterns": [],
            "resolved_roots": [],
            "exclude_suffixes": list(coverage_config.exclude_suffixes),
        }
    else:
        roots = configured_roots or tuple(
            sorted(
                {
                    item
                    for analyzer in analyzers
                    for item in getattr(analyzer, "default_coverage_roots", ())
                }
            )
        )
        coverage = {
            "source": "config" if configured_roots else "analyzer-defaults",
            "patterns": list(roots),
            "exclude_suffixes": list(coverage_config.exclude_suffixes),
            "resolved_roots": sorted(
                {
                    path.relative_to(root).as_posix()
                    for pattern in roots
                    for path in root.glob(pattern)
                    if path.exists()
                }
            ),
        }

    if as_json:
        _emit_json(
            _query_payload(
                "cov",
                "ok" if not issues else "incomplete",
                {"coverage": coverage},
                [
                    {
                        "path": issue.path,
                        "directory": issue.directory,
                        "suffix": issue.suffix,
                        "reason": issue.reason,
                    }
                    for issue in issues
                ],
                analyzers=[
                    {
                        "name": str(analyzer.name),
                        "version": str(analyzer.version),
                        "discovery_globs": list(analyzer.discovery_globs),
                    }
                    for analyzer in analyzers
                ],
            )
        )
        return 0

    print(f"Coverage complete: {'yes' if not issues else 'no'}")
    print(f"Active analyzers: {len(analyzers)}")
    for analyzer in analyzers:
        globs = ", ".join(analyzer.discovery_globs)
        print(f"analyzer: {analyzer.name} version={analyzer.version} globs={globs}")
    _render_coverage_issues(root, issues)
    return 0 if not issues else 1


def _get_head_commit(root: Path) -> str | None:
    """
    Read the current Git commit hash for a repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used as the subprocess working directory.

    Returns
    -------
    str | None
        Current ``HEAD`` commit hash, or ``None`` if it cannot be read.
    """
    return read_head_commit(root)


def _git_dirty_indexable_paths(root: Path) -> tuple[str, ...]:
    """
    Return Git-dirty paths that can affect the Codira index.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used as the Git working directory.

    Returns
    -------
    tuple[str, ...]
        Repo-root-relative paths reported dirty by Git and accepted by one
        active analyzer. An empty tuple is returned when Git cannot provide a
        dirty-path list.
    """
    try:
        result = subprocess.run(
            [GIT_EXE, "diff", "--name-only", "-z", "HEAD", "--"],
            cwd=root,
            capture_output=True,
            text=False,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ()

    analyzers = active_language_analyzers(root=root)
    dirty_paths: list[str] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode("utf-8", errors="surrogateescape")
        path = root / relative
        if is_repository_scope_excluded(path, root):
            continue
        if any(analyzer_accepts_path(analyzer, path, root) for analyzer in analyzers):
            dirty_paths.append(relative)
    return tuple(dict.fromkeys(dirty_paths))


def _read_index_metadata(root: Path) -> dict[str, str]:
    """
    Load persisted index metadata.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the ``.codira`` directory.

    Returns
    -------
    dict[str, str]
        Parsed metadata values, or an empty mapping when the metadata file
        does not exist or cannot be decoded.
    """
    return _read_metadata_file(get_metadata_path(root))


def _write_index_metadata(root: Path, data: dict[str, str]) -> None:
    """
    Persist index metadata as JSON.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the ``.codira`` directory.
    data : dict[str, str]
        Metadata payload to serialize.

    Returns
    -------
    None
        The metadata file is written in place.
    """
    _write_metadata_file(get_metadata_path(root), data)


def _resolve_prefix_argument(
    parser: argparse.ArgumentParser,
    root: Path,
    prefix: str | None,
) -> str | None:
    """
    Normalize one CLI prefix argument or terminate with a parser error.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Active top-level parser used for error reporting.
    root : pathlib.Path
        Repository root that anchors the prefix.
    prefix : str | None
        User-supplied repo-root-relative prefix.

    Returns
    -------
    str | None
        Absolute normalized prefix path, or ``None`` when unset.
    """
    if prefix is not None and Path(prefix).is_absolute():
        parser.error("Prefix must be relative to the repository root.")
    try:
        normalized = normalize_prefix(root, prefix)
    except ValueError as exc:
        parser.error(str(exc))
    if normalized is not None and not Path(normalized).exists():
        parser.error(f"Prefix does not exist under repository root: {prefix}")
    return normalized


def _build_index_metadata(
    root: Path,
    *,
    indexed_file_count: int | None = None,
) -> dict[str, str]:
    """
    Build the persisted freshness metadata for the current repository head.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose current Git metadata should be recorded.
    indexed_file_count : int | None, optional
        Number of file rows known to be present after a successful index run.

    Returns
    -------
    dict[str, str]
        Metadata payload containing schema, plugin, analyzer, file-count, and
        current commit facts when available.
    """
    backend = active_index_backend(root=root)
    metadata = {"schema_version": str(backend.version)}
    commit = _get_head_commit(root)
    if commit:
        metadata["commit"] = commit
    metadata[INDEX_METADATA_BACKEND_NAME] = str(backend.name)
    metadata[INDEX_METADATA_BACKEND_VERSION] = str(backend.version)
    metadata[INDEX_METADATA_ANALYZER_INVENTORY] = json.dumps(
        _current_analyzer_inventory(root=root)
    )
    if indexed_file_count is not None:
        metadata[INDEX_METADATA_FILE_COUNT] = str(indexed_file_count)
    return metadata


def _count_indexed_files_for_freshness(
    backend: object,
    root: Path,
    *,
    conn: object | None = None,
) -> int:
    """
    Count indexed files for CLI freshness checks.

    Parameters
    ----------
    backend : object
        Active index backend.
    root : pathlib.Path
        Repository root whose index should be inspected.
    conn : object | None, optional
        Existing backend connection to reuse.

    Returns
    -------
    int
        Number of files currently recorded in the index.
    """
    count_indexed_files = getattr(backend, "count_indexed_files", None)
    if callable(count_indexed_files):
        return int(count_indexed_files(root, conn=conn))
    hash_loader = cast("_IndexedFileHashLoader", backend)
    return len(hash_loader.load_existing_file_hashes(root, conn=conn))


def _dirty_indexable_paths_require_rebuild(
    root: Path,
    dirty_paths: tuple[str, ...],
    backend: object,
    *,
    conn: object | None = None,
) -> bool:
    """
    Return whether Git-dirty indexable paths differ from indexed content.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be inspected.
    dirty_paths : tuple[str, ...]
        Repo-root-relative paths reported dirty by Git and accepted by one
        active analyzer.
    backend : object
        Active index backend.
    conn : object | None, optional
        Existing backend connection to reuse.

    Returns
    -------
    bool
        ``True`` when at least one dirty path is new, deleted, or has content
        that differs from the hash persisted in the index.
    """
    hash_loader = cast("_IndexedFileHashLoader", backend)
    indexed_hashes = hash_loader.load_existing_file_hashes(root, conn=conn)
    for relative in dirty_paths:
        path = root / relative
        persisted_hash = indexed_hashes.get(str(path))
        if persisted_hash is None:
            return True
        try:
            current_hash = str(file_metadata(path)["hash"])
        except FileNotFoundError:
            return True
        if current_hash != persisted_hash:
            return True
    return False


def _inspect_index_metadata_freshness(
    root: Path,
    metadata: dict[str, str],
) -> tuple[bool, IndexRebuildRequest | None]:
    """
    Inspect metadata-only freshness facts when available.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose metadata should be inspected.
    metadata : dict[str, str]
        Parsed persisted index metadata.

    Returns
    -------
    tuple[bool, IndexRebuildRequest | None]
        ``(True, request)`` when metadata is complete enough to decide, where
        ``request`` is ``None`` for a fresh index. ``(False, None)`` when the
        caller must fall back to backend inspection.
    """
    metadata_file_count = metadata.get(INDEX_METADATA_FILE_COUNT)
    metadata_analyzers = metadata.get(INDEX_METADATA_ANALYZER_INVENTORY)
    metadata_backend_name = metadata.get(INDEX_METADATA_BACKEND_NAME)
    metadata_backend_version = metadata.get(INDEX_METADATA_BACKEND_VERSION)
    if (
        metadata_file_count is None
        or metadata_analyzers is None
        or metadata_backend_name is None
        or metadata_backend_version is None
    ):
        return (False, None)

    backend = active_index_backend(root=root)
    current_runtime = (str(backend.name), str(backend.version))
    if (metadata_backend_name, metadata_backend_version) != current_runtime:
        return (
            True,
            IndexRebuildRequest(
                message="[codira] Index stale (backend plugin changed) — rebuilding...",
                reset_db=True,
                stderr=True,
            ),
        )

    current_analyzers = _current_analyzer_inventory(root=root)
    if metadata_analyzers != json.dumps(current_analyzers):
        return (
            True,
            IndexRebuildRequest(
                message="[codira] Index stale "
                "(analyzer plugin inventory changed) — rebuilding...",
                reset_db=True,
                stderr=True,
            ),
        )

    try:
        indexed_files = int(metadata_file_count)
    except ValueError:
        return (
            True,
            IndexRebuildRequest(
                message="[codira] Index stale — rebuilding...",
                reset_db=True,
                stderr=True,
            ),
        )
    current_files = len(
        list(iter_project_files(root, analyzers=active_language_analyzers(root=root)))
    )
    if indexed_files != current_files:
        return (
            True,
            IndexRebuildRequest(
                message="[codira] Index stale — rebuilding...",
                reset_db=True,
                stderr=True,
            ),
        )
    return (True, None)


def _inspect_index_rebuild_request(root: Path) -> IndexRebuildRequest | None:
    """
    Inspect the local index and report whether a rebuild is required.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose local index should be inspected.

    Returns
    -------
    IndexRebuildRequest | None
        Rebuild request when the index is missing or stale, otherwise ``None``.

    Raises
    ------
    OSError
        If the index files cannot be opened.
    codira.contracts.BackendError
        If the active backend cannot be queried safely.
    RuntimeError
        If the on-disk database is structurally invalid.
    ValueError
        If one of the backend validation checks raises a value error.
    """
    metadata = _read_index_metadata(root)
    if not metadata:
        return IndexRebuildRequest(
            message="[codira] Index not found — building it now...",
            reset_db=False,
            stderr=False,
        )

    current_commit = _get_head_commit(root)
    indexed_commit = metadata.get("commit")
    indexed_schema = metadata.get("schema_version")
    backend = active_index_backend(root=root)

    if indexed_schema != str(backend.version):
        return IndexRebuildRequest(
            message="[codira] Index schema changed — rebuilding...",
            reset_db=True,
            stderr=True,
        )

    if current_commit and indexed_commit != current_commit:
        return IndexRebuildRequest(
            message="[codira] Index outdated (git commit changed) — rebuilding...",
            reset_db=True,
            stderr=True,
        )

    dirty_paths = _git_dirty_indexable_paths(root)
    if dirty_paths:
        conn = backend.open_connection(root)
        try:
            if _dirty_indexable_paths_require_rebuild(
                root,
                dirty_paths,
                backend,
                conn=conn,
            ):
                return IndexRebuildRequest(
                    message="[codira] Index stale "
                    "(working tree changed) — rebuilding...",
                    reset_db=False,
                    stderr=True,
                )
        finally:
            backend.close_connection(conn)

    metadata_decided, metadata_request = _inspect_index_metadata_freshness(
        root,
        metadata,
    )
    if metadata_decided:
        return metadata_request

    conn = backend.open_connection(root)
    try:
        runtime_inventory = backend.load_runtime_inventory(root, conn=conn)
        current_runtime = (str(backend.name), str(backend.version))
        if runtime_inventory is None:
            return IndexRebuildRequest(
                message="[codira] Index stale (plugin inventory missing) "
                "— rebuilding...",
                reset_db=True,
                stderr=True,
            )

        if runtime_inventory[:2] != current_runtime:
            return IndexRebuildRequest(
                message="[codira] Index stale (backend plugin changed) — rebuilding...",
                reset_db=True,
                stderr=True,
            )

        persisted_analyzers = backend.load_analyzer_inventory(root, conn=conn)
        current_analyzers = _current_analyzer_inventory(root=root)
        if persisted_analyzers != current_analyzers:
            return IndexRebuildRequest(
                message="[codira] Index stale "
                "(analyzer plugin inventory changed) — rebuilding...",
                reset_db=True,
                stderr=True,
            )

        indexed_files = _count_indexed_files_for_freshness(
            backend,
            root,
            conn=conn,
        )
        current_files = len(
            list(
                iter_project_files(root, analyzers=active_language_analyzers(root=root))
            )
        )

        if indexed_files != current_files:
            return IndexRebuildRequest(
                message="[codira] Index stale — rebuilding...",
                reset_db=True,
                stderr=True,
            )
        return None
    finally:
        backend.close_connection(conn)


def _run_locked_index_refresh(
    root: Path,
    request: IndexRebuildRequest,
) -> None:
    """
    Rebuild the local index while holding the exclusive mutation lock.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be rebuilt.
    request : IndexRebuildRequest
        Rebuild request describing the status line and reset mode.

    Returns
    -------
    None
        The index is rebuilt and freshness metadata is refreshed in place.
    """
    if request.stderr:
        print(request.message, file=sys.stderr)
    else:
        print(request.message)
    active_index_backend(root=root).initialize(root)
    index_repo(root)
    print("[codira] Index ready", file=sys.stderr)


def _fail_unreadable_index(error: Exception) -> None:
    """
    Terminate after reporting one corrupted or unreadable index.

    Parameters
    ----------
    error : Exception
        Underlying index access failure.

    Returns
    -------
    None
        The function does not return.

    Raises
    ------
    SystemExit
        Always raised with exit status ``1``.
    """
    print("ERROR: repository index is corrupted or unreadable")
    print("Suggested fix: codira index")
    print(f"Details: {error}")
    raise SystemExit(1) from error


def _ensure_index(root: Path) -> None:
    """
    Ensure that the repository index exists and is usable.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose local index should be checked.

    Returns
    -------
    None
        The function returns after confirming or rebuilding the index.

    Raises
    ------
    SystemExit
        If the index cannot be built or is corrupted and unreadable.

    Notes
    -----
    If the on-disk index is missing or stale, the function rebuilds it
    automatically and refreshes the stored Git commit metadata.
    """
    initial_error: Exception | None = None
    try:
        request = _inspect_index_rebuild_request(root)
    except (BackendError, OSError, RuntimeError, ValueError) as error:
        request = None
        initial_error = error

    if request is None and initial_error is None:
        return

    def run_refresh_without_lock(refresh_request: IndexRebuildRequest) -> None:
        """
        Rebuild the index without advisory locking on platforms lacking flock.

        Parameters
        ----------
        refresh_request : IndexRebuildRequest
            Rebuild request already derived from the current on-disk state.

        Returns
        -------
        None
            The index is refreshed in place without cross-process locking.
        """
        try:
            _run_locked_index_refresh(root, refresh_request)
        except (
            BackendError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            print("ERROR: failed to build index automatically")
            print("Run manually: codira index")
            print(f"Details: {error}")
            raise SystemExit(1) from error

    try:
        with acquire_index_lock(root):
            if initial_error is not None:
                try:
                    request = _inspect_index_rebuild_request(root)
                except (
                    BackendError,
                    OSError,
                    RuntimeError,
                    ValueError,
                ) as error:
                    _fail_unreadable_index(error)

            if request is None:
                return

            try:
                refreshed_request = _inspect_index_rebuild_request(root)
            except (
                BackendError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                _fail_unreadable_index(error)

            if refreshed_request is None:
                return

            try:
                _run_locked_index_refresh(root, refreshed_request)
            except (
                BackendError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                print("ERROR: failed to build index automatically")
                print("Run manually: codira index")
                print(f"Details: {error}")
                raise SystemExit(1) from error
    except RuntimeError as error:
        if "fcntl.flock" in str(error) and request is not None:
            run_refresh_without_lock(request)
            return
        _fail_unreadable_index(error)
