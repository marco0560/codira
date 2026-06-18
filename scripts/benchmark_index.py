"""Benchmark codira indexing phases and embedding batch behavior.

Responsibilities
----------------
- Run one deterministic index pass against a target repository root.
- Time major indexing phases by instrumenting the in-process indexer hooks.
- Report embedding batch sizes and flush timings to support performance tuning.

Design principles
-----------------
The benchmark script stays read-mostly, emits structured JSON, and avoids
changing normal CLI behavior.

Architectural role
------------------
This module belongs to the **developer tooling layer** and provides
operator-facing indexing diagnostics.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from typing import Protocol

    class _BenchmarkRebuildCapable(Protocol):
        def rebuild_derived_indexes(
            self,
            root: Path,
            *,
            conn: object | None = None,
        ) -> None: ...

    class _BenchmarkBackendSupportModule(Protocol):
        _flush_embedding_rows: Callable[..., object]
        embed_texts: Callable[[Sequence[str]], list[list[float]]]


from benchmark_timing import (  # type: ignore[import-not-found]
    PhaseTimer,
    benchmark_metadata,
    write_json_artifact,
)

from codira import indexer
from codira.indexer import index_repo
from codira.registry import active_index_backend
from codira.semantic import embeddings as embeddings_module
from codira.storage import override_storage_root


def build_parser() -> argparse.ArgumentParser:
    """
    Build the benchmark CLI parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser for one benchmark invocation.
    """
    parser = argparse.ArgumentParser(
        description="Benchmark codira indexing phases and embedding batches.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Repository root to benchmark.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force a full index rebuild during the benchmark run.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the benchmark JSON artifact to this path.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory under which .codira benchmark state is stored.",
    )
    return parser


def active_backend_class(root: Path) -> type[_BenchmarkRebuildCapable]:
    """
    Return the active backend class for benchmark instrumentation.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose repo-local config selects the backend.

    Returns
    -------
    type[_BenchmarkRebuildCapable]
        Concrete backend class selected for the current process.
    """
    return cast("type[_BenchmarkRebuildCapable]", type(active_index_backend(root=root)))


def active_backend_support_module(root: Path) -> _BenchmarkBackendSupportModule:
    """
    Return the package-local support module for the active backend.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose repo-local config selects the backend.

    Returns
    -------
    _BenchmarkBackendSupportModule
        Imported backend-owned helper module used for embedding flush
        instrumentation during benchmark runs.

    Raises
    ------
    RuntimeError
        Raised when the configured backend does not expose a supported helper
        module mapping for the benchmark helper.
    """
    backend_name = active_index_backend(root=root).name
    support_module_by_backend = {
        "sqlite": "codira_backend_sqlite.sqlite_support",
        "duckdb": "codira_backend_duckdb.duckdb_support",
    }
    module_name = support_module_by_backend.get(backend_name)
    if module_name is None:
        msg = (
            "benchmark_index.py does not know how to instrument backend "
            f"{backend_name!r}"
        )
        raise RuntimeError(msg)
    return cast(
        "_BenchmarkBackendSupportModule",
        # nosemgrep: python.lang.security.audit.non-literal-import.non-literal-import
        importlib.import_module(module_name),
    )


def main() -> int:
    """
    Run the benchmark and print one JSON report.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero on success.
    """
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    output_dir = None if args.output_dir is None else Path(args.output_dir).resolve()
    timer = PhaseTimer()
    embedding_batch_sizes: list[int] = []
    embedding_unique_batch_sizes: list[int] = []

    original_collect_scan = indexer._collect_project_scan_state
    original_collect_analyses = indexer._collect_indexed_file_analyses
    original_persist_analyses = indexer._persist_indexed_file_analyses
    original_select_analyzer = indexer._select_language_analyzer
    original_iter_project_files = cast(
        "Callable[..., object]",
        indexer.iter_project_files,  # type: ignore[attr-defined]
    )
    original_file_metadata = cast(
        "Callable[..., object]",
        indexer.file_metadata,  # type: ignore[attr-defined]
    )
    backend_class = active_backend_class(root)
    backend_support = active_backend_support_module(root)
    original_flush_rows = backend_support._flush_embedding_rows
    original_rebuild_indexes = backend_class.rebuild_derived_indexes
    original_embed_texts = embeddings_module.embed_texts
    original_backend_support_embed_texts = backend_support.embed_texts

    def benchmark_collect_scan(*args: object, **kwargs: object) -> object:
        return timer.timed_call(
            "scan_state",
            original_collect_scan,
            *args,
            **kwargs,
        )

    def benchmark_collect_analyses(*args: object, **kwargs: object) -> object:
        return timer.timed_call(
            "parsing",
            original_collect_analyses,
            *args,
            **kwargs,
        )

    def benchmark_persist_analyses(*args: object, **kwargs: object) -> object:
        return timer.timed_call(
            "indexing",
            original_persist_analyses,
            *args,
            **kwargs,
        )

    def benchmark_select_analyzer(*args: object, **kwargs: object) -> object:
        return timer.timed_call(
            "filtering",
            original_select_analyzer,
            *args,
            **kwargs,
        )

    def benchmark_iter_project_files(*args: object, **kwargs: object) -> object:
        with timer.measure("discovery"):
            paths = tuple(
                cast("Iterable[Path]", original_iter_project_files(*args, **kwargs))
            )
        return iter(paths)

    def benchmark_file_metadata(*args: object, **kwargs: object) -> object:
        return timer.timed_call(
            "metadata",
            original_file_metadata,
            *args,
            **kwargs,
        )

    def benchmark_flush_rows(*args: object, **kwargs: object) -> object:
        return timer.timed_call(
            "embeddings",
            original_flush_rows,
            *args,
            **kwargs,
        )

    def benchmark_rebuild_indexes(
        self: object,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        timer.timed_call(
            "indexing",
            original_rebuild_indexes,
            self,
            root,
            conn=conn,
        )

    def benchmark_embed_texts(texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        embedding_batch_sizes.append(len(batch))
        embedding_unique_batch_sizes.append(len(set(batch)))
        result = timer.timed_call(
            "embeddings",
            original_embed_texts,
            batch,
        )
        return cast("list[list[float]]", result)

    indexer._collect_project_scan_state = benchmark_collect_scan  # type: ignore[assignment]
    indexer._collect_indexed_file_analyses = benchmark_collect_analyses  # type: ignore[assignment]
    indexer._persist_indexed_file_analyses = benchmark_persist_analyses  # type: ignore[assignment]
    indexer._select_language_analyzer = benchmark_select_analyzer  # type: ignore[assignment]
    indexer.iter_project_files = benchmark_iter_project_files  # type: ignore[attr-defined, assignment]
    indexer.file_metadata = benchmark_file_metadata  # type: ignore[attr-defined, assignment]
    backend_support._flush_embedding_rows = benchmark_flush_rows
    backend_class.rebuild_derived_indexes = benchmark_rebuild_indexes  # type: ignore[method-assign]
    embeddings_module.embed_texts = benchmark_embed_texts
    backend_support.embed_texts = benchmark_embed_texts

    total_start = perf_counter()
    try:
        if output_dir is None:
            active_index_backend(root=root).initialize(root)
            report = index_repo(root, full=args.full)
        else:
            with override_storage_root(root, output_dir):
                active_index_backend(root=root).initialize(root)
                report = index_repo(root, full=args.full)
    finally:
        total_elapsed = perf_counter() - total_start
        indexer._collect_project_scan_state = original_collect_scan
        indexer._collect_indexed_file_analyses = original_collect_analyses
        indexer._persist_indexed_file_analyses = original_persist_analyses
        indexer._select_language_analyzer = original_select_analyzer
        indexer.iter_project_files = original_iter_project_files  # type: ignore[attr-defined, assignment]
        indexer.file_metadata = original_file_metadata  # type: ignore[attr-defined, assignment]
        backend_support._flush_embedding_rows = original_flush_rows
        backend_class.rebuild_derived_indexes = original_rebuild_indexes  # type: ignore[method-assign]
        embeddings_module.embed_texts = original_embed_texts
        backend_support.embed_texts = original_backend_support_embed_texts

    benchmark_report = {
        "metadata": benchmark_metadata(root),
        "root": str(root),
        "output_dir": None if output_dir is None else str(output_dir),
        "full": bool(args.full),
        "timings": {
            **timer.rounded(),
            "total": round(total_elapsed, 6),
        },
        "embedding_batches": {
            "calls": len(embedding_batch_sizes),
            "total_rows": sum(embedding_batch_sizes),
            "unique_rows": sum(embedding_unique_batch_sizes),
            "max_batch_size": max(embedding_batch_sizes, default=0),
            "max_unique_batch_size": max(embedding_unique_batch_sizes, default=0),
            "avg_batch_size": (
                round(sum(embedding_batch_sizes) / len(embedding_batch_sizes), 3)
                if embedding_batch_sizes
                else 0.0
            ),
            "avg_unique_batch_size": (
                round(
                    sum(embedding_unique_batch_sizes)
                    / len(embedding_unique_batch_sizes),
                    3,
                )
                if embedding_unique_batch_sizes
                else 0.0
            ),
            "duplicate_rows": (
                sum(embedding_batch_sizes) - sum(embedding_unique_batch_sizes)
            ),
        },
        "report": {
            "indexed": report.indexed,
            "reused": report.reused,
            "deleted": report.deleted,
            "failed": report.failed,
            "embeddings_recomputed": report.embeddings_recomputed,
            "embeddings_reused": report.embeddings_reused,
            "coverage_issues": len(report.coverage_issues),
        },
    }
    if args.output is not None:
        write_json_artifact(Path(args.output), benchmark_report)
    print(json.dumps(benchmark_report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
