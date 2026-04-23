"""Build and run release-oriented Hyperfine benchmarks for codira.

Responsibilities
----------------
- Define the deterministic Hyperfine command set used before releases.
- Cover the release gate operations: index, ctx, and audit.
- Emit Hyperfine JSON results under the repository artifact directory.

Design principles
-----------------
The script keeps benchmark command construction reviewable and testable while
leaving actual timing measurement to Hyperfine.

Architectural role
------------------
This module belongs to the **developer tooling layer** and provides a
release-quality performance guardrail.
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_QUERY = "schema migration logic"
DEFAULT_OUTPUT = Path(".artifacts") / "benchmarks" / "release-hyperfine.json"


def _path_text(path: Path) -> str:
    """
    Render a path with deterministic forward-slash separators.

    Parameters
    ----------
    path : pathlib.Path
        Path to render for command arguments.

    Returns
    -------
    str
        POSIX-style path text.
    """
    text = str(path)
    if text.startswith("\\") and not text.startswith("\\\\"):
        return path.as_posix()
    return text


@dataclass(frozen=True)
class BenchmarkConfig:
    """
    Hyperfine benchmark configuration.

    Parameters
    ----------
    hyperfine : str
        Hyperfine executable to invoke.
    codira : str
        Codira executable to benchmark.
    output : pathlib.Path
        JSON result path passed to Hyperfine.
    runs : int
        Number of measured Hyperfine runs per command.
    warmup : int
        Number of warmup runs per command.
    query : str
        Query text used for the `codira ctx` benchmark.
    """

    hyperfine: str
    codira: str
    output: Path
    runs: int
    warmup: int
    query: str


def positive_int(value: str) -> int:
    """
    Parse one positive integer command-line value.

    Parameters
    ----------
    value : str
        Raw argument value.

    Returns
    -------
    int
        Positive integer value.

    Raises
    ------
    argparse.ArgumentTypeError
        If the value is not a positive integer.
    """
    parsed = int(value)
    if parsed < 1:
        msg = "value must be >= 1"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def benchmark_command_strings(*, codira: str, query: str) -> tuple[str, ...]:
    """
    Return the Codira commands measured by the release benchmark.

    Parameters
    ----------
    codira : str
        Codira executable to benchmark.
    query : str
        Query text used for the context benchmark.

    Returns
    -------
    tuple[str, ...]
        Shell-quoted command strings passed to Hyperfine.
    """
    return (
        shlex.join((codira, "index", "--full")),
        shlex.join((codira, "ctx", "--json", query)),
        shlex.join((codira, "audit", "--json")),
    )


def build_hyperfine_argv(config: BenchmarkConfig) -> tuple[str, ...]:
    """
    Build the Hyperfine invocation for release benchmarking.

    Parameters
    ----------
    config : BenchmarkConfig
        Benchmark configuration.

    Returns
    -------
    tuple[str, ...]
        Complete Hyperfine argv.
    """
    return (
        config.hyperfine,
        "--warmup",
        str(config.warmup),
        "--runs",
        str(config.runs),
        "--export-json",
        _path_text(config.output),
        *benchmark_command_strings(codira=config.codira, query=config.query),
    )


def resolve_output_path(root: Path, output: Path) -> Path:
    """
    Resolve the Hyperfine JSON output path.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative output paths.
    output : pathlib.Path
        Configured output path.

    Returns
    -------
    pathlib.Path
        Absolute output path.
    """
    if output.is_absolute():
        return output
    return root / output


def executable_available(executable: str) -> bool:
    """
    Return whether an executable can be invoked.

    Parameters
    ----------
    executable : str
        Executable name or filesystem path.

    Returns
    -------
    bool
        ``True`` when the executable is present.
    """
    if "/" in executable:
        return Path(executable).exists()
    return shutil.which(executable) is not None


def build_parser() -> argparse.ArgumentParser:
    """
    Build the release benchmark CLI parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser for one benchmark invocation.
    """
    parser = argparse.ArgumentParser(
        description="Run release-oriented Hyperfine benchmarks for codira.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root to benchmark. Defaults to the current directory.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Hyperfine JSON output path. Relative paths are rooted at --root.",
    )
    parser.add_argument(
        "--runs",
        type=positive_int,
        default=5,
        help="Measured Hyperfine runs per command.",
    )
    parser.add_argument(
        "--warmup",
        type=positive_int,
        default=1,
        help="Warmup runs per command.",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help="Query text used for the codira ctx benchmark.",
    )
    parser.add_argument(
        "--codira",
        default="codira",
        help="Codira executable to benchmark.",
    )
    parser.add_argument(
        "--hyperfine",
        default="hyperfine",
        help="Hyperfine executable to invoke.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Hyperfine invocation without executing it.",
    )
    return parser


def main() -> int:
    """
    Run or print the release benchmark command.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit code.
    """
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    output = resolve_output_path(root, Path(args.output))
    config = BenchmarkConfig(
        hyperfine=str(args.hyperfine),
        codira=str(args.codira),
        output=output,
        runs=int(args.runs),
        warmup=int(args.warmup),
        query=str(args.query),
    )
    argv = build_hyperfine_argv(config)

    if args.dry_run:
        print(shlex.join(argv))
        return 0

    if not executable_available(config.hyperfine):
        print(
            f"ERROR: Hyperfine executable not found: {config.hyperfine}",
            file=sys.stderr,
        )
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(argv, cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
