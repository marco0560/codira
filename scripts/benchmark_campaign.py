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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from benchmark_timing import (  # type: ignore[import-not-found]
    benchmark_metadata,
    utc_run_timestamp,
    write_json_artifact,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

DEFAULT_ARTIFACT_ROOT = Path(".artifacts") / "benchmarks"
DEFAULT_RUNS = 5
DEFAULT_WARMUP = 1
DEFAULT_QUERY = "schema migration logic"
PATH_AWARE_SUBCOMMANDS = frozenset(
    {"index", "cov", "sym", "symlist", "emb", "calls", "refs", "audit", "ctx"}
)
ADAPTIVE_SYMBOL_SUBCOMMANDS = frozenset({"sym", "calls", "refs"})
ADAPTIVE_TEXT_SUBCOMMANDS = frozenset({"emb", "ctx"})
DISCOVERY_SYMBOL_LIMIT = 100
DISCOVERY_MAX_SYMBOL_CANDIDATES = 12
DISCOVERY_MAX_QUERY_CANDIDATES = 8
OPTION_FLAGS_WITH_VALUE = frozenset(
    {"--limit", "--prefix", "--module", "--path", "--output-dir", "--max-depth"}
)
MANIFEST_BENCHMARK_SUBCOMMANDS = frozenset(
    {
        "help",
        "index",
        "cov",
        "sym",
        "symlist",
        "emb",
        "calls",
        "refs",
        "audit",
        "ctx",
        "plugins",
        "caps",
    }
)


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
    commands : tuple[tuple[str, ...], ...]
        Additional Codira command vectors benchmarked through Hyperfine.
    """

    label: str
    category: str
    path: Path
    query: str
    modes: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]


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


@dataclass(frozen=True)
class SymbolCandidate:
    """
    Symbol candidate discovered during adaptive command selection.

    Parameters
    ----------
    name : str
        Symbol name used for exact and graph-oriented benchmark commands.
    prefix : str
        Repo-root-relative file prefix containing the symbol.
    score : int
        Discovery score derived from symbol inventory graph metrics.
    module : str
        Dotted module owning the symbol.
    """

    name: str
    prefix: str
    score: int
    module: str


@dataclass(frozen=True)
class ResolvedRepositoryBenchmark:
    """
    Repository benchmark with adaptive command selections applied.

    Parameters
    ----------
    label : str
        Stable repository label used in artifact names.
    category : str
        Repository category such as ``small``, ``medium``, or ``large``.
    path : pathlib.Path
        Repository root to benchmark.
    query : str
        Resolved query used for context retrieval benchmarks.
    requested_query : str
        Query requested in the manifest before adaptive refinement.
    modes : tuple[str, ...]
        Requested run modes for the repository.
    commands : tuple[tuple[str, ...], ...]
        Resolved additional Codira command vectors benchmarked through
        Hyperfine.
    requested_commands : tuple[tuple[str, ...], ...]
        Manifest command vectors before adaptive refinement.
    skipped_commands : tuple[tuple[str, ...], ...]
        Requested commands skipped because no meaningful candidate was found.
    selection : dict[str, object]
        JSON-serializable adaptive selection provenance.
    """

    label: str
    category: str
    path: Path
    query: str
    requested_query: str
    modes: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    requested_commands: tuple[tuple[str, ...], ...]
    skipped_commands: tuple[tuple[str, ...], ...]
    selection: dict[str, object]


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
        If the manifest file or a configured repository path does not exist.
    """
    if not path.exists():
        msg = f"manifest file not found: {path}"
        raise FileNotFoundError(msg)
    payload = json.loads(path.read_text(encoding="utf-8"))
    repositories = payload.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        msg = "manifest must contain a non-empty 'repositories' list"
        raise ValueError(msg)

    loaded: list[RepositoryBenchmark] = []
    labels: set[str] = set()
    artifact_keys: set[tuple[str, str]] = set()
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
        if label in labels:
            msg = f"repository entry {index} reuses duplicate label: {label}"
            raise ValueError(msg)
        labels.add(label)
        artifact_key = (_safe_label(category), _safe_label(label))
        if artifact_key in artifact_keys:
            msg = (
                f"repository entry {index} reuses duplicate artifact identity: "
                f"{category}/{label}"
            )
            raise ValueError(msg)
        artifact_keys.add(artifact_key)
        repo_path = Path(raw_path).expanduser().resolve()
        if not repo_path.exists():
            msg = f"benchmark repository path does not exist: {repo_path}"
            raise FileNotFoundError(msg)
        raw_modes = row.get("modes", ("cold", "warm", "partial_change"))
        if not isinstance(raw_modes, list | tuple) or not raw_modes:
            msg = f"repository entry {index} modes must be a non-empty list"
            raise ValueError(msg)
        commands = _load_manifest_commands(row.get("commands", ()), index=index)
        loaded.append(
            RepositoryBenchmark(
                label=label,
                category=category,
                path=repo_path,
                query=str(row.get("query", DEFAULT_QUERY)),
                modes=tuple(str(mode) for mode in raw_modes),
                commands=commands,
            )
        )
    return tuple(loaded)


def _load_manifest_commands(
    raw_commands: object,
    *,
    index: int,
) -> tuple[tuple[str, ...], ...]:
    """
    Load validated manifest commands for one repository entry.

    Parameters
    ----------
    raw_commands : object
        Raw manifest value stored under ``commands``.
    index : int
        Repository entry index used in validation messages.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Validated command token vectors.

    Raises
    ------
    TypeError
        If the ``commands`` container is not a list-like value.
    ValueError
        If a command entry is empty, has empty tokens, or names an unsupported
        subcommand.
    """
    if not isinstance(raw_commands, list | tuple):
        msg = f"repository entry {index} commands must be a list"
        raise TypeError(msg)
    commands: list[tuple[str, ...]] = []
    for command_index, raw_command in enumerate(raw_commands):
        if not isinstance(raw_command, list | tuple) or not raw_command:
            msg = (
                f"repository entry {index} command {command_index} must be a "
                "non-empty list"
            )
            raise ValueError(msg)
        argv = tuple(str(part).strip() for part in raw_command)
        if any(not part for part in argv):
            msg = (
                f"repository entry {index} command {command_index} contains an "
                "empty token"
            )
            raise ValueError(msg)
        if argv[0] not in MANIFEST_BENCHMARK_SUBCOMMANDS:
            msg = (
                f"repository entry {index} command {command_index} uses "
                f"unsupported subcommand: {argv[0]}"
            )
            raise ValueError(msg)
        commands.append(argv)
    return tuple(commands)


def _metric_total(item: dict[str, object], key: str) -> int:
    """
    Extract one graph metric total from a symbol inventory item.

    Parameters
    ----------
    item : dict[str, object]
        Parsed symbol inventory row.
    key : str
        Metric field name.

    Returns
    -------
    int
        Metric total, or zero when the field is absent.
    """
    metric = item.get(key)
    if not isinstance(metric, dict):
        return 0
    total = metric.get("total", 0)
    return total if isinstance(total, int) else 0


def _score_inventory_item(item: dict[str, object]) -> int:
    """
    Score one symbol inventory item by graph connectivity.

    Parameters
    ----------
    item : dict[str, object]
        Parsed symbol inventory row.

    Returns
    -------
    int
        Connectivity score used during adaptive selection.
    """
    return (
        _metric_total(item, "calls_out") * 2
        + _metric_total(item, "calls_in") * 2
        + _metric_total(item, "refs_out")
        + _metric_total(item, "refs_in") * 2
    )


def _repo_relative_prefix(repo: Path, file_path: str) -> str | None:
    """
    Convert a symbol inventory file path into a repo-root-relative prefix.

    Parameters
    ----------
    repo : pathlib.Path
        Target repository root.
    file_path : str
        File path emitted by ``codira symlist --json``.

    Returns
    -------
    str | None
        Repo-root-relative path prefix, or ``None`` when the file is outside
        the repository root.
    """
    repo_root = repo.resolve()
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        return candidate.resolve(strict=False).relative_to(repo_root).as_posix()
    except ValueError:
        return None


def _json_command_result(
    command: Sequence[str],
) -> tuple[int, dict[str, object] | None, str]:
    """
    Execute one command expected to emit a JSON payload.

    Parameters
    ----------
    command : collections.abc.Sequence[str]
        Command vector to execute.

    Returns
    -------
    tuple[int, dict[str, object] | None, str]
        Return code, parsed JSON payload when available, and raw standard
        output text.
    """
    process = subprocess.run(
        tuple(command),
        text=True,
        capture_output=True,
        check=False,
    )
    payload: dict[str, object] | None = None
    if process.stdout.strip():
        try:
            raw_payload = json.loads(process.stdout)
        except json.JSONDecodeError:
            raw_payload = None
        if isinstance(raw_payload, dict):
            payload = cast("dict[str, object]", raw_payload)
    return process.returncode, payload, process.stdout


def _primary_target_index(command: Sequence[str]) -> int | None:
    """
    Locate the required positional target token in one manifest command.

    Parameters
    ----------
    command : collections.abc.Sequence[str]
        Manifest command tokens excluding the Codira executable.

    Returns
    -------
    int | None
        Index of the primary name or query token, or ``None`` when the
        subcommand does not carry one.
    """
    if not command or command[0] not in ADAPTIVE_SYMBOL_SUBCOMMANDS.union(
        ADAPTIVE_TEXT_SUBCOMMANDS
    ):
        return None
    skip_next = False
    for index, token in enumerate(command[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if token in OPTION_FLAGS_WITH_VALUE:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        return index
    return None


def _with_target(command: Sequence[str], target: str) -> tuple[str, ...] | None:
    """
    Replace the primary target token in one benchmark command.

    Parameters
    ----------
    command : collections.abc.Sequence[str]
        Manifest command tokens excluding the Codira executable.
    target : str
        Replacement symbol name or query text.

    Returns
    -------
    tuple[str, ...] | None
        Updated command tokens, or ``None`` when the command has no positional
        target slot.
    """
    index = _primary_target_index(command)
    if index is None:
        return None
    parts = list(command)
    parts[index] = target
    return tuple(parts)


def _json_list_count(payload: dict[str, object] | None, key: str) -> int:
    """
    Count rows in one JSON payload list field.

    Parameters
    ----------
    payload : dict[str, object] | None
        Parsed JSON payload.
    key : str
        List field name.

    Returns
    -------
    int
        Number of list rows, or zero when unavailable.
    """
    if payload is None:
        return 0
    rows = payload.get(key)
    return len(rows) if isinstance(rows, list) else 0


def _score_text_query_result(
    *,
    subcommand: str,
    payload: dict[str, object] | None,
) -> int:
    """
    Score one text-query payload for adaptive query selection.

    Parameters
    ----------
    subcommand : str
        Text-query subcommand family such as ``emb`` or ``ctx``.
    payload : dict[str, object] | None
        Parsed JSON payload.

    Returns
    -------
    int
        Ranked significance score. Zero means the payload is not benchmarkable.
    """
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return 0
    if subcommand == "emb":
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return 0
        score_total = 0
        for row in results:
            if not isinstance(row, dict):
                continue
            value = row.get("score")
            if isinstance(value, int | float):
                score_total += int(float(value) * 1000)
        return len(results) * 1000 + score_total
    if subcommand == "ctx":
        return (
            _json_list_count(payload, "top_matches") * 1000
            + _json_list_count(payload, "context") * 100
            + _json_list_count(payload, "references") * 25
            + _json_list_count(payload, "module_expansion") * 10
        )
    return 0


def _score_symbol_command_result(
    *,
    payload: dict[str, object] | None,
    candidate: SymbolCandidate,
) -> int:
    """
    Score one exact or graph command payload for adaptive symbol selection.

    Parameters
    ----------
    payload : dict[str, object] | None
        Parsed JSON payload.
    candidate : SymbolCandidate
        Candidate symbol used to produce the payload.

    Returns
    -------
    int
        Ranked significance score. Zero means the payload is not benchmarkable.
    """
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return 0
    result_count = _json_list_count(payload, "results")
    if result_count < 1:
        return 0
    return result_count * 1000 + candidate.score


def _discover_symbol_candidates(
    *,
    repo: RepositoryBenchmark,
    config: CampaignConfig,
    output_dir: Path,
) -> tuple[SymbolCandidate, ...]:
    """
    Discover high-signal symbol candidates for one repository.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target.
    config : CampaignConfig
        Campaign configuration.
    output_dir : pathlib.Path
        Temporary Codira output directory used for discovery.

    Returns
    -------
    tuple[SymbolCandidate, ...]
        Ranked symbol candidates in descending score order.
    """
    command = (
        config.codira,
        "symlist",
        "--json",
        "--limit",
        str(DISCOVERY_SYMBOL_LIMIT),
        "--path",
        str(repo.path),
        "--output-dir",
        str(output_dir),
    )
    _, payload, _ = _json_command_result(command)
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return ()
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        return ()
    candidates: list[SymbolCandidate] = []
    seen: set[tuple[str, str]] = set()
    for item in symbols:
        if not isinstance(item, dict) or item.get("type") not in {"function", "method"}:
            continue
        name = item.get("name")
        file_path = item.get("file")
        module = item.get("module")
        if not isinstance(name, str) or not isinstance(file_path, str):
            continue
        prefix = _repo_relative_prefix(repo.path, file_path)
        if prefix is None:
            continue
        score = _score_inventory_item(cast("dict[str, object]", item))
        if score < 1:
            continue
        key = (name, prefix)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            SymbolCandidate(
                name=name,
                prefix=prefix,
                score=score,
                module=str(module) if isinstance(module, str) else "",
            )
        )
    ranked = sorted(
        candidates,
        key=lambda item: (-item.score, item.name, item.prefix),
    )
    return tuple(ranked[:DISCOVERY_MAX_SYMBOL_CANDIDATES])


def _candidate_query_texts(
    repo: RepositoryBenchmark,
    candidates: Sequence[SymbolCandidate],
) -> tuple[str, ...]:
    """
    Build ranked candidate query texts for semantic benchmark commands.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target.
    candidates : collections.abc.Sequence[SymbolCandidate]
        Ranked symbol candidates discovered for the repository.

    Returns
    -------
    tuple[str, ...]
        Candidate text queries in deterministic order.
    """
    texts: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        normalized = text.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        texts.append(normalized)

    add(repo.query)
    for candidate in candidates:
        add(candidate.name)
        add(candidate.name.replace("_", " "))
        if candidate.module:
            add(candidate.module.rsplit(".", maxsplit=1)[-1].replace("_", " "))
    return tuple(texts[:DISCOVERY_MAX_QUERY_CANDIDATES])


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


def selection_directory(config: CampaignConfig) -> Path:
    """
    Return the selector-provenance directory for one campaign run.

    Parameters
    ----------
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    pathlib.Path
        Directory storing resolved benchmark selections and skip reasons.
    """
    return run_directory(config) / "selection"


def _expand_manifest_token(
    token: str,
    *,
    repo_path: Path,
    query: str,
    output_dir: Path,
) -> str:
    """
    Expand known benchmark manifest placeholders in one command token.

    Parameters
    ----------
    token : str
        Raw manifest token.
    repo_path : pathlib.Path
        Repository root used to expand ``{path}``.
    query : str
        Query text used to expand ``{query}``.
    output_dir : pathlib.Path
        Output directory used to expand ``{output_dir}``.

    Returns
    -------
    str
        Token with supported placeholders substituted.
    """
    expanded = token.replace("{path}", str(repo_path))
    expanded = expanded.replace("{output_dir}", str(output_dir))
    return expanded.replace("{query}", query)


def _manifest_command_argv(
    command: Sequence[str],
    *,
    repo_path: Path,
    query: str,
    config: CampaignConfig,
    output_dir: Path,
) -> tuple[str, ...]:
    """
    Build one Codira argv from a manifest command entry.

    Parameters
    ----------
    command : collections.abc.Sequence[str]
        Manifest command tokens excluding the Codira executable.
    repo_path : pathlib.Path
        Repository root to benchmark.
    query : str
        Query text used to expand manifest placeholders.
    config : CampaignConfig
        Campaign configuration.
    output_dir : pathlib.Path
        Codira output directory for the generated command.

    Returns
    -------
    tuple[str, ...]
        Complete Codira argv with placeholder expansion.
    """
    subcommand = str(command[0])
    expanded = tuple(
        _expand_manifest_token(
            str(token),
            repo_path=repo_path,
            query=query,
            output_dir=output_dir,
        )
        for token in command
    )
    argv = [config.codira, *expanded]
    if subcommand in PATH_AWARE_SUBCOMMANDS and "--path" not in expanded:
        argv.extend(("--path", str(repo_path)))
    if subcommand in PATH_AWARE_SUBCOMMANDS and "--output-dir" not in expanded:
        argv.extend(("--output-dir", str(output_dir)))
    return tuple(argv)


def _resolve_symbol_command(
    command: Sequence[str],
    *,
    repo: RepositoryBenchmark,
    config: CampaignConfig,
    output_dir: Path,
    candidates: Sequence[SymbolCandidate],
) -> tuple[tuple[str, ...] | None, list[dict[str, object]]]:
    """
    Resolve one symbol-dependent benchmark command to a meaningful candidate.

    Parameters
    ----------
    command : collections.abc.Sequence[str]
        Manifest command tokens excluding the Codira executable.
    repo : RepositoryBenchmark
        Repository benchmark target.
    config : CampaignConfig
        Campaign configuration.
    output_dir : pathlib.Path
        Temporary discovery output directory.
    candidates : collections.abc.Sequence[SymbolCandidate]
        Ranked symbol candidates discovered for the repository.

    Returns
    -------
    tuple[tuple[str, ...] | None, list[dict[str, object]]]
        Resolved command tokens when a meaningful candidate exists, plus trial
        metadata persisted for inspection.
    """
    requested_target_index = _primary_target_index(command)
    trial_candidates: list[SymbolCandidate] = list(candidates)
    if requested_target_index is not None:
        requested_target = str(command[requested_target_index])
        trial_candidates = sorted(
            candidates,
            key=lambda candidate: (
                candidate.name != requested_target,
                -candidate.score,
                candidate.name,
                candidate.prefix,
            ),
        )
    best_command: tuple[str, ...] | None = None
    best_score = 0
    trials: list[dict[str, object]] = []
    for candidate in trial_candidates:
        rewritten = _with_target(command, candidate.name)
        if rewritten is None:
            break
        argv = _manifest_command_argv(
            rewritten,
            repo_path=repo.path,
            query=repo.query,
            config=config,
            output_dir=output_dir,
        )
        return_code, payload, _ = _json_command_result(argv)
        score = _score_symbol_command_result(payload=payload, candidate=candidate)
        trials.append(
            {
                "candidate": candidate.name,
                "prefix": candidate.prefix,
                "connectivity_score": candidate.score,
                "return_code": return_code,
                "score": score,
                "status": payload.get("status") if isinstance(payload, dict) else None,
                "result_count": _json_list_count(payload, "results"),
                "command": list(argv),
            }
        )
        if score > best_score:
            best_score = score
            best_command = rewritten
    return best_command, trials


def _resolve_text_query(
    *,
    repo: RepositoryBenchmark,
    config: CampaignConfig,
    output_dir: Path,
    candidates: Sequence[SymbolCandidate],
) -> tuple[str, list[dict[str, object]]]:
    """
    Resolve a meaningful semantic query for one repository.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target.
    config : CampaignConfig
        Campaign configuration.
    output_dir : pathlib.Path
        Temporary discovery output directory.
    candidates : collections.abc.Sequence[SymbolCandidate]
        Ranked symbol candidates discovered for the repository.

    Returns
    -------
    tuple[str, list[dict[str, object]]]
        Resolved query text and persisted trial metadata.
    """
    best_query = repo.query
    best_score = 0
    trials: list[dict[str, object]] = []
    for query_text in _candidate_query_texts(repo, candidates):
        argv = (
            config.codira,
            "emb",
            query_text,
            "--json",
            "--limit",
            "5",
            "--path",
            str(repo.path),
            "--output-dir",
            str(output_dir),
        )
        return_code, payload, _ = _json_command_result(argv)
        score = _score_text_query_result(subcommand="emb", payload=payload)
        trials.append(
            {
                "query": query_text,
                "return_code": return_code,
                "score": score,
                "status": payload.get("status") if isinstance(payload, dict) else None,
                "result_count": _json_list_count(payload, "results"),
                "command": list(argv),
            }
        )
        if score > best_score:
            best_score = score
            best_query = query_text
    return best_query, trials


def _resolve_inventory_command(
    command: Sequence[str],
    *,
    repo: RepositoryBenchmark,
    config: CampaignConfig,
    output_dir: Path,
    query: str,
) -> tuple[tuple[str, ...] | None, dict[str, object]]:
    """
    Resolve one inventory benchmark command after a validation trial.

    Parameters
    ----------
    command : collections.abc.Sequence[str]
        Manifest command tokens excluding the Codira executable.
    repo : RepositoryBenchmark
        Repository benchmark target.
    config : CampaignConfig
        Campaign configuration.
    output_dir : pathlib.Path
        Temporary discovery output directory.
    query : str
        Resolved query text used for placeholder expansion.

    Returns
    -------
    tuple[tuple[str, ...] | None, dict[str, object]]
        Resolved command tokens when the command yields significant output, plus
        persisted trial metadata.
    """
    argv = _manifest_command_argv(
        command,
        repo_path=repo.path,
        query=query,
        config=config,
        output_dir=output_dir,
    )
    return_code, payload, _ = _json_command_result(argv)
    symbol_count = _json_list_count(payload, "symbols")
    score = (
        symbol_count * 1000
        if isinstance(payload, dict) and payload.get("status") == "ok"
        else 0
    )
    metadata = {
        "return_code": return_code,
        "score": score,
        "status": payload.get("status") if isinstance(payload, dict) else None,
        "symbol_count": symbol_count,
        "command": list(argv),
    }
    return (tuple(command) if score > 0 else None), metadata


def resolve_repository_benchmark(
    repo: RepositoryBenchmark,
    config: CampaignConfig,
) -> ResolvedRepositoryBenchmark:
    """
    Resolve adaptive benchmark commands and query text for one repository.

    Parameters
    ----------
    repo : RepositoryBenchmark
        Repository benchmark target loaded from the manifest.
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    ResolvedRepositoryBenchmark
        Repository benchmark with adaptive selections applied.
    """
    selection: dict[str, object] = {
        "requested_query": repo.query,
        "requested_commands": [list(command) for command in repo.commands],
        "symbol_candidates": [],
        "query_trials": [],
        "command_trials": [],
    }
    with tempfile.TemporaryDirectory(
        prefix=f"codira-benchmark-{_safe_label(repo.category)}-{_safe_label(repo.label)}-"
    ) as temporary_root:
        discovery_output_dir = Path(temporary_root) / "codira-output"
        discovery_index = (
            config.codira,
            "index",
            "--path",
            str(repo.path),
            "--output-dir",
            str(discovery_output_dir),
        )
        print(f"--- {repo.label.upper()} ---", flush=True)
        return_code = subprocess.run(discovery_index, check=False).returncode
        selection["discovery_index"] = {
            "command": list(discovery_index),
            "return_code": return_code,
            "output_dir": str(discovery_output_dir),
        }
        candidates = _discover_symbol_candidates(
            repo=repo,
            config=config,
            output_dir=discovery_output_dir,
        )
        selection["symbol_candidates"] = [
            {
                "name": candidate.name,
                "prefix": candidate.prefix,
                "score": candidate.score,
                "module": candidate.module,
            }
            for candidate in candidates
        ]
        resolved_query, query_trials = _resolve_text_query(
            repo=repo,
            config=config,
            output_dir=discovery_output_dir,
            candidates=candidates,
        )
        selection["query_trials"] = query_trials

        resolved_commands: list[tuple[str, ...]] = []
        skipped_commands: list[tuple[str, ...]] = []
        command_trials: list[dict[str, object]] = []
        for command in repo.commands:
            subcommand = command[0]
            if subcommand in ADAPTIVE_SYMBOL_SUBCOMMANDS:
                resolved, trials = _resolve_symbol_command(
                    command,
                    repo=repo,
                    config=config,
                    output_dir=discovery_output_dir,
                    candidates=candidates,
                )
                command_trials.append(
                    {
                        "requested": list(command),
                        "resolved": list(resolved) if resolved is not None else None,
                        "trials": trials,
                    }
                )
                if resolved is None:
                    skipped_commands.append(tuple(command))
                else:
                    resolved_commands.append(resolved)
                continue
            if subcommand in ADAPTIVE_TEXT_SUBCOMMANDS:
                resolved = _with_target(command, resolved_query)
                if resolved is None:
                    skipped_commands.append(tuple(command))
                    command_trials.append(
                        {
                            "requested": list(command),
                            "resolved": None,
                            "reason": "missing positional query slot",
                        }
                    )
                else:
                    resolved_commands.append(resolved)
                    command_trials.append(
                        {
                            "requested": list(command),
                            "resolved": list(resolved),
                            "reason": "resolved semantic query",
                        }
                    )
                continue
            if subcommand == "symlist":
                resolved, metadata = _resolve_inventory_command(
                    command,
                    repo=repo,
                    config=config,
                    output_dir=discovery_output_dir,
                    query=resolved_query,
                )
                command_trials.append(
                    {
                        "requested": list(command),
                        "resolved": list(resolved) if resolved is not None else None,
                        "trials": [metadata],
                    }
                )
                if resolved is None:
                    skipped_commands.append(tuple(command))
                else:
                    resolved_commands.append(resolved)
                continue
            resolved_commands.append(tuple(command))
            command_trials.append(
                {
                    "requested": list(command),
                    "resolved": list(command),
                    "reason": "literal command",
                }
            )
        selection["command_trials"] = command_trials

    return ResolvedRepositoryBenchmark(
        label=repo.label,
        category=repo.category,
        path=repo.path,
        query=resolved_query,
        requested_query=repo.query,
        modes=repo.modes,
        commands=tuple(resolved_commands),
        requested_commands=repo.commands,
        skipped_commands=tuple(skipped_commands),
        selection=selection,
    )


def resolve_repositories(
    repositories: Iterable[RepositoryBenchmark],
    config: CampaignConfig,
) -> tuple[ResolvedRepositoryBenchmark, ...]:
    """
    Resolve adaptive selections for every repository in one campaign.

    Parameters
    ----------
    repositories : collections.abc.Iterable[RepositoryBenchmark]
        Repository benchmark targets loaded from the manifest.
    config : CampaignConfig
        Campaign configuration.

    Returns
    -------
    tuple[ResolvedRepositoryBenchmark, ...]
        Resolved benchmark repositories in manifest order.
    """
    resolved = tuple(
        resolve_repository_benchmark(repo, config) for repo in repositories
    )
    selection_directory(config).mkdir(parents=True, exist_ok=True)
    for repo in resolved:
        selection_path = selection_directory(config) / (
            f"{_safe_label(repo.category)}-{_safe_label(repo.label)}-selection.json"
        )
        write_json_artifact(
            selection_path,
            {
                "label": repo.label,
                "category": repo.category,
                "path": str(repo.path),
                "requested_query": repo.requested_query,
                "resolved_query": repo.query,
                "requested_commands": [
                    list(command) for command in repo.requested_commands
                ],
                "resolved_commands": [list(command) for command in repo.commands],
                "skipped_commands": [
                    list(command) for command in repo.skipped_commands
                ],
                "selection": repo.selection,
            },
        )
    return resolved


def index_output_dir(
    repo: RepositoryBenchmark | ResolvedRepositoryBenchmark,
    config: CampaignConfig,
) -> Path:
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
    repo: ResolvedRepositoryBenchmark,
    *,
    codira: str,
    output_dir: Path,
    config: CampaignConfig,
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
    config : CampaignConfig
        Campaign configuration used to expand optional manifest commands.

    Returns
    -------
    tuple[str, ...]
        Shell-quoted command strings accepted by Hyperfine.
    """
    path = str(repo.path)
    output = str(output_dir)
    commands = [
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
    ]
    commands.extend(
        shlex.join(
            _manifest_command_argv(
                command,
                repo_path=repo.path,
                query=repo.query,
                config=config,
                output_dir=output_dir,
            )
        )
        for command in repo.commands
    )
    return tuple(dict.fromkeys(commands))


def build_hyperfine_argv(
    repo: ResolvedRepositoryBenchmark,
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
            config=config,
        ),
    )


def build_phase_benchmark_argv(
    repo: ResolvedRepositoryBenchmark,
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
        "--output-dir",
        str(index_output_dir(repo, config)),
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
    repo: ResolvedRepositoryBenchmark,
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
    repo: ResolvedRepositoryBenchmark,
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
    repositories: Iterable[RepositoryBenchmark | ResolvedRepositoryBenchmark],
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
    materialized = tuple(repositories)
    resolved_repositories: tuple[ResolvedRepositoryBenchmark, ...]
    if materialized and isinstance(materialized[0], RepositoryBenchmark):
        resolved_repositories = resolve_repositories(
            cast("tuple[RepositoryBenchmark, ...]", materialized),
            config,
        )
    else:
        resolved_repositories = cast(
            "tuple[ResolvedRepositoryBenchmark, ...]",
            materialized,
        )

    plan: list[dict[str, object]] = []
    for repo in resolved_repositories:
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
                "requested_query": repo.requested_query,
                "modes": list(repo.modes),
                "requested_commands": [
                    list(command) for command in repo.requested_commands
                ],
                "resolved_commands": [list(command) for command in repo.commands],
                "skipped_commands": [
                    list(command) for command in repo.skipped_commands
                ],
                "selection_artifact": str(
                    selection_directory(config)
                    / f"{_safe_label(repo.category)}-{_safe_label(repo.label)}-selection.json"
                ),
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

    Raises
    ------
    TypeError
        If an internally generated command plan has an invalid shape.
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
    config.artifact_root.mkdir(parents=True, exist_ok=True)
    try:
        repositories = load_manifest(config.manifest)
    except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    resolved_repositories = resolve_repositories(repositories, config)
    plan = command_plan(resolved_repositories, config)
    payload = {
        "metadata": benchmark_metadata(
            Path.cwd(),
            manifest=config.manifest,
            hyperfine=config.hyperfine,
        ),
        "run_id": config.run_id,
        "dry_run": config.dry_run,
        "adaptive_resolution": True,
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
