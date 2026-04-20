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
import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

from codira_backend_sqlite import SQLiteIndexBackend

from codira import indexer, sqlite_backend_support
from codira.indexer import index_repo
from codira.semantic import embeddings as embeddings_module


@dataclass
class BenchmarkStats:
    """
    Collected benchmark timings and embedding batch metrics.

    Parameters
    ----------
    phase_seconds : dict[str, float], optional
        Accumulated timing keyed by instrumented phase name.
    embedding_batch_sizes : list[int], optional
        Observed batch sizes passed into the embedding backend.
    """

    phase_seconds: dict[str, float] = field(default_factory=dict)
    embedding_batch_sizes: list[int] = field(default_factory=list)

    def add_phase_time(self, name: str, elapsed: float) -> None:
        """
        Accumulate one measured duration under a stable phase name.

        Parameters
        ----------
        name : str
            Phase label receiving the elapsed duration.
        elapsed : float
            Measured seconds to add.

        Returns
        -------
        None
            The timing map is updated in place.
        """
        self.phase_seconds[name] = self.phase_seconds.get(name, 0.0) + elapsed


def _timed_call(
    stats: BenchmarkStats,
    phase_name: str,
    func: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> object:
    """
    Execute one callable while accumulating its elapsed duration.

    Parameters
    ----------
    stats : BenchmarkStats
        Benchmark accumulator updated in place.
    phase_name : str
        Stable label for the timed phase.
    func : collections.abc.Callable[..., object]
        Callable to execute.
    *args : object
        Positional arguments forwarded to ``func``.
    **kwargs : object
        Keyword arguments forwarded to ``func``.

    Returns
    -------
    object
        Return value from ``func``.
    """
    start = perf_counter()
    try:
        return func(*args, **kwargs)
    finally:
        stats.add_phase_time(phase_name, perf_counter() - start)


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
    return parser


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
    stats = BenchmarkStats()

    original_collect_scan = indexer._collect_project_scan_state
    original_collect_analyses = indexer._collect_indexed_file_analyses
    original_persist_analyses = indexer._persist_indexed_file_analyses
    original_flush_rows = sqlite_backend_support._flush_embedding_rows
    original_rebuild_indexes = SQLiteIndexBackend.rebuild_derived_indexes
    original_embed_texts = embeddings_module.embed_texts
    original_sqlite_support_embed_texts = cast(
        "Callable[[Sequence[str]], list[list[float]]]",
        sqlite_backend_support.embed_texts,
    )

    def benchmark_collect_scan(*args: object, **kwargs: object) -> object:
        return _timed_call(
            stats,
            "collect_project_scan_state",
            original_collect_scan,
            *args,
            **kwargs,
        )

    def benchmark_collect_analyses(*args: object, **kwargs: object) -> object:
        return _timed_call(
            stats,
            "collect_indexed_file_analyses",
            original_collect_analyses,
            *args,
            **kwargs,
        )

    def benchmark_persist_analyses(*args: object, **kwargs: object) -> object:
        return _timed_call(
            stats,
            "persist_indexed_file_analyses",
            original_persist_analyses,
            *args,
            **kwargs,
        )

    def benchmark_flush_rows(*args: object, **kwargs: object) -> object:
        return _timed_call(
            stats,
            "flush_embedding_rows",
            original_flush_rows,
            *args,
            **kwargs,
        )

    def benchmark_rebuild_indexes(
        self: SQLiteIndexBackend,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        _timed_call(
            stats,
            "rebuild_derived_indexes",
            original_rebuild_indexes,
            self,
            root,
            conn=conn,
        )

    def benchmark_embed_texts(texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        stats.embedding_batch_sizes.append(len(batch))
        result = _timed_call(
            stats,
            "embed_texts",
            original_embed_texts,
            batch,
        )
        return cast("list[list[float]]", result)

    indexer._collect_project_scan_state = benchmark_collect_scan  # type: ignore[assignment]
    indexer._collect_indexed_file_analyses = benchmark_collect_analyses  # type: ignore[assignment]
    indexer._persist_indexed_file_analyses = benchmark_persist_analyses  # type: ignore[assignment]
    sqlite_backend_support._flush_embedding_rows = benchmark_flush_rows  # type: ignore[assignment]
    SQLiteIndexBackend.rebuild_derived_indexes = benchmark_rebuild_indexes  # type: ignore[method-assign]
    embeddings_module.embed_texts = benchmark_embed_texts
    sqlite_backend_support.embed_texts = benchmark_embed_texts

    total_start = perf_counter()
    try:
        report = index_repo(root, full=args.full)
    finally:
        total_elapsed = perf_counter() - total_start
        indexer._collect_project_scan_state = original_collect_scan
        indexer._collect_indexed_file_analyses = original_collect_analyses
        indexer._persist_indexed_file_analyses = original_persist_analyses
        sqlite_backend_support._flush_embedding_rows = original_flush_rows
        SQLiteIndexBackend.rebuild_derived_indexes = original_rebuild_indexes  # type: ignore[method-assign]
        embeddings_module.embed_texts = original_embed_texts
        sqlite_backend_support.embed_texts = original_sqlite_support_embed_texts  # type: ignore[assignment]

    batch_sizes = stats.embedding_batch_sizes
    benchmark_report = {
        "root": str(root),
        "full": bool(args.full),
        "timings": {
            **{
                name: round(value, 6)
                for name, value in sorted(stats.phase_seconds.items())
            },
            "total": round(total_elapsed, 6),
        },
        "embedding_batches": {
            "calls": len(batch_sizes),
            "total_rows": sum(batch_sizes),
            "max_batch_size": max(batch_sizes, default=0),
            "avg_batch_size": (
                round(sum(batch_sizes) / len(batch_sizes), 3) if batch_sizes else 0.0
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
    print(json.dumps(benchmark_report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
