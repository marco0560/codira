#!/usr/bin/env python3
"""Run Codira benchmark campaigns from a repository manifest.

Responsibilities
----------------
- Read a benchmark manifest describing small, medium, and large repositories.
- Build reproducible Hyperfine and profiler commands for each repository.
- Store command plans and run metadata under ``.artifacts/benchmarks``.

Design principles
-----------------
The campaign runner is developer tooling: it never changes Codira CLI output
contracts and it never treats timing values as pass/fail thresholds.

Architectural role
------------------
This module belongs to the **developer tooling layer** for performance
measurement campaigns.
"""

from __future__ import annotations

import argparse
import json
import pstats
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from benchmark_timing import (  # type: ignore[import-not-found]
    benchmark_metadata,
    utc_run_timestamp,
    write_json_artifact,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_ARTIFACT_ROOT = Path(".artifacts") / "benchmarks"
DEFAULT_RUNS = 5
DEFAULT_WARMUP = 1
DEFAULT_QUERY = "schema migration logic"


@dataclass(frozen=True)
class RepositoryBenchmark:
    """
    Benchmark target loaded from a campaign manifest.

    Parameters
    ----------
    label : str
        Stable repository label used in artifact names.
    category : str
        Repository category such as ``small``, ``medium``, or ``large``.
    path : pathlib.Path
        Repository root to benchmark.
    query : str
        Query used for context retrieval benchmarks.
    modes : tuple[str, ...]
        Requested run modes for the repository.
    """

    label: str
    category: str
    path: Path
    query: str
    modes: tuple[str, ...]


@dataclass(frozen=True)
class CampaignConfig:
    """
    Runtime configuration for one benchmark campaign.

    Parameters
    ----------
    manifest : pathlib.Path
        Manifest file loaded for the campaign.
    artifact_root : pathlib.Path
        Directory under which benchmark artifacts are written.
    run_id : str
        Stable run identifier used for artifact paths.
    codira : str
        Codira executable to benchmark.
    hyperfine : str
        Hyperfine executable to invoke.
    python : str
        Python executable used for profiling and helper scripts.
    runs : int
        Number of measured Hyperfine runs.
    warmup : int
        Number of Hyperfine warmup runs.
    dry_run : bool
        Whether commands should be reported without execution.
    """

    manifest: Path
    artifact_root: Path
    run_id: str
    codira: str
    hyperfine: str
    python: str
    runs: int
    warmup: int
    dry_run: bool


def positive_int(value: str) -> int:
    """
    Parse a positive integer command-line argument.

    Parameters
    ----------
    value : str
        Raw command-line value.

    Returns
    -------
    int
        Parsed positive integer.

    Raises
    ------
    argparse.ArgumentTypeError
        If ``value`` is not greater than zero.
    """
    parsed = int(value)
    if parsed < 1:
        msg = "value must be >= 1"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """
    Build the benchmark campaign CLI parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured campaign parser.
    """
    parser = argparse.ArgumentParser(
        description="Run Codira performance measurement campaigns.",
        epilog=(
            "Examples:\n"
            "  python scripts/benchmark_campaign.py benchmarks.json --dry-run\n"
            "  python scripts/benchmark_campaign.py benchmarks.json --runs 10\n"
            "  python scripts/benchmark_campaign.py benchmarks.json "
            "--artifact-root .artifacts/benchmarks"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("manifest", type=Path, help="Benchmark manifest JSON file.")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT,
        help="Root directory for benchmark artifacts.",
    )
    parser.add_argument(
        "--run-id",
        help="Artifact run identifier. Defaults to the current UTC timestamp.",
    )
    parser.add_argument("--codira", default="codira", help="Codira executable.")
    parser.add_argument(
        "--hyperfine",
        default="hyperfine",
        help="Hyperfine executable.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for profiling helper commands.",
    )
    parser.add_argument(
        "--runs",
        type=positive_int,
        default=DEFAULT_RUNS,
        help="Measured Hyperfine runs per command.",
    )
    parser.add_argument(
        "--warmup",
        type=positive_int,
        default=DEFAULT_WARMUP,
        help="Hyperfine warmup runs per command.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the command plan without executing benchmark commands.",
    )
    return parser


def load_manifest(path: Path) -> tuple[RepositoryBenchmark, ...]:
    """
    Load benchmark repositories from a JSON manifest.

    Parameters
    ----------
    path : pathlib.Path
        Manifest path to read.

    Returns
    -------
    tuple[RepositoryBenchmark, ...]
        Repository benchmark targets in manifest order.

    Raises
    ------
    ValueError
        If the manifest shape is invalid.
    FileNotFoundError
        If a configured repository path does not exist.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    repositories = payload.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        msg = "manifest must contain a non-empty 'repositories' list"
        raise ValueError(msg)

    loaded: list[RepositoryBenchmark] = []
    for index, row in enumerate(repositories):
        if not isinstance(row, dict):
            msg = f"repository entry {index} must be an object"
            raise TypeError(msg)
        label = str(row.get("label", "")).strip()
        category = str(row.get("category", "")).strip()
        raw_path = str(row.get("path", "")).strip()
        if not label or not category or not raw_path:
            msg = f"repository entry {index} requires label, category, and path"
            raise ValueError(msg)
        repo_path = Path(raw_path).expanduser().resolve()
        if not repo_path.exists():
            msg = f"benchmark repository path does not exist: {repo_path}"
            raise FileNotFoundError(msg)
        raw_modes = row.get("modes", ("cold", "warm", "partial_change"))
        if not isinstance(raw_modes, list | tuple) or not raw_modes:
            msg = f"repository entry {index} modes must be a non-empty list"
            raise ValueError(msg)
        loaded.append(
            RepositoryBenchmark(
                label=label,
                category=category,
                path=repo_path,
                query=str(row.get("query", DEFAULT_QUERY)),
                modes=tuple(str(mode) for mode in raw_modes),
            )
        )
    return tuple(loaded)


def _safe_label(value: str) -> str:
    """
    Return a filesystem-safe label fragment.

    Parameters
    ----------
    value : str
        Raw label value.

    Returns
    -------
    str
        Label with non-alphanumeric separators normalized to hyphens.
    """
    chars = [char.lower() if char.isalnum() else "-" for char in value]
    return "-".join(part for part in "".join(chars).split("-") if part)


def run_directory(config: CampaignConfig) -> Path:
    """
    Return the artifact directory for one campaign run.

    Parameters
    ----------
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    pathlib.Path
        Directory dedicated to the campaign run.
    """
    return config.artifact_root / config.run_id


def index_output_dir(repo: RepositoryBenchmark, config: CampaignConfig) -> Path:
    """
    Return the isolated Codira output directory for one benchmark repository.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target.
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    pathlib.Path
        Output directory passed to Codira commands through ``--output-dir``.
    """
    return (
        run_directory(config)
        / "indexes"
        / f"{_safe_label(repo.category)}-{_safe_label(repo.label)}"
    )


def hyperfine_command_strings(
    repo: RepositoryBenchmark,
    *,
    codira: str,
    output_dir: Path,
) -> tuple[str, ...]:
    """
    Return command strings measured through Hyperfine for one repository.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target.
    codira : str
        Codira executable to benchmark.
    output_dir : pathlib.Path
        Codira output directory used for isolated index state.

    Returns
    -------
    tuple[str, ...]
        Shell-quoted command strings accepted by Hyperfine.
    """
    path = str(repo.path)
    output = str(output_dir)
    return (
        shlex.join((codira, "index", "--full", "--path", path, "--output-dir", output)),
        shlex.join((codira, "index", "--path", path, "--output-dir", output)),
        shlex.join(
            (
                codira,
                "ctx",
                "--json",
                repo.query,
                "--path",
                path,
                "--output-dir",
                output,
            )
        ),
    )


def build_hyperfine_argv(
    repo: RepositoryBenchmark,
    config: CampaignConfig,
) -> tuple[str, ...]:
    """
    Build the Hyperfine argv for one repository.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target.
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    tuple[str, ...]
        Complete Hyperfine argv.
    """
    output = (
        run_directory(config)
        / f"{_safe_label(repo.category)}-{_safe_label(repo.label)}-hyperfine.json"
    )
    return (
        config.hyperfine,
        "--warmup",
        str(config.warmup),
        "--runs",
        str(config.runs),
        "--export-json",
        str(output),
        *hyperfine_command_strings(
            repo,
            codira=config.codira,
            output_dir=index_output_dir(repo, config),
        ),
    )


def build_phase_benchmark_argv(
    repo: RepositoryBenchmark,
    config: CampaignConfig,
) -> tuple[str, ...]:
    """
    Build the instrumented phase benchmark argv for one repository.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target.
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    tuple[str, ...]
        Phase benchmark argv.
    """
    output = (
        run_directory(config)
        / f"{_safe_label(repo.category)}-{_safe_label(repo.label)}-index-phases.json"
    )
    return (
        config.python,
        str(Path(__file__).with_name("benchmark_index.py")),
        str(repo.path),
        "--full",
        "--output",
        str(output),
    )


def _resolved_codira_script(codira: str) -> str:
    """
    Resolve the Codira executable path for cProfile script execution.

    Parameters
    ----------
    codira : str
        Codira executable name or path.

    Returns
    -------
    str
        Executable filesystem path when resolvable, otherwise ``codira``.
    """
    if "/" in codira:
        return codira
    return shutil.which(codira) or codira


def build_profile_argvs(
    repo: RepositoryBenchmark,
    config: CampaignConfig,
) -> tuple[tuple[str, ...], ...]:
    """
    Build cProfile command vectors for index and context retrieval.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target.
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        cProfile command vectors.
    """
    base = run_directory(config) / "profiles"
    prefix = f"{_safe_label(repo.category)}-{_safe_label(repo.label)}"
    codira_script = _resolved_codira_script(config.codira)
    output_dir = str(index_output_dir(repo, config))
    return (
        (
            config.python,
            "-m",
            "cProfile",
            "-o",
            str(base / f"{prefix}-index.prof"),
            codira_script,
            "index",
            "--full",
            "--path",
            str(repo.path),
            "--output-dir",
            output_dir,
        ),
        (
            config.python,
            "-m",
            "cProfile",
            "-o",
            str(base / f"{prefix}-ctx.prof"),
            codira_script,
            "ctx",
            "--json",
            repo.query,
            "--path",
            str(repo.path),
            "--output-dir",
            output_dir,
        ),
    )


def build_pyinstrument_argvs(
    repo: RepositoryBenchmark,
    config: CampaignConfig,
) -> tuple[tuple[str, ...], ...]:
    """
    Build optional Pyinstrument command vectors for one repository.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target.
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Pyinstrument command vectors, or an empty tuple when unavailable.
    """
    if shutil.which("pyinstrument") is None:
        return ()
    base = run_directory(config) / "profiles"
    prefix = f"{_safe_label(repo.category)}-{_safe_label(repo.label)}"
    codira_script = _resolved_codira_script(config.codira)
    output_dir = str(index_output_dir(repo, config))
    return (
        (
            "pyinstrument",
            "-o",
            str(base / f"{prefix}-index-pyinstrument.html"),
            codira_script,
            "index",
            "--full",
            "--path",
            str(repo.path),
            "--output-dir",
            output_dir,
        ),
        (
            "pyinstrument",
            "-o",
            str(base / f"{prefix}-ctx-pyinstrument.html"),
            codira_script,
            "ctx",
            "--json",
            repo.query,
            "--path",
            str(repo.path),
            "--output-dir",
            output_dir,
        ),
    )


def command_plan(
    repositories: Iterable[RepositoryBenchmark],
    config: CampaignConfig,
) -> list[dict[str, object]]:
    """
    Build the complete command plan for a campaign.

    Parameters
    ----------
    repositories : collections.abc.Iterable[RepositoryBenchmark]
        Repository benchmark targets.
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    list[dict[str, object]]
        JSON-serializable command plan rows.
    """
    plan: list[dict[str, object]] = []
    for repo in repositories:
        commands = [
            build_phase_benchmark_argv(repo, config),
            build_hyperfine_argv(repo, config),
            *build_profile_argvs(repo, config),
            *build_pyinstrument_argvs(repo, config),
        ]
        plan.append(
            {
                "label": repo.label,
                "category": repo.category,
                "path": str(repo.path),
                "query": repo.query,
                "modes": list(repo.modes),
                "commands": [list(command) for command in commands],
                "display_commands": [shlex.join(command) for command in commands],
            }
        )
    return plan


def summarize_profile(profile: Path, *, limit: int = 20) -> list[dict[str, object]]:
    """
    Summarize the slowest cumulative functions in a cProfile artifact.

    Parameters
    ----------
    profile : pathlib.Path
        Profile artifact to read.
    limit : int, optional
        Maximum number of rows to return.

    Returns
    -------
    list[dict[str, object]]
        Summary rows sorted by cumulative time.
    """
    stats = pstats.Stats(str(profile))
    raw_stats = cast(
        "dict[tuple[str, int, str], tuple[int, int, float, float, object]]",
        stats.stats,  # type: ignore[attr-defined]
    )
    rows = sorted(
        raw_stats.items(),
        key=lambda item: item[1][3],
        reverse=True,
    )[:limit]
    return [
        {
            "file": file_name,
            "line": line,
            "function": function,
            "calls": values[0],
            "primitive_calls": values[1],
            "total_seconds": round(values[2], 6),
            "cumulative_seconds": round(values[3], 6),
        }
        for (file_name, line, function), values in rows
    ]


def _run_command(command: tuple[str, ...]) -> int:
    """
    Execute one benchmark command.

    Parameters
    ----------
    command : tuple[str, ...]
        Command vector to execute.

    Returns
    -------
    int
        Process return code.
    """
    return subprocess.run(command, check=False).returncode


def main() -> int:
    """
    Run or dry-run one benchmark campaign.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero when the campaign plan is generated and all executed commands pass.
    """
    args = build_parser().parse_args()
    run_id = args.run_id or utc_run_timestamp().replace(":", "").replace("-", "")
    config = CampaignConfig(
        manifest=Path(args.manifest).resolve(),
        artifact_root=Path(args.artifact_root),
        run_id=run_id,
        codira=str(args.codira),
        hyperfine=str(args.hyperfine),
        python=str(args.python),
        runs=int(args.runs),
        warmup=int(args.warmup),
        dry_run=bool(args.dry_run),
    )
    repositories = load_manifest(config.manifest)
    plan = command_plan(repositories, config)
    payload = {
        "metadata": benchmark_metadata(
            Path.cwd(),
            manifest=config.manifest,
            hyperfine=config.hyperfine,
        ),
        "run_id": config.run_id,
        "dry_run": config.dry_run,
        "repositories": plan,
    }
    plan_path = run_directory(config) / "campaign-plan.json"
    write_json_artifact(plan_path, payload)

    if config.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    (run_directory(config) / "profiles").mkdir(parents=True, exist_ok=True)
    for row in plan:
        commands = row["commands"]
        if not isinstance(commands, list):
            msg = "campaign command rows must contain a command list"
            raise TypeError(msg)
        for command in commands:
            if not isinstance(command, list):
                msg = "campaign command entries must be argument lists"
                raise TypeError(msg)
            return_code = _run_command(tuple(str(part) for part in command))
            if return_code != 0:
                return return_code

    profile_summaries = {
        str(profile): summarize_profile(profile)
        for profile in sorted((run_directory(config) / "profiles").glob("*.prof"))
    }
    write_json_artifact(
        run_directory(config) / "profile-summary.json",
        {"metadata": payload["metadata"], "profiles": profile_summaries},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
