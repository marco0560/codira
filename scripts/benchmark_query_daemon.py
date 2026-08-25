#!/usr/bin/env python3
"""Measure direct and warm repository-local query daemon reads.

The script is deliberately an operator tool, not a timing-sensitive test. It
starts one fixed-root daemon in-process, compares repeated eligible CLI reads,
and writes reproducible measurements under ``.artifacts/benchmarks``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import resource
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import TYPE_CHECKING

from codira.cli import (
    EmbeddingCommandRequest,
    _run_capabilities,
    _run_context_without_freshness_check,
    _run_embeddings,
    _run_plugins,
    build_query_daemon_cli_operations,
)
from codira.query_daemon import QueryDaemonIdentity, build_query_runtime
from codira.query_daemon_cli import route_cli_read
from codira.query_daemon_ipc import QueryDaemonIpcPaths, QueryDaemonIpcServer

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_timing import benchmark_metadata  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from collections.abc import Callable


def _positive_int(value: str) -> int:
    """Parse a strictly positive run count.

    Parameters
    ----------
    value : str
        Raw command-line value.

    Returns
    -------
    int
        Positive integer count.

    Raises
    ------
    argparse.ArgumentTypeError
        If the value is not positive.
    """
    parsed = int(value)
    if parsed < 1:
        msg = "runs must be positive"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def _measure(operation: Callable[[], int], runs: int) -> dict[str, float]:
    """Measure repeated operation wall-clock times without pass/fail thresholds.

    Parameters
    ----------
    operation : collections.abc.Callable[[], int]
        Read operation whose output is discarded.
    runs : int
        Number of measured invocations.

    Returns
    -------
    dict[str, float]
        Mean and minimum elapsed milliseconds.
    """
    samples: list[float] = []
    for _ in range(runs):
        output = io.StringIO()
        start = perf_counter()
        with contextlib.redirect_stdout(output):
            operation()
        samples.append((perf_counter() - start) * 1000)
    return {"mean_ms": round(fmean(samples), 3), "min_ms": round(min(samples), 3)}


def _parser() -> argparse.ArgumentParser:
    """Build the query-daemon benchmark command parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured benchmark parser.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--runs", type=_positive_int, default=5)
    parser.add_argument("--query", default="query daemon")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run and persist a local direct-versus-warm query measurement.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero after a successful measurement artifact is written.

    Raises
    ------
    RuntimeError
        If the root has no ready generation or daemon endpoint is occupied.
    """
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    identity = QueryDaemonIdentity.from_paths(root, root)
    paths = QueryDaemonIpcPaths(identity)
    if paths.endpoint_path.exists():
        msg = "query-daemon endpoint already exists; stop it before benchmarking"
        raise RuntimeError(msg)
    runtime = build_query_runtime(identity)
    if not runtime.refresh_from_generation_store():
        msg = "a ready index generation is required; run codira index first"
        raise RuntimeError(msg)
    server = QueryDaemonIpcServer(
        identity, runtime, build_query_daemon_cli_operations(root)
    )
    server.start()
    try:
        direct_operations: dict[str, Callable[[], int]] = {
            "ctx": lambda: _run_context_without_freshness_check(
                root,
                query=args.query,
                as_json=True,
                as_prompt=False,
                explain=False,
                search_profile=None,
            ),
            "emb": lambda: _run_embeddings(
                EmbeddingCommandRequest(
                    root=root,
                    query=args.query,
                    limit=5,
                    prefix=None,
                    as_json=True,
                    query_prefix=None,
                )
            ),
            "plugins": lambda: _run_plugins(root=root, as_json=True),
            "caps": lambda: _run_capabilities(root=root, as_json=True, strict=False),
        }
        warm_arguments = {
            "ctx": {
                "query": args.query,
                "as_json": True,
                "as_prompt": False,
                "explain": False,
            },
            "emb": {
                "query": args.query,
                "limit": 5,
                "as_json": True,
                "query_prefix": None,
            },
            "plugins": {"as_json": True},
            "caps": {"as_json": True, "strict": False},
        }
        results: dict[str, object] = {}
        for name, direct in direct_operations.items():
            warm = route_cli_read(
                root, f"cli.{name}", warm_arguments[name], enabled=True
            )
            if warm.mode != "warm":
                msg = f"warm {name} benchmark failed: {warm.failure or warm.mode}"
                raise RuntimeError(msg)

            def warm_operation(name: str = name) -> int:
                """Run one verified warm CLI request for measurement.

                Parameters
                ----------
                name : str, optional
                    Eligible CLI operation selected by the enclosing loop.

                Returns
                -------
                int
                    Original daemon-rendered command exit code.

                Raises
                ------
                RuntimeError
                    If the daemon becomes unavailable during measurement.
                """
                routed = route_cli_read(
                    root,
                    f"cli.{name}",
                    warm_arguments[name],
                    enabled=True,
                )
                if routed.mode != "warm" or routed.exit_code is None:
                    msg = f"warm {name} benchmark failed during measurement"
                    raise RuntimeError(msg)
                return routed.exit_code

            results[name] = {
                "direct": _measure(direct, args.runs),
                "warm": _measure(warm_operation, args.runs),
            }
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = args.output or (
            root / ".artifacts" / "benchmarks" / f"query-daemon-{timestamp}.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "timestamp": timestamp,
            "root": str(root),
            "runs": args.runs,
            "query": args.query,
            "generation": runtime.generation,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "metadata": benchmark_metadata(root),
            "results": results,
        }
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(output)
    finally:
        server.close()
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
