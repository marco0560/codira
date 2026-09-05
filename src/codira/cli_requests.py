"""Typed request records shared by Codira CLI command families."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from codira.version import package_version

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable
    from pathlib import Path
    from typing import Protocol

    from codira.indexer import CoverageIssue, IndexReport
    from codira.query.exact import CallTreeResult, EdgeQueryRequest, TreeQueryRequest

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


@dataclass(frozen=True)
class IndexRebuildRequest:
    """
    Describe one index rebuild requested by the CLI freshness check.

    Parameters
    ----------
    message : str
        Human-readable status line printed before the rebuild starts.
    reset_db : bool
        Whether the schema should be refreshed before indexing.
    stderr : bool
        Whether the status line should be emitted to standard error.
    """

    message: str
    reset_db: bool
    stderr: bool


@dataclass(frozen=True)
class IndexCommandRequest:
    """
    Runtime request for the ``index`` CLI command.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose supported source files should be indexed.
    full : bool
        Whether to force a full rebuild instead of incremental reuse.
    explain : bool
        Whether to print per-file indexing decisions after the summary.
    require_full_coverage : bool
        Whether strict coverage gating is enabled.
    defer_embeddings : bool
        Whether eligible embedding work should be left pending.
    concurrency : str | None
        Optional scheduler override.
    jobs : int | None
        Optional explicit analysis worker cap.
    embeddings_only : bool
        Whether only pending embeddings should be computed.
    as_json : bool
        Whether to render structured JSON output.
    """

    root: Path
    full: bool
    explain: bool
    require_full_coverage: bool
    defer_embeddings: bool
    embeddings_only: bool
    concurrency: str | None = None
    jobs: int | None = None
    as_json: bool = False


@dataclass(frozen=True)
class IndexPayloadRequest:
    """
    Structured payload request for ``codira index --json``.

    Parameters
    ----------
    full : bool
        Whether the caller requested a full rebuild.
    explain : bool
        Whether the caller requested per-file decision details.
    require_full_coverage : bool
        Whether strict coverage gating was enabled.
    defer_embeddings : bool
        Whether the caller requested deferred embedding computation.
    embeddings_only : bool
        Whether the caller requested only pending embedding computation.
    status : str
        Stable status code for the command outcome.
    report : codira.indexer.IndexReport | None
        Completed index report, or ``None`` when indexing stopped early.
    coverage_issues : list[codira.indexer.CoverageIssue]
        Coverage issues relevant to the command outcome.
    """

    full: bool
    explain: bool
    require_full_coverage: bool
    status: str
    report: IndexReport | None
    coverage_issues: list[CoverageIssue]
    defer_embeddings: bool = False
    embeddings_only: bool = False


@dataclass(frozen=True)
class EmbeddingCommandRequest:
    """
    Runtime options for the ``emb`` CLI command.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    query : str
        Natural-language query to score.
    limit : int
        Maximum number of matches to print.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict matched files.
    as_json : bool, optional
        Whether to render structured JSON output.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.
    search_profile : str | None, optional
        Named similarity-index runtime profile.
    """

    root: Path
    query: str
    limit: int
    prefix: str | None = None
    as_json: bool = False
    query_prefix: str | None = None
    search_profile: str | None = None


@dataclass(frozen=True)
class DocumentationCommandRequest:
    """
    Runtime options for the ``docs`` CLI command.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    query : str
        Natural-language documentation query to score.
    limit : int
        Maximum number of documentation matches to print.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict matched documents.
    as_json : bool, optional
        Whether to render structured JSON output.
    explain : bool, optional
        Whether to render inspection details for the docs-only retrieval pass.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.
    search_profile : str | None, optional
        Named similarity-index runtime profile.
    """

    root: Path
    query: str
    limit: int
    prefix: str | None = None
    as_json: bool = False
    explain: bool = False
    query_prefix: str | None = None
    search_profile: str | None = None


@dataclass(frozen=True)
class SymbolInventoryCommandRequest:
    """
    Runtime options for the ``symlist`` CLI command.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict symbols.
    include_tests : bool, optional
        Whether symbols from ``tests`` modules are included.
    limit : int, optional
        Maximum number of symbols to print after sorting.
    as_json : bool, optional
        Whether to render structured JSON output.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.
    """

    root: Path
    prefix: str | None = None
    include_tests: bool = False
    limit: int = 1000
    as_json: bool = False
    query_prefix: str | None = None


@dataclass(frozen=True)
class RelationCommandRequest:
    """
    Runtime options shared by the ``calls`` and ``refs`` CLI commands.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    name : str
        Exact logical name to inspect.
    module : str | None, optional
        Optional exact module filter for the selected side of the relation.
    incoming : bool, optional
        Whether to show incoming relations instead of outgoing relations.
    as_tree : bool, optional
        Whether to render a bounded traversal tree instead of a flat list.
    as_dot : bool, optional
        Whether to render the bounded tree as Graphviz DOT.
    max_depth : int, optional
        Maximum traversal depth used by tree mode.
    max_nodes : int, optional
        Maximum number of rendered nodes used by tree mode.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict owner files.
    as_json : bool, optional
        Whether to render structured JSON output.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.
    """

    root: Path
    name: str
    module: str | None = None
    incoming: bool = False
    as_tree: bool = False
    as_dot: bool = False
    max_depth: int = 2
    max_nodes: int = 20
    prefix: str | None = None
    as_json: bool = False
    query_prefix: str | None = None


@dataclass(frozen=True)
class RelationCommandSpec:
    """
    Rendering and lookup hooks for one relation-oriented CLI command.

    Parameters
    ----------
    command : {"calls", "refs"}
        Stable command name used in JSON payloads.
    missing_message : str
        Human-readable relation label used in no-match output.
    graph_name : str
        Graphviz graph name used for DOT output.
    missing_direction_outgoing : str
        Human-readable label for missing outgoing results.
    missing_direction_incoming : str
        Human-readable label for missing incoming results.
    plain_arrow : str
        Flat-list arrow rendered between relation endpoints.
    outgoing_tree_marker : str
        Tree marker used for outgoing traversal.
    incoming_tree_marker : str
        Tree marker used for incoming traversal.
    source_module_key : str
        JSON key for the source module field.
    source_name_key : str
        JSON key for the source name field.
    target_module_key : str
        JSON key for the target module field.
    target_name_key : str
        JSON key for the target name field.
    row_fetcher : collections.abc.Callable[
        [codira.query.exact.EdgeQueryRequest],
        list[tuple[str, str, str | None, str | None, str | None, str | None, int]],
    ]
        Exact lookup helper for flat relation rows.
    tree_builder : collections.abc.Callable[
        [codira.query.exact.TreeQueryRequest],
        codira.query.exact.CallTreeResult | None,
    ]
        Exact traversal helper for tree mode.
    """

    command: str
    missing_message: str
    graph_name: str
    missing_direction_outgoing: str
    missing_direction_incoming: str
    plain_arrow: str
    outgoing_tree_marker: str
    incoming_tree_marker: str
    source_module_key: str
    source_name_key: str
    target_module_key: str
    target_name_key: str
    row_fetcher: Callable[
        [EdgeQueryRequest],
        list[tuple[str, str, str | None, str | None, str | None, str | None, int]],
    ]
    tree_builder: Callable[[TreeQueryRequest], CallTreeResult | None]


@dataclass(frozen=True)
class RelationSubcommandRequest:
    """
    Shared runtime context for one relation-oriented CLI subcommand.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    parser : argparse.ArgumentParser
        Active top-level parser used for error reporting.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None, optional
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.
    command : {"calls", "refs"}
        Stable relation subcommand name.
    """

    args: argparse.Namespace
    parser: argparse.ArgumentParser
    root: Path
    prefix: str | None = None
    raw_prefix: str | None = None
    command: str = ""
