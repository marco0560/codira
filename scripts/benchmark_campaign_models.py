"""Immutable data records for benchmark campaign planning.

Responsibilities
----------------
- Define manifest, resolved-selection, and runtime campaign records.
- Keep campaign data serializable and independent of CLI execution.

Architectural role
------------------
This module is the data-model boundary for the benchmark campaign script.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


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
    continue_on_error : bool
        Whether campaign execution should continue after command failures and
        persist a failure summary.
    keep_indexes : bool
        Whether repository-local benchmark index directories should be retained
        after logs, summaries, and profiles are written.
    config_file : pathlib.Path | None
        Optional explicit repo-level Codira config file passed to path-aware
        Codira commands.
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
    continue_on_error: bool = False
    keep_indexes: bool = False
    config_file: Path | None = None


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


@dataclass(frozen=True)
class AdaptiveDiscoveryContext:
    """
    Runtime context for adaptive command-resolution trials.

    Parameters
    ----------
    config : CampaignConfig
        Campaign configuration.
    output_dir : pathlib.Path
        Temporary Codira output directory used for discovery.
    """

    config: CampaignConfig
    output_dir: Path


__all__ = (
    "AdaptiveDiscoveryContext",
    "CampaignConfig",
    "RepositoryBenchmark",
    "ResolvedRepositoryBenchmark",
    "SymbolCandidate",
)
