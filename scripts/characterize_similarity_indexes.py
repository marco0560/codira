#!/usr/bin/env python3
"""Characterize exact and FAISS HNSW retrieval on a deterministic corpus.

The report is descriptive release evidence, not a retrieval-quality gate.  It
keeps hardware-sensitive timings separate from deterministic exact-reference
and recall measurements.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import struct
import tempfile
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from codira_similarity_index_faiss import FaissSimilarityIndex

from codira.contracts import (
    EmbeddingEngineSpec,
    SimilarityIndexIdentity,
    SimilaritySearchProfile,
    SimilaritySearchRequest,
    SimilaritySearchResult,
    StoredVectorRow,
    VectorSetIdentity,
    VectorSnapshot,
    VectorSnapshotMetadata,
    VectorStoreSpec,
)
from codira.similarity import ExactSimilarityIndex

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

CHARACTERIZATION_VERSION = 1
DEFAULT_SEED = 20
DEFAULT_VECTOR_COUNT = 128
DEFAULT_DIMENSION = 32
DEFAULT_QUERY_COUNT = 16
DEFAULT_TOP_K = 10
DEFAULT_REPEATS = 3


def _normalized_values(randomizer: random.Random, dimension: int) -> tuple[float, ...]:
    """Return one deterministic unit vector.

    Parameters
    ----------
    randomizer : random.Random
        Seeded random-number source.
    dimension : int
        Positive vector dimension.

    Returns
    -------
    tuple[float, ...]
        L2-normalized deterministic values.
    """
    values = tuple(randomizer.uniform(-1.0, 1.0) for _ in range(dimension))
    norm = sum(value * value for value in values) ** 0.5
    if norm == 0.0:
        message = "Deterministic corpus unexpectedly produced a zero vector."
        raise RuntimeError(message)
    return tuple(value / norm for value in values)


def build_synthetic_corpus(
    *,
    seed: int = DEFAULT_SEED,
    vector_count: int = DEFAULT_VECTOR_COUNT,
    dimension: int = DEFAULT_DIMENSION,
    query_count: int = DEFAULT_QUERY_COUNT,
) -> tuple[VectorSnapshot, tuple[tuple[float, ...], ...]]:
    """Build a fixed snapshot and query workload without external input.

    Parameters
    ----------
    seed : int, optional
        Random seed defining vectors and queries.
    vector_count : int, optional
        Number of stored vectors. Must be positive.
    dimension : int, optional
        Vector dimension. Must be positive.
    query_count : int, optional
        Number of query vectors. Must be positive.

    Returns
    -------
    tuple[codira.contracts.VectorSnapshot, tuple[tuple[float, ...], ...]]
        Ordered durable snapshot and ordered normalized query workload.

    Raises
    ------
    ValueError
        If any corpus dimension is non-positive.
    """
    if min(vector_count, dimension, query_count) <= 0:
        message = "Synthetic corpus vector_count, dimension, and query_count must be positive."
        raise ValueError(message)
    randomizer = random.Random(seed)
    identity = VectorSetIdentity(
        engine=EmbeddingEngineSpec(
            "characterization", "1", "synthetic", str(seed), dimension
        ),
        vector_store=VectorStoreSpec("characterization", "1", "1"),
    )
    rows = tuple(
        StoredVectorRow(
            "symbol",
            f"synthetic:{index:04d}",
            f"source:{index:04d}",
            dimension,
            struct.pack(f"<{dimension}f", *_normalized_values(randomizer, dimension)),
        )
        for index in range(vector_count)
    )
    snapshot = VectorSnapshot(
        VectorSnapshotMetadata(identity, 1, "symbol", len(rows)), rows
    )
    queries = tuple(
        _normalized_values(randomizer, dimension) for _ in range(query_count)
    )
    return snapshot, queries


def _identity(
    root: Path,
    index: FaissSimilarityIndex,
    config: dict[str, object],
    snapshot: VectorSnapshot,
) -> SimilarityIndexIdentity:
    """Return the root-bound identity for one FAISS configuration.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root for the derived artifact.
    index : codira_similarity_index_faiss.FaissSimilarityIndex
        Configured FAISS implementation.
    config : dict[str, object]
        FAISS build configuration.
    snapshot : codira.contracts.VectorSnapshot
        Durable source snapshot.

    Returns
    -------
    codira.contracts.SimilarityIndexIdentity
        Selected identity for the configured artifact.
    """
    return SimilarityIndexIdentity(root, snapshot.metadata.identity, index.spec(config))


def _request(
    identity: SimilarityIndexIdentity,
    snapshot: VectorSnapshot,
    query: tuple[float, ...],
    *,
    top_k: int,
    ef_search: int,
) -> SimilaritySearchRequest:
    """Return one bounded characterization search request.

    Parameters
    ----------
    identity : codira.contracts.SimilarityIndexIdentity
        Root-bound selected index identity.
    snapshot : codira.contracts.VectorSnapshot
        Authoritative ordered source vectors.
    query : tuple[float, ...]
        Normalized query vector.
    top_k : int
        Candidate and result count used for recall comparison.
    ef_search : int
        Per-query HNSW graph exploration setting.

    Returns
    -------
    codira.contracts.SimilaritySearchRequest
        Deterministic bounded query request.
    """
    return SimilaritySearchRequest(
        identity,
        snapshot,
        query,
        SimilaritySearchProfile("characterization", ef_search, top_k, top_k, top_k),
    )


def _median_latency_ns(operation: Callable[[], object], *, repeats: int) -> int:
    """Measure a short operation repeatedly and return its median duration.

    Parameters
    ----------
    operation : collections.abc.Callable[[], object]
        Operation whose result is intentionally discarded.
    repeats : int
        Positive number of timed repetitions.

    Returns
    -------
    int
        Median elapsed wall-clock time in nanoseconds.

    Raises
    ------
    ValueError
        If ``repeats`` is not positive.
    """
    if repeats <= 0:
        message = "Characterization repeats must be positive."
        raise ValueError(message)
    timings: list[int] = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        operation()
        timings.append(time.perf_counter_ns() - started)
    return int(statistics.median(timings))


def _artifact_size_bytes(root: Path) -> int:
    """Return the complete derived-artifact size below one temporary root.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root containing FAISS artifacts.

    Returns
    -------
    int
        Sum of regular-file sizes in bytes.
    """
    artifact_root = root / ".codira" / "similarity-indexes" / "faiss"
    return sum(
        path.stat().st_size for path in artifact_root.rglob("*") if path.is_file()
    )


def _top_ids(result: SimilaritySearchResult) -> tuple[str, ...]:
    """Return stable IDs from a typed similarity result.

    Parameters
    ----------
    result : codira.contracts.SimilaritySearchResult
        Ordered similarity candidates with query provenance.

    Returns
    -------
    tuple[str, ...]
        Ordered stable IDs.
    """
    return tuple(candidate.stable_id for candidate in result.candidates)


def _rebuild(
    index: FaissSimilarityIndex,
    snapshot: VectorSnapshot,
    identity: SimilarityIndexIdentity,
) -> None:
    """Rebuild one selected FAISS artifact for timing.

    Parameters
    ----------
    index : codira_similarity_index_faiss.FaissSimilarityIndex
        Configured FAISS implementation.
    snapshot : codira.contracts.VectorSnapshot
        Authoritative source snapshot.
    identity : codira.contracts.SimilarityIndexIdentity
        Root-bound derived artifact identity.

    Returns
    -------
    None
        The artifact is rebuilt.
    """
    index.rebuild(snapshot, identity)


def _search_all(
    index: FaissSimilarityIndex,
    requests: Sequence[SimilaritySearchRequest],
) -> list[SimilaritySearchResult]:
    """Search the deterministic workload through one selected FAISS index.

    Parameters
    ----------
    index : codira_similarity_index_faiss.FaissSimilarityIndex
        Configured FAISS implementation.
    requests : collections.abc.Sequence[codira.contracts.SimilaritySearchRequest]
        Ordered profile-bound search requests.

    Returns
    -------
    list[codira.contracts.SimilaritySearchResult]
        Ordered candidate results for every workload query.
    """
    return [index.search(request) for request in requests]


def run_characterization(  # noqa: PLR0913
    *,
    seed: int = DEFAULT_SEED,
    vector_count: int = DEFAULT_VECTOR_COUNT,
    dimension: int = DEFAULT_DIMENSION,
    query_count: int = DEFAULT_QUERY_COUNT,
    top_k: int = DEFAULT_TOP_K,
    repeats: int = DEFAULT_REPEATS,
) -> dict[str, object]:
    """Measure exact-reference and FAISS flat/HNSW behavior on one corpus.

    Parameters
    ----------
    seed : int, optional
        Synthetic-corpus random seed.
    vector_count : int, optional
        Number of synthetic vectors.
    dimension : int, optional
        Synthetic vector dimension.
    query_count : int, optional
        Number of synthetic queries.
    top_k : int, optional
        Compared top-k result count.
    repeats : int, optional
        Timed rebuild/query repetitions.

    Returns
    -------
    dict[str, object]
        JSON-ready deterministic corpus metadata, exact reference, and
        hardware-sensitive FAISS measurements.

    Raises
    ------
    ValueError
        If ``top_k`` exceeds the synthetic vector count.
    """
    snapshot, queries = build_synthetic_corpus(
        seed=seed,
        vector_count=vector_count,
        dimension=dimension,
        query_count=query_count,
    )
    if not 0 < top_k <= vector_count:
        message = "Characterization top_k must be between 1 and vector_count."
        raise ValueError(message)

    exact = ExactSimilarityIndex()
    exact_identity = SimilarityIndexIdentity(
        Path("/synthetic-exact"), snapshot.metadata.identity, exact.spec({})
    )
    reference = [
        _top_ids(
            exact.search(
                _request(exact_identity, snapshot, query, top_k=top_k, ef_search=top_k)
            )
        )
        for query in queries
    ]
    modes: dict[str, object] = {}
    configurations: tuple[tuple[str, dict[str, object], int], ...] = (
        ("flat", {"index_type": "flat"}, top_k),
        ("hnsw", {"index_type": "hnsw", "M": 16, "efConstruction": 80}, 64),
    )
    for name, config, ef_search in configurations:
        with tempfile.TemporaryDirectory(
            prefix="codira-similarity-characterization-"
        ) as temporary:
            root = Path(temporary)
            index = FaissSimilarityIndex()
            index.initialize(root, config)
            identity = _identity(root, index, config, snapshot)
            build_latency_ns = _median_latency_ns(
                partial(_rebuild, index, snapshot, identity),
                repeats=repeats,
            )
            requests = tuple(
                _request(identity, snapshot, query, top_k=top_k, ef_search=ef_search)
                for query in queries
            )
            index.reset_runtime_caches()
            cold_latency_ns = _median_latency_ns(
                partial(_search_all, index, requests),
                repeats=repeats,
            )
            warm_latency_ns = _median_latency_ns(
                partial(_search_all, index, requests),
                repeats=repeats,
            )
            observed = [_top_ids(scores) for scores in _search_all(index, requests)]
            overlaps = [
                len(set(expected).intersection(actual)) / top_k
                for expected, actual in zip(reference, observed, strict=True)
            ]
            modes[name] = {
                "build_latency_ns_median": build_latency_ns,
                "cold_query_latency_ns_median": cold_latency_ns,
                "warm_query_latency_ns_median": warm_latency_ns,
                "artifact_size_bytes": _artifact_size_bytes(root),
                "recall_at_k": sum(overlaps) / len(overlaps),
                "first_query_top_k": list(observed[0]),
            }
    return {
        "schema_version": CHARACTERIZATION_VERSION,
        "corpus": {
            "seed": seed,
            "vector_count": vector_count,
            "dimension": dimension,
            "query_count": query_count,
            "top_k": top_k,
            "timing_repeats": repeats,
        },
        "exact_reference": {"first_query_top_k": list(reference[0])},
        "modes": modes,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse deterministic-characterization command-line arguments.

    Parameters
    ----------
    argv : list[str] | None, optional
        Explicit command-line arguments, or ``None`` for process arguments.

    Returns
    -------
    argparse.Namespace
        Parsed characterization settings and optional output path.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--vectors", type=int, default=DEFAULT_VECTOR_COUNT)
    parser.add_argument("--dimension", type=int, default=DEFAULT_DIMENSION)
    parser.add_argument("--queries", type=int, default=DEFAULT_QUERY_COUNT)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run and emit one deterministic similarity-index characterization.

    Parameters
    ----------
    argv : list[str] | None, optional
        Explicit command-line arguments, or ``None`` for process arguments.

    Returns
    -------
    int
        Zero after printing and optionally writing canonical JSON.
    """
    args = parse_args(argv)
    report = run_characterization(
        seed=args.seed,
        vector_count=args.vectors,
        dimension=args.dimension,
        query_count=args.queries,
        top_k=args.top_k,
        repeats=args.repeats,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
