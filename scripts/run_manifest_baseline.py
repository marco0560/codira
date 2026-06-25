#!/usr/bin/env python3
"""Run paired SQLite and DuckDB benchmark baselines."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.scriptlib import (
    epoch_seconds,
    format_duration,
    resolve_codira,
    resolve_python,
    tee_run,
)


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for baseline options.
    """

    parser = argparse.ArgumentParser(
        description="Run SQLite and DuckDB benchmark baselines."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sqlite-only", action="store_true", help="Run only SQLite.")
    mode.add_argument("--duckdb-only", action="store_true", help="Run only DuckDB.")
    parser.add_argument(
        "manifest",
        nargs="?",
        default="benchmarks/bk-cpp.local.json",
        help="Benchmark manifest path.",
    )
    parser.add_argument("extra_args", nargs=argparse.REMAINDER)
    return parser


def run_backend(  # noqa: PLR0913
    backend: str,
    *,
    manifest: Path,
    artifact_root: Path,
    stamp: str,
    python: str,
    codira: str,
    runs: str,
    warmup: str,
    extra_args: list[str],
) -> int:
    """
    Run one backend campaign.

    Parameters
    ----------
    backend : str
        Backend name.
    manifest : pathlib.Path
        Benchmark manifest.
    artifact_root : pathlib.Path
        Artifact root.
    stamp : str
        Campaign stamp.
    python : str
        Python executable.
    codira : str
        Codira executable.
    runs : str
        Hyperfine run count.
    warmup : str
        Hyperfine warmup count.
    extra_args : list[str]
        Extra campaign arguments.

    Returns
    -------
    int
        Campaign exit status.
    """

    run_id = f"{stamp}-bk-cpp-{backend}"
    run_dir = artifact_root / run_id
    log_path = run_dir / "campaign-console.log"
    started_at = epoch_seconds()
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"== {backend} baseline: {run_id} ==")
    env = dict(os.environ)
    env.update(
        {
            "CODIRA_DISABLE_THIRD_PARTY_PLUGINS": os.environ.get(
                "CODIRA_DISABLE_THIRD_PARTY_PLUGINS", "1"
            ),
            "CODIRA_EMBED_BATCH_SIZE": os.environ.get("CODIRA_EMBED_BATCH_SIZE", "32"),
            "CODIRA_TORCH_NUM_THREADS": os.environ.get(
                "CODIRA_TORCH_NUM_THREADS", "10"
            ),
            "CODIRA_TORCH_NUM_INTEROP_THREADS": os.environ.get(
                "CODIRA_TORCH_NUM_INTEROP_THREADS", "1"
            ),
            "CODIRA_INDEX_BACKEND": backend,
        }
    )
    status = tee_run(
        [
            python,
            "scripts/benchmark_campaign.py",
            str(manifest),
            "--artifact-root",
            str(artifact_root),
            "--run-id",
            run_id,
            "--runs",
            runs,
            "--warmup",
            warmup,
            "--codira",
            codira,
            "--python",
            python,
            "--continue-on-error",
            *extra_args,
        ],
        log_path,
        env=env,
    )
    elapsed = epoch_seconds() - started_at
    print(f"== {backend} total: {format_duration(elapsed)} status={status} ==")
    return status


def main(argv: list[str] | None = None) -> int:
    """
    Run requested backend baselines.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments. Defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit status.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    manifest = Path(args.manifest)
    if not manifest.is_file():
        parser.error(f"manifest file does not exist: {manifest}")

    python = resolve_python()
    codira = resolve_codira()
    artifact_root = Path(os.environ.get("ARTIFACT_ROOT", ".artifacts"))
    stamp = os.environ.get("STAMP", datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    runs = os.environ.get("RUNS", "5")
    warmup = os.environ.get("WARMUP", "1")
    status = 0
    sqlite_status: int | str = "skipped"
    duckdb_status: int | str = "skipped"

    if not args.duckdb_only:
        sqlite_status = run_backend(
            "sqlite",
            manifest=manifest,
            artifact_root=artifact_root,
            stamp=stamp,
            python=python,
            codira=codira,
            runs=runs,
            warmup=warmup,
            extra_args=args.extra_args,
        )
        status = sqlite_status if sqlite_status else status
    if not args.sqlite_only:
        duckdb_status = run_backend(
            "duckdb",
            manifest=manifest,
            artifact_root=artifact_root,
            stamp=stamp,
            python=python,
            codira=codira,
            runs=runs,
            warmup=warmup,
            extra_args=args.extra_args,
        )
        if duckdb_status and not status:
            status = duckdb_status

    print(f"SQLite status: {sqlite_status}")
    print(f"DuckDB status: {duckdb_status}")
    print("Artifacts:")
    if not args.duckdb_only:
        print(f"  {artifact_root}/{stamp}-bk-cpp-sqlite")
    if not args.sqlite_only:
        print(f"  {artifact_root}/{stamp}-bk-cpp-duckdb")
    return int(status)


if __name__ == "__main__":
    raise SystemExit(main())
