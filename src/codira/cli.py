"""Command-line entry points for codira.

Responsibilities
----------------
- Parse CLI arguments, build the top-level parser, and dispatch subcommands.
- Coordinate analyzer inventory reporting, index rebuild logic, and metadata inspection.
- Expose commands such as `ctx`, `index`, `audit`, and docstring diagnostics.

Design principles
-----------------
CLI code keeps argument parsing deterministic, surfaces helpful errors, and delegates work to lower-level indexers and query helpers.

Architectural role
------------------
This module belongs to the **CLI layer** that wraps storage, indexing, and query primitives for end users.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import re
import shutil
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast

from codira.architecture import (
    ArchitectureForbiddenDependencyRule,
    ArchitectureLayer,
    ArchitecturePolicy,
    analyze_architecture_policy,
    build_architecture_model_from_index,
)
from codira.architecture_report import write_architecture_artifacts
from codira.calibration import (
    calibrate_embeddings,
    embeddings_config_update,
    render_embeddings_calibration_toml,
)
from codira.capabilities import build_capability_contract
from codira.config import (
    ConfigError,
    ConfigOrigin,
    IndexConcurrencyConfig,
    LevelName,
    ProfileName,
    config_path,
    config_to_mapping,
    effective_config_cache,
    ensure_user_config,
    explain_key,
    load_config_level,
    load_effective_config,
    override_repo_config_path,
    render_config_toml,
    update_config_file,
    user_config_path,
    validate_config_mapping,
    write_config_file,
)
from codira.contracts import (
    BackendError,
    VectorStorePurgeRequest,
    VectorStorePurgeResult,
)
from codira.daemon import (
    DaemonStatusStore,
    LaunchdUserAgent,
    QueryDaemonLaunchdUserAgent,
    QueryDaemonSystemdUserService,
    QueryDaemonWindowsScmService,
    SystemdUserService,
    WindowsScmService,
    run_foreground_daemon,
)
from codira.daemon.service_spec import ServiceSpecification
from codira.git import read_head_commit
from codira.indexer import (
    CoverageIssue,
    IndexFailure,
    IndexReport,
    IndexWarning,
    audit_repo_coverage,
    index_repo,
    persisted_analysis_coverage_issues,
    validate_index_concurrency_preflight,
)
from codira.migration import (
    ConfigMigrationMode,
    ModelImport,
    StateMigrationMode,
    apply_workspace_migration,
    migration_payload,
    preview_workspace_migration,
)
from codira.model_store import ModelIdentity
from codira.path_resolution import (
    CODIRA_CONFIG_FILE_ENV,
    CODIRA_OUTPUT_DIR_ENV,
    CODIRA_TARGET_DIR_ENV,
    ResolvedRuntimePaths,
    resolve_runtime_paths,
)
from codira.plugin_config import analyzer_inventory_discovery_json
from codira.prefix import normalize_prefix
from codira.query.context import ContextRequest, context_for
from codira.query.exact import (
    CallTreeNode,
    CallTreeResult,
    EdgeQueryRequest,
    TreeQueryRequest,
    build_call_tree,
    build_ref_tree,
    docstring_issues,
    embedding_inventory,
    find_call_edges,
    find_callable_refs,
    find_symbol,
    find_symbol_enum_members,
    find_symbol_overloads,
    symbol_inventory,
)
from codira.query_daemon import QueryDaemonIdentity
from codira.query_daemon_cli import CliRouteResult, emit_execution_mode, route_cli_read
from codira.query_daemon_lifecycle import (
    QueryDaemonStatusStore,
    install_query_daemon_signal_handlers,
    run_foreground_query_daemon,
)
from codira.registry import (
    active_index_backend,
    active_language_analyzers,
    active_plugin_instance_cache,
    active_similarity_index,
    configured_index_backend_name,
    plugin_registrations,
    validate_plugin_configuration,
)
from codira.repository_scope import is_repository_scope_excluded
from codira.scanner import analyzer_accepts_path, file_metadata, iter_project_files
from codira.semantic.embeddings import EmbeddingBackendError, get_embedding_backend
from codira.semantic.search import (
    DocumentationCandidatesRequest,
    EmbeddingCandidatesRequest,
    documentation_candidates,
    embedding_candidates,
    similarity_candidate_provenance_payload,
    similarity_query_provenance_payload,
)
from codira.similarity_lifecycle import (
    purge_active_similarity_index,
    rebuild_active_similarity_index,
)
from codira.storage import (
    _read_metadata_file,
    _write_metadata_file,
    acquire_index_lock,
    get_codira_dir,
    get_metadata_path,
    get_storage_root,
    override_storage_root,
)
from codira.vector_store import active_vector_store_context
from codira.version import installed_distribution_version, package_version
from codira.workspace import ResolvedWorkspace, WorkspaceDefinition, WorkspaceError
from codira.workspace_registry import WorkspaceRegistry

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Protocol

    import codira.indexer as indexer_types
    from codira.contracts import (
        BackendGraphMetric,
        BackendQueryConnection,
        BackendSymbolInventoryItem,
    )
    from codira.types import DocstringIssueRow

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


def _collapsed_source_text(source: str) -> str:
    """
    Return source text collapsed to stable single spacing.

    Parameters
    ----------
    source : str
        Source text to normalize.

    Returns
    -------
    str
        Source text with whitespace collapsed deterministically.
    """
    return " ".join(source.split())


def _source_constant_json_detail(
    *,
    file_path: str,
    symbol_name: str,
    lineno: int,
) -> dict[str, object] | None:
    """
    Return detail metadata for one indexed constant symbol.

    Parameters
    ----------
    file_path : str
        Absolute source path recorded for the symbol row.
    symbol_name : str
        Exact constant symbol name.
    lineno : int
        Indexed declaration line number.

    Returns
    -------
    dict[str, object] | None
        Constant detail payload when the current source still contains a
        matching declaration at the indexed location.
    """
    path = Path(file_path)
    try:
        source_line = path.read_text(encoding="utf-8").splitlines()[lineno - 1]
    except (IndexError, OSError, SyntaxError, UnicodeDecodeError):
        return None
    match = re.match(
        rf"^\s*{re.escape(symbol_name)}\s*(?::\s*(?P<annotation>[^=]+))?="
        r"\s*(?P<value>.+?)\s*$",
        source_line,
    )
    if match is None:
        return None
    annotation = match.group("annotation")
    return {
        "kind": "constant_detail",
        "annotation": None
        if annotation is None
        else _collapsed_source_text(annotation),
        "value": _collapsed_source_text(match.group("value")),
    }


def _current_analyzer_inventory(
    *, root: Path | None = None
) -> list[tuple[str, str, str]]:
    """
    Return the active analyzer inventory in persisted comparison form.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in analyzer
        selection.

    Returns
    -------
    list[tuple[str, str, str]]
        Active analyzer rows as ``(name, version, discovery_globs_json)``
        ordered by analyzer name.
    """
    rows: list[tuple[str, str, str]] = []
    for analyzer in sorted(
        active_language_analyzers(root=root),
        key=lambda item: str(item.name),
    ):
        rows.append(
            (
                str(analyzer.name),
                str(analyzer.version),
                analyzer_inventory_discovery_json(analyzer),
            )
        )
    return rows


def _loaded_plugin_registrations(
    *,
    root: Path | None = None,
) -> list[tuple[str, str, str, str]]:
    """
    Return loaded plugin registrations in deterministic display order.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in plugin
        diagnostics.

    Returns
    -------
    list[tuple[str, str, str, str]]
        Loaded plugin rows as ``(origin, family, name, version)`` ordered for
        operator-facing version reports. The reported version prefers the
        installed provider distribution version and falls back to the plugin's
        own implementation version when package metadata is unavailable.
    """
    return sorted(
        [
            (
                registration.origin,
                registration.family,
                registration.name,
                installed_distribution_version(registration.provider)
                or registration.version,
            )
            for registration in plugin_registrations(root=root)
            if registration.status == "loaded"
        ],
        key=lambda item: (
            {"first_party": 0, "third_party": 1, "core": 2}.get(item[0], 99),
            {
                "analyzer": 0,
                "backend": 1,
                "documentation-audit": 2,
                "embedding": 3,
                "vector-store": 4,
            }.get(item[1], 99),
            item[2],
            item[3],
        ),
    )


def _plugin_is_active_backend(
    family: str,
    name: str,
    *,
    root: Path | None = None,
) -> bool:
    """
    Return whether one plugin row is the configured active singleton.

    Parameters
    ----------
    family : str
        Plugin family name.
    name : str
        Plugin display name.
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in backend
        selection.

    Returns
    -------
    bool
        ``True`` when the row represents the currently configured singleton.
    """

    if family == "backend":
        return name == configured_index_backend_name(root=root)
    if family == "similarity-index":
        return name == load_effective_config(root=root).embeddings.similarity_index
    return False


def _render_version_report(*, root: Path | None = None) -> str:
    """
    Return the multi-line CLI version report.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should mark the active backend.

    Returns
    -------
    str
        Human-readable version report including the core package and installed
        plugins discovered in the current environment.
    """
    lines = [f"codira {__version__}"]
    bundle_version = installed_distribution_version("codira-bundle-official")
    registrations = _loaded_plugin_registrations(root=root)
    first_party_plugins = [
        registration
        for registration in registrations
        if registration[0] == "first_party"
    ]
    third_party_plugins = [
        registration
        for registration in registrations
        if registration[0] == "third_party"
    ]

    if bundle_version is not None:
        lines.append(f"bundle-official {bundle_version}")
        for _origin, family, name, version in first_party_plugins:
            active_suffix = (
                " [active]"
                if _plugin_is_active_backend(family, name, root=root)
                else ""
            )
            lines.append(f"  {family} {name} {version}{active_suffix}")
    elif first_party_plugins:
        lines.append("first-party plugins:")
        for _origin, family, name, version in first_party_plugins:
            active_suffix = (
                " [active]"
                if _plugin_is_active_backend(family, name, root=root)
                else ""
            )
            lines.append(f"  {family} {name} {version}{active_suffix}")

    if third_party_plugins:
        lines.append("third-party plugins:")
        for _origin, family, name, version in third_party_plugins:
            active_suffix = (
                " [active]"
                if _plugin_is_active_backend(family, name, root=root)
                else ""
            )
            lines.append(f"  {family} {name} {version}{active_suffix}")

    return "\n".join(lines)


def _run_version() -> int:
    """
    Print the runtime version report.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero after printing version information.
    """
    print(_render_version_report())
    return 0


def build_parser() -> argparse.ArgumentParser:
    """
    Build the top-level command-line parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser configured with the supported codira subcommands.
    """

    def _add_repo_path_arguments(command_parser: argparse.ArgumentParser) -> None:
        """
        Add shared target/output path overrides to one repo-bound command.

        Parameters
        ----------
        command_parser : argparse.ArgumentParser
            Subparser that operates on one repository index.

        Returns
        -------
        None
            Shared path arguments are added in place.
        """

        command_parser.add_argument(
            "-p",
            "--path",
            help=(
                f"Repository target directory to read (env: {CODIRA_TARGET_DIR_ENV})"
            ),
        )
        command_parser.add_argument(
            "-w",
            "--workspace",
            help="Named workspace routing selection (env: CODIRA_WORKSPACE)",
        )
        command_parser.add_argument(
            "--workspace-fingerprint",
            help=argparse.SUPPRESS,
        )
        command_parser.add_argument(
            "-o",
            "--output-dir",
            help=(
                "Directory under which .codira state is stored "
                f"(env: {CODIRA_OUTPUT_DIR_ENV})"
            ),
        )
        command_parser.add_argument(
            "-c",
            "--config-file",
            help=(
                "Explicit repo-level config file to merge instead of "
                f"<output-dir>/.codira/config.toml (env: {CODIRA_CONFIG_FILE_ENV})"
            ),
        )

    def _add_config_file_argument(command_parser: argparse.ArgumentParser) -> None:
        """
        Add the explicit repo config file argument to one parser.

        Parameters
        ----------
        command_parser : argparse.ArgumentParser
            Subparser receiving the shared option.

        Returns
        -------
        None
            The option is added in place.
        """

        command_parser.add_argument(
            "-c",
            "--config-file",
            help=(
                "Explicit repo-level config file to merge instead of "
                f"<output-dir>/.codira/config.toml (env: {CODIRA_CONFIG_FILE_ENV})"
            ),
        )

    def _add_execution_mode_argument(command_parser: argparse.ArgumentParser) -> None:
        """Add opt-in warm/direct routing diagnostics to an eligible read.

        Parameters
        ----------
        command_parser : argparse.ArgumentParser
            Parser receiving the diagnostic option.

        Returns
        -------
        None
            The option is added in place.
        """
        command_parser.add_argument(
            "--execution-mode",
            action="store_true",
            help="Report warm, direct, or fallback execution to standard error",
        )

    parser = argparse.ArgumentParser(
        prog="codira",
        description=(
            "Index a repository, precompute semantic embeddings, inspect exact "
            "symbols and static relations, and retrieve task-focused context."
        ),
        epilog=(
            "Examples:\n"
            "  codira index  # build or refresh the current repository index\n"
            "  codira index --require-full-coverage  # fail if tracked source files are uncovered\n"
            "  codira index --path /mnt/readonly/repo --output-dir /tmp/codira-run  # index a read-only repo while storing state elsewhere\n"
            "  codira index --config-file /tmp/codira-config.toml  # use a specific repo config file\n"
            "  codira sym build_parser  # look up the exact symbol named build_parser\n"
            '  codira emb "schema migration rules"  # inspect embedding-only matches\n'
            '  codira docs "release process"  # inspect documentation-only matches\n'
            "  codira symlist --limit 20  # list the top 20 indexed symbols\n"
            "  codira arch  # write a repository architecture artifact set\n"
            "  codira arch --output /tmp/architecture  # choose an artifact directory\n"
            '  codira ctx "find schema migration logic"  # retrieve task-focused context\n'
            "  codira ctx --prompt "
            '"add a regression test for symbol lookup"  # render a Codex-ready prompt\n'
            '  codira ctx --explain "why does symbol lookup rank this result?"  # show retrieval diagnostics\n'
            "  codira calls caller --tree  # render a bounded outgoing call tree\n"
            "  codira refs _retrieve_script_candidates --incoming --tree --dot  # render incoming references as DOT\n"
            "  codira daemon --help  # inspect the optional automatic-indexing daemon contract\n"
            "  codira query-daemon --help  # inspect the optional warm query service contract\n"
            "\n"
            "Local MCP:\n"
            "  codira-mcp --root .  # start the read-only stdio server\n"
            "  codira-mcp-config codex --root .  # generate a client configuration"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Show codira and installed plugin versions",
    )
    sub = parser.add_subparsers(
        dest="command",
        title="subcommands",
        metavar=(
            "{help,setup,index,cov,sym,symlist,arch,emb,docs,calls,refs,audit,ctx,plugins,"
            "caps,config,workspace,daemon,query-daemon,calibrate}"
        ),
    )

    sub.add_parser("help", help="Show help")
    setup_parser = sub.add_parser(
        "setup", help="Launch the optional coordinated Codira installer"
    )
    setup_parser.add_argument("setup_args", nargs=argparse.REMAINDER)
    index_parser = sub.add_parser(
        "index",
        help="Build or refresh the repository index",
        description=(
            "Build the repository-local SQLite index used by codira queries, "
            "including precomputed semantic embeddings. Incremental indexing "
            "reuses unchanged files by default."
        ),
        epilog=(
            "Examples:\n"
            "  codira index  # incrementally refresh the repository index\n"
            "  codira index --explain  # show per-file reuse and indexing decisions\n"
            "  codira index --full  # rebuild the index from scratch\n"
            "  codira index --require-full-coverage  # fail when canonical source files lack analyzer coverage\n"
            "  codira index --path /mnt/readonly/repo --output-dir /tmp/codira-run  # index a target repo with state stored elsewhere\n"
            "  codira index --config-file /tmp/codira-config.toml  # merge a specific repo config file"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    index_parser.add_argument(
        "-f",
        "--full",
        action="store_true",
        help="Force a full rebuild instead of reusing unchanged files",
    )
    index_parser.add_argument(
        "-e",
        "--explain",
        "--verbose",
        dest="explain",
        action="store_true",
        help="Show per-file indexing decisions after the summary",
    )
    index_parser.add_argument(
        "-C",
        "--require-full-coverage",
        action="store_true",
        help=(
            "Fail before indexing when canonical directories contain "
            "uncovered tracked files"
        ),
    )
    index_parser.add_argument(
        "-E",
        "--defer-embeddings",
        action="store_true",
        help="Record index data now and leave eligible embeddings pending",
    )
    index_parser.add_argument(
        "-B",
        "--embeddings-only",
        action="store_true",
        help="Compute pending embeddings without reparsing source files",
    )
    index_parser.add_argument(
        "--concurrency",
        choices=("off", "auto", "process", "thread"),
        help="Override configured analyzer scheduling strategy",
    )
    index_parser.add_argument(
        "--jobs",
        type=int,
        help="Force automatic scheduling with this positive analysis worker cap",
    )
    index_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    _add_repo_path_arguments(index_parser)

    coverage_parser = sub.add_parser(
        "cov",
        help="Inspect canonical-directory analyzer coverage",
        description=(
            "Inspect tracked files under canonical source directories and "
            "report which files are not covered by the active analyzer set."
        ),
        epilog=(
            "Examples:\n"
            "  codira cov  # print analyzer coverage gaps\n"
            "  codira cov --json  # emit analyzer coverage gaps as JSON"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    coverage_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    _add_repo_path_arguments(coverage_parser)

    symbol_parser = sub.add_parser(
        "sym",
        help="Find symbol by exact name",
        description="Resolve one exact symbol name from the indexed repository.",
        epilog=(
            "Examples:\n"
            "  codira sym build_parser  # look up the exact symbol named build_parser\n"
            "  codira sym build_parser --json  # emit exact symbol matches as JSON\n"
            "  codira sym build_parser --prefix src/codira  # restrict matches to src/codira"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    symbol_parser.add_argument("name", help="Exact symbol name to look up")
    symbol_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    symbol_parser.add_argument(
        "-x",
        "--prefix",
        help="Restrict results to files under this repo-root-relative path prefix",
    )
    _add_repo_path_arguments(symbol_parser)

    symlist_parser = sub.add_parser(
        "symlist",
        help="List indexed symbols with graph metrics",
        description=(
            "List indexed symbols with static call and callable-reference "
            "connectivity counts."
        ),
        epilog=(
            "Examples:\n"
            "  codira symlist  # list indexed symbols with graph metrics\n"
            "  codira symlist --json  # emit the symbol inventory as JSON\n"
            "  codira symlist --limit 20  # print only the first 20 sorted symbols\n"
            "  codira symlist --include-tests  # include symbols from test modules\n"
            "  codira symlist --prefix src/codira  # restrict inventory to src/codira"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    symlist_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    symlist_parser.add_argument(
        "-x",
        "--prefix",
        help="Restrict symbols to files under this repo-root-relative path prefix",
    )
    symlist_parser.add_argument(
        "-T",
        "--include-tests",
        action="store_true",
        help="Include symbols from tests modules",
    )
    symlist_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=1000,
        help="Maximum number of symbols to print after sorting (default: 1000)",
    )
    _add_repo_path_arguments(symlist_parser)

    architecture_parser = sub.add_parser(
        "arch",
        help="Render repository architecture artifacts",
        description=(
            "Build an analyzer-independent architecture report from the current "
            "repository index."
        ),
    )
    architecture_parser.add_argument(
        "--output",
        help="Artifact directory (default: <repo>/.codira/architecture-report)",
    )
    architecture_parser.add_argument(
        "--layer",
        action="append",
        default=[],
        metavar="NAME=PATH_PREFIX",
        help="Ordered path-prefix layer; repeat to define additional layers",
    )
    architecture_parser.add_argument(
        "--forbid",
        action="append",
        default=[],
        metavar="RULE:SOURCE_LAYER:DESTINATION_LAYER:SEVERITY",
        help="Forbidden directed layer dependency; repeat to define additional rules",
    )
    _add_repo_path_arguments(architecture_parser)

    embeddings_parser = sub.add_parser(
        "emb",
        help="Inspect embedding-channel matches",
        description=(
            "Inspect embedding-channel matches, or run vector-store maintenance "
            "with `codira emb purge`."
        ),
        epilog=(
            "Examples:\n"
            '  codira emb "schema migration rules"  # show embedding-only matches\n'
            '  codira emb "schema migration rules" --json  # emit embedding matches as JSON\n'
            '  codira emb "numpy docstring sections" --limit 3  # show only 3 embedding matches\n'
            '  codira emb "numpy docstring sections" --prefix '
            "src/codira/query  # restrict embedding matches to query code\n"
            "  codira emb purge --stale --dry-run  # report stale vector sets without deleting them\n"
            "  codira emb purge --stale --keep 1 --yes  # delete stale vector sets except the newest one\n"
            "  codira emb purge --all --yes  # delete every persisted vector set"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    embeddings_parser.add_argument(
        "query",
        nargs="?",
        metavar="{query,purge,similarity-purge,rebuild,reset}",
        help="Natural-language query to score against stored embeddings",
    )
    embeddings_parser.add_argument(
        "--search-profile",
        help="Named similarity-index search profile (default: configured default)",
    )
    embeddings_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=5,
        help="Maximum number of embedding matches to print",
    )
    embeddings_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    embeddings_parser.add_argument(
        "-x",
        "--prefix",
        help="Restrict matches to files under this repo-root-relative path prefix",
    )
    _add_execution_mode_argument(embeddings_parser)
    purge_options = embeddings_parser.add_argument_group(
        "purge options",
        "Options used only with `codira emb purge`.",
    )
    purge_mode = purge_options.add_mutually_exclusive_group()
    purge_mode.add_argument(
        "-S",
        "--stale",
        action="store_true",
        help="Delete vector sets not matching current config",
    )
    purge_mode.add_argument(
        "-A",
        "--all",
        dest="all_sets",
        action="store_true",
        help="Delete all persisted vectors and vector cache",
    )
    purge_options.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Report what would be deleted",
    )
    purge_options.add_argument(
        "-b",
        "--backend",
        choices=("sqlite", "duckdb"),
        help="Vector-store backend to target (default: configured vector store)",
    )
    purge_options.add_argument(
        "-O",
        "--older-than",
        type=int,
        metavar="DAYS",
        help="With --stale, select stale vector sets older than DAYS",
    )
    purge_options.add_argument(
        "-K",
        "--keep",
        type=int,
        default=0,
        help="With --stale, keep the N newest selected stale sets",
    )
    purge_options.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Confirm destructive purge execution",
    )
    purge_options.add_argument(
        "--allow-remote-orphans",
        action="store_true",
        help="Allow emb reset to proceed when verified remote cleanup fails",
    )
    _add_repo_path_arguments(embeddings_parser)

    docs_parser = sub.add_parser(
        "docs",
        help="Inspect documentation-channel matches",
        description=(
            "Inspect documentation-only retrieval for a natural-language query. "
            "This is an inspection surface for the docs channel; mixed code and "
            "documentation retrieval remains available through ctx."
        ),
        epilog=(
            "Examples:\n"
            '  codira docs "release process"  # show documentation-only matches\n'
            '  codira docs "release process" --json  # emit documentation matches as JSON\n'
            '  codira docs "architecture decisions" --explain  # show docs retrieval diagnostics\n'
            '  codira docs "plugin loading" --prefix docs  # restrict matches to docs'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    docs_parser.add_argument(
        "query",
        help="Natural-language query to score against stored documentation",
    )
    docs_parser.add_argument(
        "--search-profile",
        help="Named similarity-index search profile (default: configured default)",
    )
    docs_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=5,
        help="Maximum number of documentation matches to print",
    )
    docs_mode_group = docs_parser.add_mutually_exclusive_group()
    docs_mode_group.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    docs_mode_group.add_argument(
        "-e",
        "--explain",
        action="store_true",
        help="Show docs-only retrieval diagnostics",
    )
    docs_parser.add_argument(
        "-x",
        "--prefix",
        help="Restrict matches to files under this repo-root-relative path prefix",
    )
    _add_repo_path_arguments(docs_parser)

    calls_parser = sub.add_parser(
        "calls",
        help="Inspect indexed static call edges",
        description=(
            "Inspect static heuristic call edges stored during indexing. "
            "Use --incoming to show callers of a callee."
        ),
        epilog=(
            "Examples:\n"
            "  codira calls caller  # show outgoing static call edges for caller\n"
            "  codira calls caller --json  # emit call edges as JSON\n"
            "  codira calls caller --tree  # render outgoing calls as a bounded tree\n"
            "  codira calls caller --tree --dot  # render the tree as Graphviz DOT\n"
            "  codira calls imported_helper --module pkg.b --incoming  # show callers of imported_helper in pkg.b\n"
            "  codira calls caller --prefix src/codira/query  # restrict caller files to query code"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    calls_parser.add_argument(
        "name",
        help="Exact logical caller or callee name to inspect",
    )
    calls_parser.add_argument(
        "-m",
        "--module",
        help="Restrict the caller or callee side to one exact module",
    )
    calls_parser.add_argument(
        "-i",
        "--incoming",
        action="store_true",
        help="Show callers of the named callee instead of outgoing edges",
    )
    calls_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    calls_parser.add_argument(
        "-d",
        "--dot",
        action="store_true",
        help="Render a bounded tree as Graphviz DOT; requires --tree",
    )
    calls_parser.add_argument(
        "-t",
        "--tree",
        action="store_true",
        help="Render a bounded traversal tree instead of a flat edge list",
    )
    calls_parser.add_argument(
        "-D",
        "--max-depth",
        type=int,
        default=2,
        help="Maximum traversal depth used by --tree (default: 2)",
    )
    calls_parser.add_argument(
        "-N",
        "--max-nodes",
        type=int,
        default=20,
        help="Maximum number of rendered nodes used by --tree (default: 20)",
    )
    calls_parser.add_argument(
        "-x",
        "--prefix",
        help="Restrict caller files to this repo-root-relative path prefix",
    )
    _add_repo_path_arguments(calls_parser)

    refs_parser = sub.add_parser(
        "refs",
        help="Inspect indexed callable-object references",
        description=(
            "Inspect static heuristic references to callable objects such as "
            "registry bindings, return values, and assignment values. "
            "Use --incoming to show owners that reference a target."
        ),
        epilog=(
            "Examples:\n"
            "  codira refs helper  # show outgoing callable-object references from helper\n"
            "  codira refs helper --json  # emit references as JSON\n"
            "  codira refs helper --incoming --tree  # render incoming references as a bounded tree\n"
            "  codira refs helper --tree --dot  # render the reference tree as Graphviz DOT\n"
            "  codira refs _retrieve_script_candidates --incoming  # show owners that reference the target\n"
            "  codira refs imported_helper --module pkg.b --incoming  # restrict incoming target side to pkg.b\n"
            "  codira refs helper --prefix src/codira/query  # restrict owner files to query code"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    refs_parser.add_argument(
        "name",
        help="Exact logical owner or target name to inspect",
    )
    refs_parser.add_argument(
        "-m",
        "--module",
        help="Restrict the owner or target side to one exact module",
    )
    refs_parser.add_argument(
        "-i",
        "--incoming",
        action="store_true",
        help="Show owners of the named target instead of outgoing references",
    )
    refs_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    refs_parser.add_argument(
        "-d",
        "--dot",
        action="store_true",
        help="Render a bounded tree as Graphviz DOT; requires --tree",
    )
    refs_parser.add_argument(
        "-t",
        "--tree",
        action="store_true",
        help="Render a bounded traversal tree instead of a flat reference list",
    )
    refs_parser.add_argument(
        "-D",
        "--max-depth",
        type=int,
        default=2,
        help="Maximum traversal depth used by --tree (default: 2)",
    )
    refs_parser.add_argument(
        "-N",
        "--max-nodes",
        type=int,
        default=20,
        help="Maximum number of rendered nodes used by --tree (default: 20)",
    )
    refs_parser.add_argument(
        "-x",
        "--prefix",
        help="Restrict owner files to this repo-root-relative path prefix",
    )
    _add_repo_path_arguments(refs_parser)

    audit_parser = sub.add_parser(
        "audit",
        help="List docstring issues",
        description="Print indexed docstring issues in deterministic order.",
        epilog=(
            "Examples:\n"
            "  codira audit  # print indexed docstring issues\n"
            "  codira audit --json  # emit docstring issues as JSON\n"
            "  codira audit --prefix src/codira/query  # restrict issues to query code"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    audit_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    audit_parser.add_argument(
        "-x",
        "--prefix",
        help="Restrict issues to files under this repo-root-relative path prefix",
    )
    _add_repo_path_arguments(audit_parser)

    context_parser = sub.add_parser(
        "ctx",
        help="Retrieve task-focused repository context",
        description=(
            "Retrieve task-focused repository context for a natural-language "
            "query. The retrieval pipeline includes symbol, heuristic semantic, "
            "and embedding channels. Output modes are mutually exclusive."
        ),
        epilog=(
            "Examples:\n"
            '  codira ctx "find schema migration logic"  # retrieve task-focused context\n'
            '  codira ctx --json "schema migration rules"  # emit retrieved context as JSON\n'
            '  codira ctx --prompt "add a test for imported calls"  # render a Codex-ready prompt\n'
            "  codira ctx --explain "
            '"why does symbol lookup rank this result?"  # show retrieval diagnostics\n'
            '  codira ctx "find schema migration logic" --prefix '
            "src/codira/query  # restrict retrieval to query code\n"
            '  codira ctx "static call graph"  # retrieve call-graph-related context'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    context_parser.add_argument(
        "query", type=str, help="Natural-language query to retrieve context for"
    )
    _add_execution_mode_argument(context_parser)
    mode_group = context_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON (agent mode)",
    )
    mode_group.add_argument(
        "-P",
        "--prompt",
        action="store_true",
        help="Output a Codex-ready deterministic prompt",
    )
    mode_group.add_argument(
        "-e",
        "--explain",
        action="store_true",
        help="Show retrieval routing and merge diagnostics",
    )
    context_parser.add_argument(
        "-x",
        "--prefix",
        help="Restrict retrieval to files under this repo-root-relative path prefix",
    )
    context_parser.add_argument(
        "--search-profile",
        help="Use a named similarity-index search profile for semantic channels",
    )
    _add_repo_path_arguments(context_parser)

    plugins_parser = sub.add_parser(
        "plugins",
        help="List built-in and third-party plugins",
        description=(
            "List analyzer and backend plugins discovered from built-ins and "
            "installed Python entry points."
        ),
        epilog=(
            "Examples:\n"
            "  codira plugins  # list discovered plugins\n"
            "  codira plugins --json  # emit plugin registrations as JSON"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    plugins_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    _add_execution_mode_argument(plugins_parser)

    capabilities_parser = sub.add_parser(
        "caps",
        help="Export the machine-readable capability contract",
        description=(
            "Export codira's deterministic Layer 0 capability contract, "
            "including ontology, command, channel, analyzer, and retrieval "
            "producer declarations."
        ),
        epilog=(
            "Examples:\n"
            "  codira caps  # print the capability contract summary\n"
            "  codira caps --json  # emit the full capability contract as JSON\n"
            "  codira caps --strict --json  # fail if declarations are invalid"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    capabilities_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    _add_execution_mode_argument(capabilities_parser)
    capabilities_parser.add_argument(
        "-s",
        "--strict",
        action="store_true",
        help="Fail if active analyzers have missing or invalid declarations",
    )

    config_parser = sub.add_parser(
        "config",
        help="Inspect and manage Codira configuration",
        description=(
            "Create, inspect, explain, and validate Codira's deterministic "
            "configuration hierarchy."
        ),
        epilog=(
            "Examples:\n"
            "  codira config init  # create the default repository config template\n"
            "  codira config init --level repo --profile low-memory  # create a repo config with low-memory overrides\n"
            "  codira config dump --level effective  # print the merged effective config\n"
            "  codira config explain embeddings.batch_size  # show where one config value came from\n"
            "  codira config validate  # validate effective config and plugin tables"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_repo_path_arguments(config_parser)
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_init_parser = config_sub.add_parser(
        "init",
        help="Create a config file for one level",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_config_file_argument(config_init_parser)
    config_init_parser.add_argument(
        "-l",
        "--level",
        choices=("user", "repo", "system"),
        default="repo",
        help="Config level to create (default: repo)",
    )
    config_init_parser.add_argument(
        "-r",
        "--profile",
        choices=("default", "low-memory", "gpu"),
        default="default",
        help="Generated profile to write (default: default)",
    )
    config_init_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite an existing config file",
    )
    config_init_parser.add_argument(
        "-F",
        "--full",
        action="store_true",
        help="Include all known first-party plugin options with default values",
    )
    config_dump_parser = config_sub.add_parser(
        "dump",
        help="Print one config level or the effective config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_config_file_argument(config_dump_parser)
    config_dump_parser.add_argument(
        "-l",
        "--level",
        choices=("system", "user", "repo", "effective"),
        default="effective",
        help="Config level to dump (default: effective)",
    )
    config_dump_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    config_explain_parser = config_sub.add_parser(
        "explain",
        help="Explain one effective config key",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_config_file_argument(config_explain_parser)
    config_explain_parser.add_argument("key", help="Dotted config key to explain")
    config_explain_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    config_validate_parser = config_sub.add_parser(
        "validate",
        help="Validate one config level or the effective config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_config_file_argument(config_validate_parser)
    config_validate_parser.add_argument(
        "-l",
        "--level",
        choices=("system", "user", "repo", "effective"),
        default="effective",
        help="Config level to validate (default: effective)",
    )
    config_validate_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )

    workspace_parser = sub.add_parser(
        "workspace",
        help="Manage named workspace registrations",
        description="Register, inspect, validate, update, or unregister one named workspace.",
    )
    workspace_sub = workspace_parser.add_subparsers(dest="workspace_action")
    for action, help_text in (
        ("add", "Register one workspace"),
        ("list", "List registered workspaces"),
        ("show", "Show one workspace descriptor"),
        ("validate", "Validate one workspace routing definition"),
        ("update", "Update one registered workspace"),
        ("remove", "Unregister one workspace without deleting its data"),
        ("migrate", "Preview or apply a non-destructive workspace migration"),
    ):
        action_parser = workspace_sub.add_parser(action, help=help_text)
        action_parser.add_argument("-j", "--json", action="store_true")
        if action in {"add", "update", "migrate"}:
            action_parser.add_argument("name")
            action_parser.add_argument("--path", required=True)
            action_parser.add_argument("--state-root")
            action_parser.add_argument("--config-file")
        if action == "migrate":
            action_parser.add_argument(
                "--config-mode",
                choices=tuple(ConfigMigrationMode),
                default=ConfigMigrationMode.NONE,
                help="Preserve, reference, or atomically copy the configuration",
            )
            action_parser.add_argument("--state-source")
            action_parser.add_argument(
                "--state-mode",
                choices=tuple(StateMigrationMode),
                default=StateMigrationMode.REBUILD,
                help="Reuse, atomically copy, or rebuild Codira state",
            )
            action_parser.add_argument(
                "--model-import",
                action="append",
                default=[],
                metavar="ENGINE|MODEL|VERSION|ARTIFACT|PATH",
                help="Import one existing model artifact into the shared store",
            )
            action_parser.add_argument("--model-root")
            action_parser.add_argument(
                "--apply",
                action="store_true",
                help="Apply the previewed plan; default is a no-write dry run",
            )
        elif action in {"show", "validate", "remove"}:
            action_parser.add_argument("name")

    daemon_parser = sub.add_parser(
        "daemon",
        help="Run or inspect the optional automatic-indexing daemon",
        description=(
            "Run the foreground mode of Codira's optional automatic indexing "
            "daemon, or manage its installed platform service."
        ),
        epilog=(
            "Lifecycle commands:\n"
            "  codira daemon run\n"
            "  codira daemon install\n"
            "  codira daemon uninstall\n"
            "  codira daemon start\n"
            "  codira daemon stop\n"
            "  codira daemon status\n"
            "\n"
            "Service support: Linux systemd user units, macOS LaunchAgents, "
            "and Windows SCM services."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_repo_path_arguments(daemon_parser)
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_action")
    for action, help_text in (
        ("run", "Run the daemon in the foreground"),
        ("install", "Install a platform service definition"),
        ("uninstall", "Remove a platform service definition"),
        ("start", "Start the installed daemon service"),
        ("stop", "Stop the installed daemon service"),
        ("status", "Inspect daemon service and indexing status"),
    ):
        daemon_sub.add_parser(action, help=help_text)

    query_daemon_parser = sub.add_parser(
        "query-daemon",
        help="Inspect the optional repository-local warm query daemon",
        description=(
            "Run or inspect Codira's optional repository-local warm query daemon."
        ),
        epilog=(
            "Lifecycle commands:\n"
            "  codira query-daemon run\n"
            "  codira query-daemon install\n"
            "  codira query-daemon uninstall\n"
            "  codira query-daemon start\n"
            "  codira query-daemon stop\n"
            "  codira query-daemon status\n"
            "\n"
            "The service is disabled by default with query_daemon.enabled = false. "
            "It is repository/output-directory scoped and read-only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_repo_path_arguments(query_daemon_parser)
    query_daemon_sub = query_daemon_parser.add_subparsers(dest="query_daemon_action")
    for action, help_text in (
        ("run", "Run the query daemon in the foreground"),
        ("install", "Install a platform service definition"),
        ("uninstall", "Remove a platform service definition"),
        ("start", "Start the installed query daemon service"),
        ("stop", "Stop the installed query daemon service"),
        ("status", "Inspect query daemon service status"),
    ):
        query_daemon_sub.add_parser(action, help=help_text)

    calibrate_parser = sub.add_parser(
        "calibrate",
        help="Calibrate hardware-aware Codira runtime settings",
        description=(
            "Run deterministic bounded calibration workflows and emit "
            "configuration-compatible output."
        ),
        epilog=(
            "Examples:\n"
            "  codira calibrate embeddings  # print calibrated embedding settings\n"
            "  codira calibrate embeddings --print  # explicitly print calibrated TOML\n"
            "  codira calibrate embeddings --write  # merge calibrated values into user config\n"
            "  codira calibrate embeddings --output /tmp/codira-embeddings.toml  # write calibrated TOML to a file"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    calibrate_sub = calibrate_parser.add_subparsers(dest="calibration_target")
    embeddings_calibrate_parser = calibrate_sub.add_parser(
        "embeddings",
        help="Calibrate embedding runtime parameters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    calibration_mode = embeddings_calibrate_parser.add_mutually_exclusive_group()
    calibration_mode.add_argument(
        "-p",
        "--print",
        dest="print_output",
        action="store_true",
        help="Print the calibrated TOML snippet to stdout",
    )
    calibration_mode.add_argument(
        "-w",
        "--write",
        action="store_true",
        help="Merge calibrated values into the user config file",
    )
    calibration_mode.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the calibrated TOML snippet to a file",
    )

    return parser


def _print_embedding_purge_help() -> None:
    """
    Print focused help for ``codira emb purge``.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Help text is written to stdout.
    """

    print(
        "usage: codira emb purge [-h] [-S | -A] [-n] [-b {sqlite,duckdb}] "
        "[-O DAYS] [-K KEEP] [-y] [-p PATH] [-o OUTPUT_DIR] [-c CONFIG_FILE]\n"
        "\n"
        "Delete or report retained vector-store rows.\n"
        "\n"
        "options:\n"
        "  -h, --help            show this help message and exit\n"
        "  -S, --stale           delete vector sets not matching current config "
        "(default mode)\n"
        "  -A, --all             delete all persisted vectors and vector cache\n"
        "  -n, --dry-run         report what would be deleted\n"
        "  -b, --backend {sqlite,duckdb}\n"
        "                        vector-store backend to target "
        "(default: configured vector store)\n"
        "  -O, --older-than DAYS\n"
        "                        with --stale, select stale vector sets older "
        "than DAYS\n"
        "  -K, --keep KEEP       with --stale, keep the N newest selected stale "
        "sets\n"
        "  -y, --yes             confirm destructive purge execution\n"
        f"  -p, --path PATH       repository target directory to read "
        f"(env: {CODIRA_TARGET_DIR_ENV})\n"
        "  -o, --output-dir OUTPUT_DIR\n"
        "                        directory under which .codira state is stored "
        f"(env: {CODIRA_OUTPUT_DIR_ENV})\n"
        "  -c, --config-file CONFIG_FILE\n"
        "                        explicit repo-level config file to merge instead "
        "of <output-dir>/.codira/config.toml "
        f"(env: {CODIRA_CONFIG_FILE_ENV})\n"
        "\n"
        "Examples:\n"
        "  codira emb purge --stale --dry-run  # report stale vector sets "
        "without deleting them\n"
        "  codira emb purge --stale --backend duckdb --keep 1 --yes  # purge "
        "DuckDB stale sets except the newest one\n"
        "  codira emb purge --all --backend sqlite --yes  # delete every SQLite "
        "vector set\n"
    )


def _emit_json(payload: dict[str, object]) -> None:
    """
    Print a JSON payload with deterministic formatting.

    Parameters
    ----------
    payload : dict[str, object]
        JSON-serializable payload to render.

    Returns
    -------
    None
        The formatted JSON is printed to standard output.
    """
    print(json.dumps(payload, indent=2))


def _format_bytes(value: int | None) -> str:
    """
    Format a byte count for CLI output.

    Parameters
    ----------
    value : int | None
        Byte count, when available.

    Returns
    -------
    str
        Human-readable byte count.
    """
    if value is None:
        return "unknown"
    units = ("B", "KiB", "MiB", "GiB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{value} B"
        size /= 1024
    return f"{value} B"


def _query_payload(
    command: str,
    status: str,
    query: dict[str, object],
    results: list[dict[str, object]],
    **extra: object,
) -> dict[str, object]:
    """
    Build the shared JSON envelope for exact/query subcommands.

    Parameters
    ----------
    command : str
        Subcommand name that produced the payload.
    status : str
        Query status such as ``ok`` or ``no_matches``.
    query : dict[str, object]
        Machine-readable query arguments.
    results : list[dict[str, object]]
        Result rows for the selected subcommand.
    **extra : object
        Additional top-level JSON fields for command-specific metadata.

    Returns
    -------
    dict[str, object]
        Shared JSON envelope for the CLI query subcommands.
    """
    payload: dict[str, object] = {
        "schema_version": QUERY_JSON_SCHEMA_VERSION,
        "command": command,
        "status": status,
        "query": query,
        "results": results,
    }
    payload.update(extra)
    return payload


def _run_help(parser: argparse.ArgumentParser) -> int:
    """
    Print CLI help text.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Parser whose help message should be rendered.

    Returns
    -------
    int
        Process exit status for a successful help invocation.
    """
    parser.print_help()
    return 0


def _run_capabilities(
    *,
    root: Path,
    as_json: bool,
    strict: bool,
) -> int:
    """
    Render the deterministic capability contract.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose effective configuration determines active
        plugins.
    as_json : bool
        Whether to render the full JSON contract. Plain text prints a compact
        summary for humans.
    strict : bool
        Whether validation issues should fail instead of producing degraded
        metadata.

    Returns
    -------
    int
        Zero after rendering the capability contract.
    """
    payload = build_capability_contract(root=root, strict=strict)
    if as_json:
        _emit_json(payload)
        return 0

    ontology = payload["ontology"]
    commands = payload["commands"]
    analyzers = payload["analyzers"]
    plugin_families = payload["plugin_families"]
    plugins = payload["plugins"]
    mcp = payload["mcp"]
    validation = payload["validation"]
    print(f"schema_version: {payload['schema_version']}")
    if isinstance(ontology, dict):
        print(f"ontology_version: {ontology['version']}")
        print("ontology_types: " + ", ".join(str(item) for item in ontology["types"]))
    if isinstance(commands, dict):
        print("commands: " + ", ".join(sorted(commands)))
    if isinstance(analyzers, list):
        analyzer_names = [
            str(item["analyzer_name"])
            for item in analyzers
            if isinstance(item, dict) and "analyzer_name" in item
        ]
        print("analyzers: " + ", ".join(sorted(analyzer_names)))
    if isinstance(plugin_families, list) and isinstance(plugins, list):
        families = sorted(
            str(item["family"])
            for item in plugin_families
            if isinstance(item, dict) and isinstance(item.get("family"), str)
        )
        for family in families:
            family_plugins = sorted(
                f"{item['name']} [{item['status']}, "
                f"{'active' if item['active'] else 'inactive'}]"
                for item in plugins
                if isinstance(item, dict)
                and item.get("family") == family
                and isinstance(item.get("name"), str)
                and isinstance(item.get("active"), bool)
                and isinstance(item.get("status"), str)
            )
            print(f"{family.replace('-', '_')}_plugins: " + ", ".join(family_plugins))
    if isinstance(mcp, dict):
        tools = mcp.get("tools")
        if isinstance(tools, list):
            print(
                "mcp: "
                + f"{mcp['server_command']} ({mcp['transport']}, "
                + f"read-only, tools: {', '.join(str(tool) for tool in tools)})"
            )
    if isinstance(validation, dict):
        print(f"validation: {validation['status']}")
        issues = validation.get("issues")
        if isinstance(issues, list) and issues:
            print("validation_issues: " + "; ".join(str(issue) for issue in issues))
    return 0


def _run_capabilities_command(args: argparse.Namespace, root: Path) -> int:
    """Run capability diagnostics through the optional warm daemon.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed capabilities command arguments.
    root : pathlib.Path
        Current repository root used for daemon identity.

    Returns
    -------
    int
        Original capability command exit status.
    """
    routing = _route_eligible_cli_read(
        root,
        "cli.caps",
        {"as_json": args.json, "strict": args.strict},
    )
    if routing.stdout is not None:
        print(routing.stdout, end="")
        emit_execution_mode(routing, requested=args.execution_mode)
        return cast("int", routing.exit_code)
    result = _run_capabilities(root=root, as_json=args.json, strict=args.strict)
    emit_execution_mode(routing, requested=args.execution_mode)
    return result


def _run_index(request: IndexCommandRequest) -> int:  # noqa: C901, PLR0912
    """
    Build or refresh the repository index.

    Parameters
    ----------
    request : IndexCommandRequest
        Parsed command options for the indexing run.

    Returns
    -------
    int
        Process exit status for a successful indexing run.
    """
    root = request.root
    full = request.full
    explain = request.explain
    require_full_coverage = request.require_full_coverage
    defer_embeddings = request.defer_embeddings
    embeddings_only = request.embeddings_only
    concurrency = request.concurrency
    jobs = request.jobs
    as_json = request.as_json
    if defer_embeddings and embeddings_only:
        msg = "--defer-embeddings and --embeddings-only are mutually exclusive."
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="invalid_arguments",
                        report=None,
                        coverage_issues=[],
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            print(f"[codira] ValueError: {msg}", file=sys.stderr)
        return 2

    config = load_effective_config(root=root)
    if jobs is not None and jobs < 1:
        msg = "--jobs must be a positive integer."
        print(f"[codira] ValueError: {msg}", file=sys.stderr)
        return 2
    if concurrency == "off" and jobs is not None:
        msg = "--jobs cannot be combined with --concurrency off."
        print(f"[codira] ValueError: {msg}", file=sys.stderr)
        return 2
    analysis_concurrency = (
        None
        if concurrency is None and jobs is None
        else IndexConcurrencyConfig(
            strategy="auto"
            if jobs is not None and concurrency is None
            else (concurrency or config.index.strategy),
            max_workers=config.index.max_workers if jobs is None else jobs,
            min_files=config.index.min_files,
        )
    )
    effective_analysis_concurrency = analysis_concurrency or config.index
    try:
        validate_index_concurrency_preflight(root, effective_analysis_concurrency)
    except ValueError as exc:
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="invalid_concurrency",
                        report=None,
                        coverage_issues=[],
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            print(f"[codira] ValueError: {exc}", file=sys.stderr)
        return 2
    if not config.embeddings.enabled and (defer_embeddings or embeddings_only):
        msg = "Embedding index mode flags require embeddings.enabled = true."
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="embeddings_disabled",
                        report=None,
                        coverage_issues=[],
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            print(f"[codira] ConfigError: {msg}", file=sys.stderr)
        return 2

    effective_embedding_index_mode = (
        "deferred" if defer_embeddings else config.embeddings.indexing.mode
    )
    if embeddings_only:
        vector_store_context = active_vector_store_context(root)
        active_backend = active_index_backend(root=root)
        with acquire_index_lock(root):
            active_backend.initialize(root)
            recomputed, reused = active_backend.process_pending_embeddings(
                root,
                embedding_backend=get_embedding_backend(root=root),
                vector_store=vector_store_context.store,
                vector_set_identity=vector_store_context.identity,
                vector_store_config=vector_store_context.config,
            )
            vector_store_context.store.clear_pending_vectors(
                root,
                vector_store_context.identity,
                vector_store_context.config,
            )
            if recomputed:
                rebuild_active_similarity_index(root)
        report = IndexReport(
            indexed=0,
            reused=0,
            deleted=0,
            failed=0,
            embeddings_recomputed=recomputed,
            embeddings_reused=reused,
            decisions=[],
            failures=[],
            warnings=[],
            coverage_issues=[],
            embeddings_pending=0,
            embedding_index_mode=effective_embedding_index_mode,
            embedding_complete=True,
        )
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="ok",
                        report=report,
                        coverage_issues=[],
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            _render_index_report(root, report)
        return 0

    coverage_issues = audit_repo_coverage(root)
    if require_full_coverage and coverage_issues:
        if as_json:
            _emit_json(
                _index_payload(
                    IndexPayloadRequest(
                        full=full,
                        explain=explain,
                        require_full_coverage=require_full_coverage,
                        status="coverage_incomplete",
                        report=None,
                        coverage_issues=coverage_issues,
                        defer_embeddings=defer_embeddings,
                        embeddings_only=embeddings_only,
                    )
                )
            )
        else:
            _render_required_coverage_failure(root, coverage_issues)
        return 2

    with acquire_index_lock(root):
        active_index_backend(root=root).initialize(root)
        if analysis_concurrency is None:
            report = index_repo(
                root,
                full=full,
                embedding_index_mode=effective_embedding_index_mode,
            )
        else:
            report = index_repo(
                root,
                full=full,
                embedding_index_mode=effective_embedding_index_mode,
                analysis_concurrency=analysis_concurrency,
            )
    if as_json:
        _emit_json(
            _index_payload(
                IndexPayloadRequest(
                    full=full,
                    explain=explain,
                    require_full_coverage=require_full_coverage,
                    status="ok",
                    report=report,
                    coverage_issues=report.coverage_issues,
                    defer_embeddings=defer_embeddings,
                    embeddings_only=embeddings_only,
                )
            )
        )
        return 2 if require_full_coverage and report.coverage_issues else 0
    _render_index_report(root, report)
    if require_full_coverage and report.coverage_issues:
        return 2
    if explain:
        for decision in report.decisions:
            rel_path = Path(decision.path)
            try:
                rel_label = rel_path.relative_to(root).as_posix()
            except ValueError:
                rel_label = decision.path
            print(f"{decision.action}: {rel_label} ({decision.reason})")
    return 0


def _index_payload(
    request: IndexPayloadRequest,
) -> dict[str, object]:
    """
    Build the structured JSON payload for one index command run.

    Parameters
    ----------
    request : IndexPayloadRequest
        Structured index payload request.

    Returns
    -------
    dict[str, object]
        JSON-serializable payload for ``codira index --json``.
    """
    report = request.report
    return {
        "schema_version": QUERY_JSON_SCHEMA_VERSION,
        "command": "index",
        "status": request.status,
        "query": {
            "full": request.full,
            "explain": request.explain,
            "require_full_coverage": request.require_full_coverage,
            "defer_embeddings": request.defer_embeddings,
            "embeddings_only": request.embeddings_only,
        },
        "results": [],
        "summary": {
            "indexed": 0 if report is None else report.indexed,
            "reused": 0 if report is None else report.reused,
            "deleted": 0 if report is None else report.deleted,
            "failed": 0 if report is None else report.failed,
            "embeddings_recomputed": (
                0 if report is None else report.embeddings_recomputed
            ),
            "embeddings_reused": 0 if report is None else report.embeddings_reused,
            "embeddings_skipped": 0 if report is None else report.embeddings_skipped,
            "embeddings_pending": 0 if report is None else report.embeddings_pending,
            "embedding_index_mode": (
                "unknown" if report is None else report.embedding_index_mode
            ),
            "embedding_complete": False
            if report is None
            else report.embedding_complete,
            "analysis_concurrency": {
                "requested_strategy": "unknown"
                if report is None
                else report.analysis_concurrency.requested_strategy,
                "effective_strategy": "unknown"
                if report is None
                else report.analysis_concurrency.effective_strategy,
                "workers": 0 if report is None else report.analysis_concurrency.workers,
                "reason": None
                if report is None
                else report.analysis_concurrency.reason,
            },
        },
        "coverage_issues": [
            {
                "path": issue.path,
                "directory": issue.directory,
                "suffix": issue.suffix,
                "reason": issue.reason,
            }
            for issue in request.coverage_issues
        ],
        "warnings": [] if report is None else _index_warning_payload(report.warnings),
        "failures": [] if report is None else _index_failure_payload(report.failures),
        "decisions": (
            []
            if report is None or not request.explain
            else _index_decision_payload(report.decisions)
        ),
    }


def _index_decision_payload(
    decisions: list[indexer_types.IndexDecision],
) -> list[dict[str, object]]:
    """
    Serialize per-file index decisions for JSON output.

    Parameters
    ----------
    decisions : list[codira.indexer.IndexDecision]
        Deterministic per-file decisions emitted by the indexer.

    Returns
    -------
    list[dict[str, object]]
        JSON rows describing indexed, reused, and deleted files.
    """
    return [
        {
            "path": decision.path,
            "action": decision.action,
            "reason": decision.reason,
        }
        for decision in decisions
    ]


def _index_warning_payload(
    warnings: list[IndexWarning],
) -> list[dict[str, object]]:
    """
    Serialize index warning diagnostics for JSON output.

    Parameters
    ----------
    warnings : list[codira.indexer.IndexWarning]
        Warning diagnostics recorded during indexing.

    Returns
    -------
    list[dict[str, object]]
        JSON rows for warning diagnostics.
    """
    return [
        {
            "path": warning.path,
            "analyzer_name": warning.analyzer_name,
            "warning_type": warning.warning_type,
            "line": warning.line,
            "reason": warning.reason,
        }
        for warning in warnings
    ]


def _index_failure_payload(
    failures: list[IndexFailure],
) -> list[dict[str, object]]:
    """
    Serialize index failure diagnostics for JSON output.

    Parameters
    ----------
    failures : list[codira.indexer.IndexFailure]
        Failure diagnostics recorded during indexing.

    Returns
    -------
    list[dict[str, object]]
        JSON rows for failure diagnostics.
    """
    return [
        {
            "path": failure.path,
            "analyzer_name": failure.analyzer_name,
            "error_type": failure.error_type,
            "reason": failure.reason,
        }
        for failure in failures
    ]


def _render_required_coverage_failure(
    root: Path,
    coverage_issues: list[CoverageIssue],
) -> bool:
    """
    Render strict coverage failure output when indexing must stop early.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative path labels.
    coverage_issues : list[codira.indexer.CoverageIssue]
        Coverage-issue rows discovered before indexing.

    Returns
    -------
    bool
        ``True`` when strict coverage mode should abort indexing.
    """
    if not coverage_issues:
        return False
    print(
        "[codira] Coverage incomplete — install the missing analyzer "
        "plugins or rerun without --require-full-coverage",
        file=sys.stderr,
    )
    _render_coverage_issues(root, coverage_issues)
    return True


def _write_index_head_metadata(
    root: Path,
    *,
    indexed_file_count: int | None = None,
) -> None:
    """
    Persist index metadata derived from the current repository head.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose metadata should be updated.
    indexed_file_count : int | None, optional
        Number of indexed file rows known after a successful index run.

    Returns
    -------
    None
        Index metadata is updated in place.
    """
    metadata = _read_index_metadata(root)
    metadata.update(_build_index_metadata(root, indexed_file_count=indexed_file_count))
    _write_index_metadata(root, metadata)


def _relative_report_path(root: Path, path: str) -> str:
    """
    Convert one absolute diagnostic path into a repo-relative label.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for path relativization.
    path : str
        Absolute or already-relative path to render.

    Returns
    -------
    str
        Repo-relative diagnostic label when possible.
    """
    path_obj = Path(path)
    try:
        return path_obj.relative_to(root).as_posix()
    except ValueError:
        return path


def _render_index_report(root: Path, report: IndexReport) -> None:
    """
    Render the deterministic summary and diagnostics for one index run.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative diagnostic labels.
    report : codira.indexer.IndexReport
        Completed index-run report to render.

    Returns
    -------
    None
        Summary lines and diagnostics are printed to standard output.
    """
    print(f"Indexed: {report.indexed}")
    print(f"Reused: {report.reused}")
    print(f"Deleted: {report.deleted}")
    print(f"Failed: {report.failed}")
    print(f"Embeddings recomputed: {report.embeddings_recomputed}")
    print(f"Embeddings reused: {report.embeddings_reused}")
    print(f"Embeddings skipped: {report.embeddings_skipped}")
    print(f"Embeddings pending: {report.embeddings_pending}")
    print(f"Embedding index mode: {report.embedding_index_mode}")
    print(f"Embedding complete: {str(report.embedding_complete).lower()}")
    concurrency = report.analysis_concurrency
    suffix = "" if concurrency.reason is None else f" ({concurrency.reason})"
    print(
        "Analysis concurrency: "
        f"{concurrency.effective_strategy}, workers={concurrency.workers}{suffix}"
    )
    _render_coverage_issues(root, report.coverage_issues)
    _render_index_warnings(root, report.warnings)
    _render_index_failures(root, report.failures)


def _render_index_warnings(root: Path, warnings: list[IndexWarning]) -> None:
    """
    Render file-scoped analysis warnings from one index run.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative diagnostic labels.
    warnings : list[codira.indexer.IndexWarning]
        Recorded warning diagnostics to print.

    Returns
    -------
    None
        Warning diagnostics are printed to standard output.
    """
    for warning in warnings:
        rel_label = _relative_report_path(root, warning.path)
        line_suffix = f", line {warning.line}" if warning.line is not None else ""
        print(
            "warning: "
            f"{rel_label} ({warning.analyzer_name}, {warning.warning_type}"
            f"{line_suffix}, {warning.reason})"
        )


def _render_index_failures(root: Path, failures: list[IndexFailure]) -> None:
    """
    Render file-scoped analysis failures from one index run.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative diagnostic labels.
    failures : list[codira.indexer.IndexFailure]
        Recorded failure diagnostics to print.

    Returns
    -------
    None
        Failure diagnostics are printed to standard output.
    """
    for failure in failures:
        rel_label = _relative_report_path(root, failure.path)
        print(
            "failure: "
            f"{rel_label} ({failure.analyzer_name}, {failure.error_type}, "
            f"{failure.reason})"
        )


def _render_coverage_issues(root: Path, issues: list[CoverageIssue]) -> None:
    """
    Render canonical-directory coverage issues in deterministic text form.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative path labels.
    issues : list[codira.indexer.CoverageIssue]
        Coverage-issue rows to print.

    Returns
    -------
    None
        Coverage diagnostics are printed to standard output.
    """
    print(f"Coverage issues: {len(issues)}")
    grouped: OrderedDict[tuple[str, str], tuple[int, OrderedDict[str, None]]] = (
        OrderedDict()
    )
    for issue in issues:
        rel_path = Path(str(issue.path))
        try:
            rel_text = rel_path.relative_to(root).as_posix()
        except ValueError:
            rel_text = str(issue.path)
        top_level_directory = rel_text.split("/", 1)[0]
        key = (issue.suffix, issue.reason)
        count, directories = grouped.setdefault(key, (0, OrderedDict()))
        directories[top_level_directory] = None
        grouped[key] = (count + 1, directories)
    for (suffix, reason), (count, directories) in grouped.items():
        directory_list = ", ".join(directories)
        print(f"coverage: {suffix} x{count} in {directory_list} ({suffix}, {reason})")


def _run_coverage(root: Path, *, as_json: bool = False) -> int:
    """
    Inspect canonical-directory coverage for the active analyzer set.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose canonical tracked files should be inspected.
    as_json : bool, optional
        Whether to render structured JSON output.

    Returns
    -------
    int
        Zero when coverage is complete. JSON output also returns zero for
        incomplete coverage so automation can consume the structured findings.
    """
    analyzers = sorted(
        active_language_analyzers(root=root),
        key=lambda item: str(item.name),
    )
    issues = audit_repo_coverage(root)
    if get_metadata_path(root).exists():
        issues.extend(
            persisted_analysis_coverage_issues(root, active_index_backend(root=root))
        )
    coverage_config = load_effective_config(root=root).coverage
    configured_roots = coverage_config.roots
    if configured_roots == ("-",):
        coverage = {
            "source": "disabled",
            "patterns": [],
            "resolved_roots": [],
            "exclude_suffixes": list(coverage_config.exclude_suffixes),
        }
    else:
        roots = configured_roots or tuple(
            sorted(
                {
                    item
                    for analyzer in analyzers
                    for item in getattr(analyzer, "default_coverage_roots", ())
                }
            )
        )
        coverage = {
            "source": "config" if configured_roots else "analyzer-defaults",
            "patterns": list(roots),
            "exclude_suffixes": list(coverage_config.exclude_suffixes),
            "resolved_roots": sorted(
                {
                    path.relative_to(root).as_posix()
                    for pattern in roots
                    for path in root.glob(pattern)
                    if path.exists()
                }
            ),
        }

    if as_json:
        _emit_json(
            _query_payload(
                "cov",
                "ok" if not issues else "incomplete",
                {"coverage": coverage},
                [
                    {
                        "path": issue.path,
                        "directory": issue.directory,
                        "suffix": issue.suffix,
                        "reason": issue.reason,
                    }
                    for issue in issues
                ],
                analyzers=[
                    {
                        "name": str(analyzer.name),
                        "version": str(analyzer.version),
                        "discovery_globs": list(analyzer.discovery_globs),
                    }
                    for analyzer in analyzers
                ],
            )
        )
        return 0

    print(f"Coverage complete: {'yes' if not issues else 'no'}")
    print(f"Active analyzers: {len(analyzers)}")
    for analyzer in analyzers:
        globs = ", ".join(analyzer.discovery_globs)
        print(f"analyzer: {analyzer.name} version={analyzer.version} globs={globs}")
    _render_coverage_issues(root, issues)
    return 0 if not issues else 1


def _run_symbol(
    root: Path,
    name: str,
    *,
    prefix: str | None = None,
    as_json: bool = False,
    query_prefix: str | None = None,
) -> int:
    """
    Resolve and print exact symbol matches.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    name : str
        Exact symbol name to look up.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict symbol files.
    as_json : bool, optional
        Whether to render structured JSON output.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Zero when at least one symbol is found, otherwise one.
    """
    backend = active_index_backend(root=root)
    conn = backend.open_connection(root)
    try:
        rows = find_symbol(root, name, prefix=prefix, conn=conn)

        if as_json:

            def _symbol_json_result(
                symbol_type: str,
                module_name: str,
                symbol_name: str,
                file_path: str,
                lineno: int,
            ) -> dict[str, object]:
                row: dict[str, object] = {
                    "type": symbol_type,
                    "module": module_name,
                    "name": symbol_name,
                    "file": file_path,
                    "lineno": lineno,
                }
                overloads = find_symbol_overloads(
                    root,
                    (
                        symbol_type,
                        module_name,
                        symbol_name,
                        file_path,
                        lineno,
                    ),
                    conn=conn,
                )
                if overloads:
                    row["overloads"] = [
                        {
                            "kind": "overload",
                            "stable_id": stable_id,
                            "parent_stable_id": parent_stable_id,
                            "ordinal": ordinal,
                            "signature": signature,
                            "lineno": overload_lineno,
                            "end_lineno": end_lineno,
                            "docstring": docstring,
                        }
                        for (
                            stable_id,
                            parent_stable_id,
                            ordinal,
                            signature,
                            overload_lineno,
                            end_lineno,
                            docstring,
                        ) in overloads
                    ]
                enum_members = find_symbol_enum_members(
                    root,
                    (
                        symbol_type,
                        module_name,
                        symbol_name,
                        file_path,
                        lineno,
                    ),
                    conn=conn,
                )
                if enum_members:
                    row["enum_members"] = [
                        {
                            "kind": "enum_member",
                            "stable_id": stable_id,
                            "parent_stable_id": parent_stable_id,
                            "ordinal": ordinal,
                            "name": member_name,
                            "signature": signature,
                            "lineno": member_lineno,
                        }
                        for (
                            stable_id,
                            parent_stable_id,
                            ordinal,
                            member_name,
                            signature,
                            member_lineno,
                        ) in enum_members
                    ]
                if symbol_type == "constant":
                    constant_detail = _source_constant_json_detail(
                        file_path=file_path,
                        symbol_name=symbol_name,
                        lineno=lineno,
                    )
                    if constant_detail is not None:
                        row["constant_detail"] = constant_detail
                return row

            _emit_json(
                _query_payload(
                    "sym",
                    "ok" if rows else "no_matches",
                    {"name": name, "prefix": query_prefix},
                    [
                        _symbol_json_result(
                            symbol_type,
                            module_name,
                            symbol_name,
                            file_path,
                            lineno,
                        )
                        for symbol_type, module_name, symbol_name, file_path, lineno in rows
                    ],
                )
            )
            return 0 if rows else 1

        if not rows:
            print(f"No symbol found: {name}")
            return 1

        for symbol_type, module_name, symbol_name, file_path, lineno in rows:
            if symbol_type == "module":
                print(f"{symbol_type}: {module_name} {file_path}:{lineno}")
            else:
                print(
                    f"{symbol_type}: {module_name}.{symbol_name} {file_path}:{lineno}"
                )

        return 0
    finally:
        backend.close_connection(conn)


def _graph_metric_payload(metric: BackendGraphMetric) -> dict[str, int]:
    """
    Convert one graph metric to the public JSON shape.

    Parameters
    ----------
    metric : codira.contracts.BackendGraphMetric
        Graph metric returned by the active backend.

    Returns
    -------
    dict[str, int]
        JSON-ready metric payload.
    """
    return {"total": metric.total, "unresolved": metric.unresolved}


def _symbol_inventory_payload(
    item: BackendSymbolInventoryItem,
) -> dict[str, object]:
    """
    Convert one symbol inventory row to the public JSON shape.

    Parameters
    ----------
    item : codira.contracts.BackendSymbolInventoryItem
        Backend-neutral inventory row.

    Returns
    -------
    dict[str, object]
        JSON-ready symbol inventory payload.
    """
    return {
        "id": f"{item.module}:{item.name}",
        "type": item.symbol_type,
        "module": item.module,
        "name": item.name,
        "file": item.file,
        "lineno": item.lineno,
        "calls_out": _graph_metric_payload(item.calls_out),
        "calls_in": _graph_metric_payload(item.calls_in),
        "refs_out": _graph_metric_payload(item.refs_out),
        "refs_in": _graph_metric_payload(item.refs_in),
    }


def _format_graph_metric(name: str, metric: BackendGraphMetric) -> str | None:
    """
    Render one compact human-readable graph metric.

    Parameters
    ----------
    name : str
        Metric label to render.
    metric : codira.contracts.BackendGraphMetric
        Metric values returned by the active backend.

    Returns
    -------
    str | None
        Human-readable metric fragment, or ``None`` when all values are zero.
    """
    if metric.total == 0:
        return None
    if metric.unresolved == 0:
        return f"{name}={metric.total}"
    return f"{name}={metric.total} ({metric.unresolved} unresolved)"


def _run_symbol_inventory(request: SymbolInventoryCommandRequest) -> int:
    """
    Print indexed symbols with graph connectivity metrics.

    Parameters
    ----------
    request : SymbolInventoryCommandRequest
        Runtime options for the ``symlist`` command.

    Returns
    -------
    int
        Zero after rendering the inventory.
    """
    rows = symbol_inventory(
        request.root,
        prefix=request.prefix,
        include_tests=request.include_tests,
        limit=request.limit,
    )

    if request.as_json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "status": "ok",
                "symbols": [_symbol_inventory_payload(item) for item in rows],
            }
        )
        return 0

    current_module: str | None = None
    for item in rows:
        if item.module != current_module:
            current_module = item.module
            print(item.module)
        metrics = " ".join(
            metric
            for metric in (
                _format_graph_metric("calls_out", item.calls_out),
                _format_graph_metric("calls_in", item.calls_in),
                _format_graph_metric("refs_out", item.refs_out),
                _format_graph_metric("refs_in", item.refs_in),
            )
            if metric is not None
        )
        suffix = f"  {metrics}" if metrics else ""
        print(f"  {item.name}{suffix}")
    return 0


def _run_audit_docstrings(
    root: Path,
    *,
    prefix: str | None = None,
    as_json: bool = False,
    query_prefix: str | None = None,
) -> int:
    """
    Print indexed docstring issues.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict issue ownership.
    as_json : bool, optional
        Whether to render structured JSON output.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the audit command.
    """
    rows = docstring_issues(root, prefix=prefix)

    if as_json:
        _emit_json(
            _query_payload(
                "audit",
                "ok" if rows else "no_matches",
                {"prefix": query_prefix},
                [
                    {
                        "type": issue_type,
                        "message": message,
                        "audit_plugin": {
                            "name": audit_plugin_name,
                            "version": audit_plugin_version,
                        },
                        "audit_convention": {
                            "name": convention_name,
                            "version": convention_version,
                        },
                        "rule_id": rule_id,
                        "severity": severity,
                        "stable_id": stable_id,
                        "symbol_type": symbol_type,
                        "module": module_name,
                        "name": symbol_name,
                        "file": file_path,
                        "lineno": lineno,
                        "end_lineno": end_lineno,
                        "audit_route": {
                            "language": audit_language,
                            "convention": convention_name,
                            "plugin": audit_plugin_name,
                        },
                    }
                    for (
                        issue_type,
                        message,
                        audit_language,
                        audit_plugin_name,
                        audit_plugin_version,
                        convention_name,
                        convention_version,
                        rule_id,
                        severity,
                        stable_id,
                        symbol_type,
                        module_name,
                        symbol_name,
                        file_path,
                        lineno,
                        end_lineno,
                    ) in rows
                ],
            )
        )
        return 0

    if not rows:
        print("No docstring issues found")
        return 0

    grouped_missing: dict[tuple[str, str, int], list[str]] = {}
    passthrough: list[DocstringIssueRow] = []

    for row in rows:
        (
            issue_type,
            message,
            _audit_language,
            _audit_plugin_name,
            _audit_plugin_version,
            _convention_name,
            _convention_version,
            _rule_id,
            _severity,
            _stable_id,
            _symbol_type,
            _module_name,
            symbol_name,
            file_path,
            lineno,
            _end_lineno,
        ) = row

        if issue_type == "missing_parameter" and "Parameter not documented:" in message:
            param = message.split("Parameter not documented:", 1)[1].strip()
            key = (symbol_name, file_path, lineno)
            grouped_missing.setdefault(key, []).append(param)
        else:
            passthrough.append(row)

    for (symbol_name, file_path, lineno), params in grouped_missing.items():
        params_str = ", ".join(sorted(params))
        print(
            f"missing_parameter: Function {symbol_name}: Parameters not documented: {params_str} "
            f"[{file_path}:{lineno}]"
        )

    for (
        issue_type,
        message,
        _audit_language,
        _audit_plugin_name,
        _audit_plugin_version,
        _convention_name,
        _convention_version,
        _rule_id,
        _severity,
        _stable_id,
        _symbol_type,
        _module_name,
        _symbol_name,
        file_path,
        lineno,
        _end_lineno,
    ) in passthrough:
        print(f"{issue_type}: {message} [{file_path}:{lineno}]")

    return 0


def _run_embeddings(
    request: EmbeddingCommandRequest,
) -> int:
    """
    Print embedding-backend metadata and top embedding matches.

    Parameters
    ----------
    request : EmbeddingCommandRequest
        Runtime options for the embedding command.

    Returns
    -------
    int
        Zero when embedding inventory exists, otherwise one.
    """
    root = request.root
    backend = get_embedding_backend(root=root)
    inventory = embedding_inventory(root)

    if not inventory:
        if request.as_json:
            _emit_json(
                _query_payload(
                    "emb",
                    "not_indexed",
                    {
                        "text": request.query,
                        "limit": request.limit,
                        "prefix": request.query_prefix,
                    },
                    [],
                    backend={
                        "name": backend.name,
                        "version": backend.version,
                        "dim": backend.dim,
                    },
                    inventory=[],
                )
            )
            return 1
        print("No stored embeddings found. Run: codira index")
        return 1

    matches = embedding_candidates(
        EmbeddingCandidatesRequest(
            root=root,
            query=request.query,
            limit=request.limit,
            min_score=0.0,
            prefix=request.prefix,
            search_profile=request.search_profile,
        )
    )
    if request.as_json:
        similarity = getattr(matches, "search_result", None)
        resolved = getattr(matches, "resolved", ())
        if similarity is None:
            resolved = tuple(None for _ in matches)
        results: list[dict[str, object]] = []
        for match, resolved_candidate in zip(matches, resolved, strict=True):
            score, (symbol_type, module_name, name, file_path, lineno) = match
            results.append(
                {
                    "score": round(score, 2),
                    "type": symbol_type,
                    "module": module_name,
                    "name": name,
                    "file": file_path,
                    "lineno": lineno,
                    "similarity": (
                        None
                        if resolved_candidate is None
                        else similarity_candidate_provenance_payload(
                            resolved_candidate.candidate
                        )
                    ),
                }
            )
        _emit_json(
            _query_payload(
                "emb",
                "ok" if matches else "no_matches",
                {
                    "text": request.query,
                    "limit": request.limit,
                    "prefix": request.query_prefix,
                },
                results,
                backend={
                    "name": backend.name,
                    "version": backend.version,
                    "dim": backend.dim,
                },
                inventory=[
                    {
                        "backend": stored_backend,
                        "version": stored_version,
                        "dim": stored_dim,
                        "rows": count,
                    }
                    for stored_backend, stored_version, stored_dim, count in inventory
                ],
                similarity=(
                    None
                    if similarity is None
                    else similarity_query_provenance_payload(similarity)
                ),
            )
        )
        return 0

    print(f"backend: {backend.name} version={backend.version} dim={backend.dim}")
    for stored_backend, stored_version, stored_dim, count in inventory:
        print(
            "stored:"
            f" {stored_backend}"
            f" version={stored_version}"
            f" dim={stored_dim}"
            f" rows={count}"
        )

    if not matches:
        print("No embedding matches found.")
        return 0

    for score, (symbol_type, module_name, name, file_path, lineno) in matches:
        print(f"{score:.2f} {symbol_type}: {module_name}.{name} {file_path}:{lineno}")

    return 0


def _run_documentation_lookup(
    request: DocumentationCommandRequest,
) -> int:
    """
    Print docs-only retrieval matches.

    Parameters
    ----------
    request : codira.cli.DocumentationCommandRequest
        Runtime options for the docs command.

    Returns
    -------
    int
        Zero when documentation retrieval completed, otherwise one when no
        stored embeddings exist.
    """
    root = request.root
    backend = get_embedding_backend(root=root)
    inventory = embedding_inventory(root)

    if not inventory:
        if request.as_json:
            _emit_json(
                _query_payload(
                    "docs",
                    "not_indexed",
                    {
                        "text": request.query,
                        "limit": request.limit,
                        "prefix": request.query_prefix,
                    },
                    [],
                    backend={
                        "name": backend.name,
                        "version": backend.version,
                        "dim": backend.dim,
                    },
                )
            )
            return 1
        print("No stored embeddings found. Run: codira index")
        return 1

    matches = documentation_candidates(
        DocumentationCandidatesRequest(
            root=root,
            query=request.query,
            limit=request.limit,
            min_score=0.0,
            prefix=request.prefix,
            search_profile=request.search_profile,
        )
    )

    if request.as_json:
        similarity = getattr(matches, "search_result", None)
        resolved = getattr(matches, "resolved", ())
        if similarity is None:
            resolved = tuple(None for _ in matches)
        results: list[dict[str, object]] = []
        for match, resolved_candidate in zip(matches, resolved, strict=True):
            (
                score,
                (
                    stable_id,
                    kind,
                    source_format,
                    file_path,
                    lineno,
                    end_lineno,
                    title,
                    heading_path,
                    text,
                ),
            ) = match
            results.append(
                {
                    "score": round(score, 2),
                    "stable_id": stable_id,
                    "kind": kind,
                    "source_format": source_format,
                    "file": file_path,
                    "lineno": lineno,
                    "end_lineno": end_lineno,
                    "title": title,
                    "heading_path": list(heading_path),
                    "text": text,
                    "similarity": (
                        None
                        if resolved_candidate is None
                        else similarity_candidate_provenance_payload(
                            resolved_candidate.candidate
                        )
                    ),
                }
            )
        _emit_json(
            _query_payload(
                "docs",
                "ok" if matches else "no_matches",
                {
                    "text": request.query,
                    "limit": request.limit,
                    "prefix": request.query_prefix,
                },
                results,
                backend={
                    "name": backend.name,
                    "version": backend.version,
                    "dim": backend.dim,
                },
                similarity=(
                    None
                    if similarity is None
                    else similarity_query_provenance_payload(similarity)
                ),
            )
        )
        return 0

    if request.explain:
        print(f"backend: {backend.name} version={backend.version} dim={backend.dim}")
        print(f"query: {request.query}")
        print(f"limit: {request.limit}")
        print(f"prefix: {request.query_prefix}")
        print(f"matches: {len(matches)}")

    if not matches:
        print("No documentation matches found.")
        return 0

    for score, (
        stable_id,
        kind,
        source_format,
        file_path,
        lineno,
        end_lineno,
        title,
        heading_path,
        text,
    ) in matches:
        rel_path = _relative_report_path(root, file_path)
        end_label = f"-{end_lineno}" if end_lineno is not None else ""
        print(
            f"{score:.2f} {kind}: {title} "
            f"{rel_path}:{lineno}{end_label} [{source_format}]"
        )
        if request.explain:
            heading = " > ".join(heading_path)
            print(f"  stable_id: {stable_id}")
            print(f"  heading_path: {heading}")
            preview = " ".join(text.split())[:160]
            print(f"  preview: {preview}")

    return 0


def _validate_relation_request(
    request: RelationCommandRequest,
) -> int | None:
    """
    Validate shared traversal limits for relation commands.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.

    Returns
    -------
    int | None
        Error exit code when validation fails, otherwise ``None``.
    """
    if request.max_depth < 0:
        print("--max-depth must be >= 0", file=sys.stderr)
        return 2
    if request.max_nodes < 1:
        print("--max-nodes must be >= 1", file=sys.stderr)
        return 2
    return None


def _relation_query_metadata(
    request: RelationCommandRequest,
    *,
    tree: bool,
) -> dict[str, object]:
    """
    Build the shared JSON query metadata for relation commands.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.
    tree : bool
        Whether the current render mode is tree traversal.

    Returns
    -------
    dict[str, object]
        Machine-readable query metadata.
    """
    query: dict[str, object] = {
        "name": request.name,
        "module": request.module,
        "incoming": request.incoming,
        "prefix": request.query_prefix,
    }
    if tree:
        query["tree"] = True
        query["max_depth"] = request.max_depth
        query["max_nodes"] = request.max_nodes
    return query


def _relation_rows_payload(
    rows: list[tuple[str, str, str | None, str | None, str | None, str | None, int]],
    spec: RelationCommandSpec,
) -> list[dict[str, object]]:
    """
    Serialize flat relation rows for JSON output.

    Parameters
    ----------
    rows : list[tuple[str, str, str | None, str | None, str | None, str | None, int]]
        Flat relation rows returned by the exact query layer.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    list[dict[str, object]]
        JSON-serializable relation rows.
    """
    return [
        {
            spec.source_module_key: source_module,
            spec.source_name_key: source_name,
            spec.target_module_key: target_module,
            spec.target_name_key: target_name,
            **(
                {"external_target_kind": external_target_kind}
                if external_target_kind is not None
                else {}
            ),
            **(
                {"external_target_name": external_target_name}
                if external_target_name is not None
                else {}
            ),
            "resolved": bool(resolved),
        }
        for (
            source_module,
            source_name,
            target_module,
            target_name,
            external_target_kind,
            external_target_name,
            resolved,
        ) in rows
    ]


def _print_relation_rows(
    rows: list[tuple[str, str, str | None, str | None, str | None, str | None, int]],
    spec: RelationCommandSpec,
) -> None:
    """
    Print flat relation rows in deterministic plain text.

    Parameters
    ----------
    rows : list[tuple[str, str, str | None, str | None, str | None, str | None, int]]
        Flat relation rows returned by the exact query layer.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    None
        Relation rows are printed to standard output.
    """
    for (
        source_module,
        source_name,
        target_module,
        target_name,
        external_target_kind,
        external_target_name,
        resolved,
    ) in rows:
        source = f"{source_module}.{source_name}"
        if resolved:
            assert target_module is not None
            assert target_name is not None
            target = f"{target_module}.{target_name}"
        elif external_target_kind is not None and external_target_name is not None:
            target = f"{external_target_kind}:{external_target_name}"
        elif external_target_name is not None:
            target = external_target_name
        else:
            target = "<unresolved>"
        print(f"{source} {spec.plain_arrow} {target}")


def _run_relation_tree(
    request: RelationCommandRequest,
    spec: RelationCommandSpec,
) -> int:
    """
    Render one relation command in bounded tree mode.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    int
        Zero when the tree exists, otherwise one.
    """
    tree = spec.tree_builder(
        TreeQueryRequest(
            root=request.root,
            name=request.name,
            module=request.module,
            incoming=request.incoming,
            prefix=request.prefix,
            max_depth=request.max_depth,
            max_nodes=request.max_nodes,
        )
    )
    if request.as_json:
        _emit_json(
            _query_payload(
                spec.command,
                "ok" if tree is not None else "no_matches",
                _relation_query_metadata(request, tree=True),
                [_call_tree_result_payload(tree)] if tree is not None else [],
                truncated=(
                    {
                        "depth": tree.truncated_by_depth,
                        "nodes": tree.truncated_by_nodes,
                    }
                    if tree is not None
                    else {"depth": False, "nodes": False}
                ),
                node_count=tree.node_count if tree is not None else 0,
                edge_count=tree.edge_count if tree is not None else 0,
            )
        )
        return 0 if tree is not None else 1

    if tree is None:
        noun = (
            spec.missing_direction_incoming
            if request.incoming
            else spec.missing_direction_outgoing
        )
        if request.module is None:
            print(f"No {spec.missing_message} found for {noun}: {request.name}")
        else:
            print(
                f"No {spec.missing_message} found for "
                f"{noun}: {request.module}.{request.name}"
            )
        return 1

    if request.as_dot:
        for line in _render_relation_tree_dot(tree, graph_name=spec.graph_name):
            print(line)
        return 0

    for line in _render_relation_tree_lines(
        tree,
        outgoing_marker=spec.outgoing_tree_marker,
        incoming_marker=spec.incoming_tree_marker,
    ):
        print(line)
    if tree.truncated_by_depth or tree.truncated_by_nodes:
        truncation_bits: list[str] = []
        if tree.truncated_by_depth:
            truncation_bits.append(f"max_depth={request.max_depth}")
        if tree.truncated_by_nodes:
            truncation_bits.append(f"max_nodes={request.max_nodes}")
        print(f"truncated: {', '.join(truncation_bits)}")
    return 0


def _run_relation_rows_mode(
    request: RelationCommandRequest,
    spec: RelationCommandSpec,
) -> int:
    """
    Render one relation command in flat-row mode.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    int
        Zero when at least one row exists, otherwise one.
    """
    rows = spec.row_fetcher(
        EdgeQueryRequest(
            root=request.root,
            name=request.name,
            module=request.module,
            incoming=request.incoming,
            prefix=request.prefix,
        )
    )

    if request.as_json:
        _emit_json(
            _query_payload(
                spec.command,
                "ok" if rows else "no_matches",
                _relation_query_metadata(request, tree=False),
                _relation_rows_payload(rows, spec),
            )
        )
        return 0 if rows else 1

    if not rows:
        noun = (
            spec.missing_direction_incoming
            if request.incoming
            else spec.missing_direction_outgoing
        )
        if request.module is None:
            print(f"No {spec.missing_message} found for {noun}: {request.name}")
        else:
            print(
                f"No {spec.missing_message} found for "
                f"{noun}: {request.module}.{request.name}"
            )
        return 1

    _print_relation_rows(rows, spec)
    return 0


def _run_relation_command(
    request: RelationCommandRequest,
    spec: RelationCommandSpec,
) -> int:
    """
    Run one relation-oriented CLI command.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    int
        Process exit status for the command.
    """
    validation_error = _validate_relation_request(request)
    if validation_error is not None:
        return validation_error
    if request.as_tree:
        return _run_relation_tree(request, spec)
    return _run_relation_rows_mode(request, spec)


def _run_calls(
    request: RelationCommandRequest,
) -> int:
    """
    Print indexed static call edges for one logical name.

    Parameters
    ----------
    request : RelationCommandRequest
        Runtime options for the calls command.

    Returns
    -------
    int
        Zero when at least one edge is found, otherwise one.
    """
    return _run_relation_command(
        request,
        RelationCommandSpec(
            command="calls",
            missing_message="call edges",
            graph_name="codira_calls",
            missing_direction_outgoing="caller",
            missing_direction_incoming="callee",
            plain_arrow="->",
            outgoing_tree_marker="-> ",
            incoming_tree_marker="<- ",
            source_module_key="caller_module",
            source_name_key="caller_name",
            target_module_key="callee_module",
            target_name_key="callee_name",
            row_fetcher=find_call_edges,
            tree_builder=build_call_tree,
        ),
    )


def _call_tree_display(module: str | None, name: str, *, resolved: bool) -> str:
    """
    Render a compact display label for one call-tree node.

    Parameters
    ----------
    module : str | None
        Owning module when the node resolves to an indexed symbol.
    name : str
        Logical symbol name or unresolved placeholder.
    resolved : bool
        Whether the node resolves to a concrete indexed symbol.

    Returns
    -------
    str
        Display label suitable for plain-text tree rendering.
    """
    if not resolved:
        return name
    if module is None:
        return name
    return f"{module}.{name}"


def _dot_node_id(index: int) -> str:
    """
    Return a deterministic DOT node identifier for one rendered tree node.

    Parameters
    ----------
    index : int
        Zero-based traversal index assigned during DOT emission.

    Returns
    -------
    str
        Stable Graphviz-safe node identifier.
    """
    return f"n{index}"


def _dot_escape(value: str) -> str:
    """
    Escape one string value for safe inclusion in DOT labels.

    Parameters
    ----------
    value : str
        Raw label value to escape.

    Returns
    -------
    str
        DOT-safe double-quoted label content.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_relation_tree_dot(
    tree: CallTreeResult,
    *,
    graph_name: str,
) -> list[str]:
    """
    Render a bounded relation tree as Graphviz DOT.

    Parameters
    ----------
    tree : codira.query.exact.CallTreeResult
        Traversal result to render.
    graph_name : str
        Stable graph name used in the DOT header.

    Returns
    -------
    list[str]
        Deterministic DOT lines describing the rendered bounded tree.
    """
    lines = [f"digraph {graph_name} {{", "  rankdir=LR;"]
    node_counter = 0
    root_id = _dot_node_id(node_counter)
    root_label = _dot_escape(
        _call_tree_display(tree.root_module, tree.root_name, resolved=True)
    )
    lines.append(f'  {root_id} [label="{root_label}"];')

    def append_children(
        parent_id: str,
        nodes: tuple[CallTreeNode, ...],
    ) -> None:
        nonlocal node_counter
        for node in nodes:
            node_counter += 1
            node_id = _dot_node_id(node_counter)
            node_label = _call_tree_display(
                node.module,
                node.name,
                resolved=node.resolved,
            )
            attributes = [f'label="{_dot_escape(node_label)}"']
            if not node.resolved:
                attributes.append('style="dashed"')
            if node.cycle:
                attributes.append('peripheries="2"')
            lines.append(f"  {node_id} [{', '.join(attributes)}];")
            if tree.incoming:
                lines.append(f"  {node_id} -> {parent_id};")
            else:
                lines.append(f"  {parent_id} -> {node_id};")
            append_children(node_id, node.children)

    append_children(root_id, tree.children)

    truncation_bits: list[str] = []
    if tree.truncated_by_depth:
        truncation_bits.append("max_depth")
    if tree.truncated_by_nodes:
        truncation_bits.append("max_nodes")
    if truncation_bits:
        lines.append(
            f'  graph [label="truncated by {", ".join(truncation_bits)}", labelloc="b"];'
        )
    lines.append("}")
    return lines


def _call_tree_node_payload(node: CallTreeNode) -> dict[str, object]:
    """
    Serialize one bounded call-tree node for JSON output.

    Parameters
    ----------
    node : codira.query.exact.CallTreeNode
        Tree node to serialize.

    Returns
    -------
    dict[str, object]
        JSON-serializable tree node payload.
    """
    payload: dict[str, object] = {
        "module": node.module,
        "name": node.name,
        "display": _call_tree_display(
            node.module,
            node.name,
            resolved=node.resolved,
        ),
        "resolved": node.resolved,
        "cycle": node.cycle,
        "children": [_call_tree_node_payload(child) for child in node.children],
    }
    if node.external_target_kind is not None:
        payload["external_target_kind"] = node.external_target_kind
    if node.external_target_name is not None:
        payload["external_target_name"] = node.external_target_name
    return payload


def _call_tree_result_payload(tree: CallTreeResult) -> dict[str, object]:
    """
    Serialize one bounded call-tree result for JSON output.

    Parameters
    ----------
    tree : codira.query.exact.CallTreeResult
        Traversal result to serialize.

    Returns
    -------
    dict[str, object]
        JSON-serializable root payload for the bounded tree.
    """
    return {
        "module": tree.root_module,
        "name": tree.root_name,
        "display": _call_tree_display(
            tree.root_module,
            tree.root_name,
            resolved=True,
        ),
        "resolved": True,
        "incoming": tree.incoming,
        "cycle": False,
        "children": [_call_tree_node_payload(child) for child in tree.children],
    }


def _render_call_tree_lines(tree: CallTreeResult) -> list[str]:
    """
    Render a bounded call tree as deterministic plain-text lines.

    Parameters
    ----------
    tree : codira.query.exact.CallTreeResult
        Traversal result to render.

    Returns
    -------
    list[str]
        Deterministic plain-text lines for the bounded tree.
    """
    lines = [
        _call_tree_display(
            tree.root_module,
            tree.root_name,
            resolved=True,
        )
    ]
    marker = "<- " if tree.incoming else "-> "

    def append_children(nodes: tuple[CallTreeNode, ...], *, depth: int) -> None:
        for node in nodes:
            suffix = " [cycle]" if node.cycle else ""
            lines.append(
                f"{'  ' * depth}{marker}"
                f"{_call_tree_display(node.module, node.name, resolved=node.resolved)}"
                f"{suffix}"
            )
            append_children(node.children, depth=depth + 1)

    append_children(tree.children, depth=1)
    return lines


def _render_relation_tree_lines(
    tree: CallTreeResult,
    *,
    outgoing_marker: str,
    incoming_marker: str,
) -> list[str]:
    """
    Render a bounded relation tree with caller-selected edge markers.

    Parameters
    ----------
    tree : codira.query.exact.CallTreeResult
        Traversal result to render.
    outgoing_marker : str
        Marker used for outgoing traversal edges.
    incoming_marker : str
        Marker used for incoming traversal edges.

    Returns
    -------
    list[str]
        Deterministic plain-text lines for the bounded relation tree.
    """
    lines = [
        _call_tree_display(
            tree.root_module,
            tree.root_name,
            resolved=True,
        )
    ]
    marker = incoming_marker if tree.incoming else outgoing_marker

    def append_children(nodes: tuple[CallTreeNode, ...], *, depth: int) -> None:
        for node in nodes:
            suffix = " [cycle]" if node.cycle else ""
            lines.append(
                f"{'  ' * depth}{marker}"
                f"{_call_tree_display(node.module, node.name, resolved=node.resolved)}"
                f"{suffix}"
            )
            append_children(node.children, depth=depth + 1)

    append_children(tree.children, depth=1)
    return lines


def _run_refs(
    request: RelationCommandRequest,
) -> int:
    """
    Print indexed callable-object references for one logical name.

    Parameters
    ----------
    request : RelationCommandRequest
        Runtime options for the refs command.

    Returns
    -------
    int
        Zero when at least one reference is found, otherwise one.
    """
    return _run_relation_command(
        request,
        RelationCommandSpec(
            command="refs",
            missing_message="callable references",
            graph_name="codira_refs",
            missing_direction_outgoing="owner",
            missing_direction_incoming="target",
            plain_arrow="=>",
            outgoing_tree_marker="=> ",
            incoming_tree_marker="<= ",
            source_module_key="owner_module",
            source_name_key="owner_name",
            target_module_key="target_module",
            target_name_key="target_name",
            row_fetcher=find_callable_refs,
            tree_builder=build_ref_tree,
        ),
    )


def _get_head_commit(root: Path) -> str | None:
    """
    Read the current Git commit hash for a repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used as the subprocess working directory.

    Returns
    -------
    str | None
        Current ``HEAD`` commit hash, or ``None`` if it cannot be read.
    """
    return read_head_commit(root)


def _git_dirty_indexable_paths(root: Path) -> tuple[str, ...]:
    """
    Return Git-dirty paths that can affect the Codira index.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used as the Git working directory.

    Returns
    -------
    tuple[str, ...]
        Repo-root-relative paths reported dirty by Git and accepted by one
        active analyzer. An empty tuple is returned when Git cannot provide a
        dirty-path list.
    """
    try:
        result = subprocess.run(
            [GIT_EXE, "diff", "--name-only", "-z", "HEAD", "--"],
            cwd=root,
            capture_output=True,
            text=False,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ()

    analyzers = active_language_analyzers(root=root)
    dirty_paths: list[str] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode("utf-8", errors="surrogateescape")
        path = root / relative
        if is_repository_scope_excluded(path, root):
            continue
        if any(analyzer_accepts_path(analyzer, path, root) for analyzer in analyzers):
            dirty_paths.append(relative)
    return tuple(dict.fromkeys(dirty_paths))


def _read_index_metadata(root: Path) -> dict[str, str]:
    """
    Load persisted index metadata.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the ``.codira`` directory.

    Returns
    -------
    dict[str, str]
        Parsed metadata values, or an empty mapping when the metadata file
        does not exist or cannot be decoded.
    """
    return _read_metadata_file(get_metadata_path(root))


def _write_index_metadata(root: Path, data: dict[str, str]) -> None:
    """
    Persist index metadata as JSON.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the ``.codira`` directory.
    data : dict[str, str]
        Metadata payload to serialize.

    Returns
    -------
    None
        The metadata file is written in place.
    """
    _write_metadata_file(get_metadata_path(root), data)


def _resolve_prefix_argument(
    parser: argparse.ArgumentParser,
    root: Path,
    prefix: str | None,
) -> str | None:
    """
    Normalize one CLI prefix argument or terminate with a parser error.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Active top-level parser used for error reporting.
    root : pathlib.Path
        Repository root that anchors the prefix.
    prefix : str | None
        User-supplied repo-root-relative prefix.

    Returns
    -------
    str | None
        Absolute normalized prefix path, or ``None`` when unset.
    """
    if prefix is not None and Path(prefix).is_absolute():
        parser.error("Prefix must be relative to the repository root.")
    try:
        normalized = normalize_prefix(root, prefix)
    except ValueError as exc:
        parser.error(str(exc))
    if normalized is not None and not Path(normalized).exists():
        parser.error(f"Prefix does not exist under repository root: {prefix}")
    return normalized


def _build_index_metadata(
    root: Path,
    *,
    indexed_file_count: int | None = None,
) -> dict[str, str]:
    """
    Build the persisted freshness metadata for the current repository head.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose current Git metadata should be recorded.
    indexed_file_count : int | None, optional
        Number of file rows known to be present after a successful index run.

    Returns
    -------
    dict[str, str]
        Metadata payload containing schema, plugin, analyzer, file-count, and
        current commit facts when available.
    """
    backend = active_index_backend(root=root)
    metadata = {"schema_version": str(backend.version)}
    commit = _get_head_commit(root)
    if commit:
        metadata["commit"] = commit
    metadata[INDEX_METADATA_BACKEND_NAME] = str(backend.name)
    metadata[INDEX_METADATA_BACKEND_VERSION] = str(backend.version)
    metadata[INDEX_METADATA_ANALYZER_INVENTORY] = json.dumps(
        _current_analyzer_inventory(root=root)
    )
    if indexed_file_count is not None:
        metadata[INDEX_METADATA_FILE_COUNT] = str(indexed_file_count)
    return metadata


def _count_indexed_files_for_freshness(
    backend: object,
    root: Path,
    *,
    conn: object | None = None,
) -> int:
    """
    Count indexed files for CLI freshness checks.

    Parameters
    ----------
    backend : object
        Active index backend.
    root : pathlib.Path
        Repository root whose index should be inspected.
    conn : object | None, optional
        Existing backend connection to reuse.

    Returns
    -------
    int
        Number of files currently recorded in the index.
    """
    count_indexed_files = getattr(backend, "count_indexed_files", None)
    if callable(count_indexed_files):
        return int(count_indexed_files(root, conn=conn))
    hash_loader = cast("_IndexedFileHashLoader", backend)
    return len(hash_loader.load_existing_file_hashes(root, conn=conn))


def _dirty_indexable_paths_require_rebuild(
    root: Path,
    dirty_paths: tuple[str, ...],
    backend: object,
    *,
    conn: object | None = None,
) -> bool:
    """
    Return whether Git-dirty indexable paths differ from indexed content.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be inspected.
    dirty_paths : tuple[str, ...]
        Repo-root-relative paths reported dirty by Git and accepted by one
        active analyzer.
    backend : object
        Active index backend.
    conn : object | None, optional
        Existing backend connection to reuse.

    Returns
    -------
    bool
        ``True`` when at least one dirty path is new, deleted, or has content
        that differs from the hash persisted in the index.
    """
    hash_loader = cast("_IndexedFileHashLoader", backend)
    indexed_hashes = hash_loader.load_existing_file_hashes(root, conn=conn)
    for relative in dirty_paths:
        path = root / relative
        persisted_hash = indexed_hashes.get(str(path))
        if persisted_hash is None:
            return True
        try:
            current_hash = str(file_metadata(path)["hash"])
        except FileNotFoundError:
            return True
        if current_hash != persisted_hash:
            return True
    return False


def _inspect_index_metadata_freshness(
    root: Path,
    metadata: dict[str, str],
) -> tuple[bool, IndexRebuildRequest | None]:
    """
    Inspect metadata-only freshness facts when available.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose metadata should be inspected.
    metadata : dict[str, str]
        Parsed persisted index metadata.

    Returns
    -------
    tuple[bool, IndexRebuildRequest | None]
        ``(True, request)`` when metadata is complete enough to decide, where
        ``request`` is ``None`` for a fresh index. ``(False, None)`` when the
        caller must fall back to backend inspection.
    """
    metadata_file_count = metadata.get(INDEX_METADATA_FILE_COUNT)
    metadata_analyzers = metadata.get(INDEX_METADATA_ANALYZER_INVENTORY)
    metadata_backend_name = metadata.get(INDEX_METADATA_BACKEND_NAME)
    metadata_backend_version = metadata.get(INDEX_METADATA_BACKEND_VERSION)
    if (
        metadata_file_count is None
        or metadata_analyzers is None
        or metadata_backend_name is None
        or metadata_backend_version is None
    ):
        return (False, None)

    backend = active_index_backend(root=root)
    current_runtime = (str(backend.name), str(backend.version))
    if (metadata_backend_name, metadata_backend_version) != current_runtime:
        return (
            True,
            IndexRebuildRequest(
                message="[codira] Index stale (backend plugin changed) — rebuilding...",
                reset_db=True,
                stderr=True,
            ),
        )

    current_analyzers = _current_analyzer_inventory(root=root)
    if metadata_analyzers != json.dumps(current_analyzers):
        return (
            True,
            IndexRebuildRequest(
                message="[codira] Index stale "
                "(analyzer plugin inventory changed) — rebuilding...",
                reset_db=True,
                stderr=True,
            ),
        )

    try:
        indexed_files = int(metadata_file_count)
    except ValueError:
        return (
            True,
            IndexRebuildRequest(
                message="[codira] Index stale — rebuilding...",
                reset_db=True,
                stderr=True,
            ),
        )
    current_files = len(
        list(iter_project_files(root, analyzers=active_language_analyzers(root=root)))
    )
    if indexed_files != current_files:
        return (
            True,
            IndexRebuildRequest(
                message="[codira] Index stale — rebuilding...",
                reset_db=True,
                stderr=True,
            ),
        )
    return (True, None)


def _inspect_index_rebuild_request(root: Path) -> IndexRebuildRequest | None:
    """
    Inspect the local index and report whether a rebuild is required.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose local index should be inspected.

    Returns
    -------
    IndexRebuildRequest | None
        Rebuild request when the index is missing or stale, otherwise ``None``.

    Raises
    ------
    OSError
        If the index files cannot be opened.
    codira.contracts.BackendError
        If the active backend cannot be queried safely.
    RuntimeError
        If the on-disk database is structurally invalid.
    ValueError
        If one of the backend validation checks raises a value error.
    """
    metadata = _read_index_metadata(root)
    if not metadata:
        return IndexRebuildRequest(
            message="[codira] Index not found — building it now...",
            reset_db=False,
            stderr=False,
        )

    current_commit = _get_head_commit(root)
    indexed_commit = metadata.get("commit")
    indexed_schema = metadata.get("schema_version")
    backend = active_index_backend(root=root)

    if indexed_schema != str(backend.version):
        return IndexRebuildRequest(
            message="[codira] Index schema changed — rebuilding...",
            reset_db=True,
            stderr=True,
        )

    if current_commit and indexed_commit != current_commit:
        return IndexRebuildRequest(
            message="[codira] Index outdated (git commit changed) — rebuilding...",
            reset_db=True,
            stderr=True,
        )

    dirty_paths = _git_dirty_indexable_paths(root)
    if dirty_paths:
        conn = backend.open_connection(root)
        try:
            if _dirty_indexable_paths_require_rebuild(
                root,
                dirty_paths,
                backend,
                conn=conn,
            ):
                return IndexRebuildRequest(
                    message="[codira] Index stale "
                    "(working tree changed) — rebuilding...",
                    reset_db=False,
                    stderr=True,
                )
        finally:
            backend.close_connection(conn)

    metadata_decided, metadata_request = _inspect_index_metadata_freshness(
        root,
        metadata,
    )
    if metadata_decided:
        return metadata_request

    conn = backend.open_connection(root)
    try:
        runtime_inventory = backend.load_runtime_inventory(root, conn=conn)
        current_runtime = (str(backend.name), str(backend.version))
        if runtime_inventory is None:
            return IndexRebuildRequest(
                message="[codira] Index stale (plugin inventory missing) "
                "— rebuilding...",
                reset_db=True,
                stderr=True,
            )

        if runtime_inventory[:2] != current_runtime:
            return IndexRebuildRequest(
                message="[codira] Index stale (backend plugin changed) — rebuilding...",
                reset_db=True,
                stderr=True,
            )

        persisted_analyzers = backend.load_analyzer_inventory(root, conn=conn)
        current_analyzers = _current_analyzer_inventory(root=root)
        if persisted_analyzers != current_analyzers:
            return IndexRebuildRequest(
                message="[codira] Index stale "
                "(analyzer plugin inventory changed) — rebuilding...",
                reset_db=True,
                stderr=True,
            )

        indexed_files = _count_indexed_files_for_freshness(
            backend,
            root,
            conn=conn,
        )
        current_files = len(
            list(
                iter_project_files(root, analyzers=active_language_analyzers(root=root))
            )
        )

        if indexed_files != current_files:
            return IndexRebuildRequest(
                message="[codira] Index stale — rebuilding...",
                reset_db=True,
                stderr=True,
            )
        return None
    finally:
        backend.close_connection(conn)


def _run_locked_index_refresh(
    root: Path,
    request: IndexRebuildRequest,
) -> None:
    """
    Rebuild the local index while holding the exclusive mutation lock.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be rebuilt.
    request : IndexRebuildRequest
        Rebuild request describing the status line and reset mode.

    Returns
    -------
    None
        The index is rebuilt and freshness metadata is refreshed in place.
    """
    if request.stderr:
        print(request.message, file=sys.stderr)
    else:
        print(request.message)
    active_index_backend(root=root).initialize(root)
    index_repo(root)
    print("[codira] Index ready", file=sys.stderr)


def _fail_unreadable_index(error: Exception) -> None:
    """
    Terminate after reporting one corrupted or unreadable index.

    Parameters
    ----------
    error : Exception
        Underlying index access failure.

    Returns
    -------
    None
        The function does not return.

    Raises
    ------
    SystemExit
        Always raised with exit status ``1``.
    """
    print("ERROR: repository index is corrupted or unreadable")
    print("Suggested fix: codira index")
    print(f"Details: {error}")
    raise SystemExit(1) from error


def _ensure_index(root: Path) -> None:
    """
    Ensure that the repository index exists and is usable.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose local index should be checked.

    Returns
    -------
    None
        The function returns after confirming or rebuilding the index.

    Raises
    ------
    SystemExit
        If the index cannot be built or is corrupted and unreadable.

    Notes
    -----
    If the on-disk index is missing or stale, the function rebuilds it
    automatically and refreshes the stored Git commit metadata.
    """
    initial_error: Exception | None = None
    try:
        request = _inspect_index_rebuild_request(root)
    except (BackendError, OSError, RuntimeError, ValueError) as error:
        request = None
        initial_error = error

    if request is None and initial_error is None:
        return

    def run_refresh_without_lock(refresh_request: IndexRebuildRequest) -> None:
        """
        Rebuild the index without advisory locking on platforms lacking flock.

        Parameters
        ----------
        refresh_request : IndexRebuildRequest
            Rebuild request already derived from the current on-disk state.

        Returns
        -------
        None
            The index is refreshed in place without cross-process locking.
        """
        try:
            _run_locked_index_refresh(root, refresh_request)
        except (
            BackendError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            print("ERROR: failed to build index automatically")
            print("Run manually: codira index")
            print(f"Details: {error}")
            raise SystemExit(1) from error

    try:
        with acquire_index_lock(root):
            if initial_error is not None:
                try:
                    request = _inspect_index_rebuild_request(root)
                except (
                    BackendError,
                    OSError,
                    RuntimeError,
                    ValueError,
                ) as error:
                    _fail_unreadable_index(error)

            if request is None:
                return

            try:
                refreshed_request = _inspect_index_rebuild_request(root)
            except (
                BackendError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                _fail_unreadable_index(error)

            if refreshed_request is None:
                return

            try:
                _run_locked_index_refresh(root, refreshed_request)
            except (
                BackendError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                print("ERROR: failed to build index automatically")
                print("Run manually: codira index")
                print(f"Details: {error}")
                raise SystemExit(1) from error
    except RuntimeError as error:
        if "fcntl.flock" in str(error) and request is not None:
            run_refresh_without_lock(request)
            return
        _fail_unreadable_index(error)


def _run_plugins(*, root: Path | None = None, as_json: bool = False) -> int:
    """
    Print built-in and entry-point plugin registrations.

    Parameters
    ----------
    as_json : bool, optional
        Whether to render structured JSON output.
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should mark the active backend.

    Returns
    -------
    int
        Zero after printing deterministic plugin diagnostics.
    """
    registrations = plugin_registrations(root=root)

    if as_json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "plugins",
                "status": "ok",
                "results": [
                    {
                        "family": registration.family,
                        "name": registration.name,
                        "active": _plugin_is_active_backend(
                            registration.family,
                            registration.name,
                            root=root,
                        ),
                        "provider": registration.provider,
                        "origin": registration.origin,
                        "source": registration.source,
                        "status": registration.status,
                        "version": registration.version,
                        "entry_point": registration.entry_point,
                        "detail": registration.detail,
                    }
                    for registration in registrations
                ],
            }
        )
        return 0

    for registration in registrations:
        status_tokens: list[str] = [registration.status]
        if _plugin_is_active_backend(
            registration.family,
            registration.name,
            root=root,
        ):
            status_tokens.insert(0, "active")
        line = (
            f"{registration.family}: {registration.name} "
            f"[{', '.join(status_tokens)}] "
            f"provider={registration.provider} "
            f"origin={registration.origin} "
            f"source={registration.source} "
            f"version={registration.version}"
        )
        if registration.entry_point is not None:
            line += f" entry_point={registration.entry_point}"
        if registration.detail is not None:
            line += f" detail={registration.detail}"
        print(line)

    return 0


def _run_plugins_command(args: argparse.Namespace, root: Path) -> int:
    """Run plugin diagnostics through the optional warm daemon.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed plugin command arguments.
    root : pathlib.Path
        Current repository root used for daemon identity.

    Returns
    -------
    int
        Original plugin command exit status.
    """
    routing = _route_eligible_cli_read(root, "cli.plugins", {"as_json": args.json})
    if routing.stdout is not None:
        print(routing.stdout, end="")
        emit_execution_mode(routing, requested=args.execution_mode)
        return cast("int", routing.exit_code)
    result = _run_plugins(root=root, as_json=args.json)
    emit_execution_mode(routing, requested=args.execution_mode)
    return result


def _run_symbol_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the ``sym`` command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the symbol command.
    """
    _ensure_index(root)
    return _run_symbol(
        root,
        args.name,
        prefix=prefix,
        as_json=args.json,
        query_prefix=raw_prefix,
    )


def _run_architecture_report_command(args: argparse.Namespace, root: Path) -> int:
    """Render architecture-report artifacts from the current repository index.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed architecture-report command arguments.
    root : pathlib.Path
        Repository root containing the index and default output location.

    Returns
    -------
    int
        Zero after all mandatory report artifacts are written.
    """
    _ensure_index(root)
    model = build_architecture_model_from_index(root)
    policy = _architecture_policy_from_arguments(args)
    analysis = analyze_architecture_policy(model, policy)
    output = (
        Path(args.output)
        if args.output is not None
        else root / ".codira" / "architecture-report"
    )
    result = write_architecture_artifacts(model, analysis, output)
    print(f"Wrote architecture report: {result.output_dir}")
    if result.warning is not None:
        print(f"[codira] {result.warning}", file=sys.stderr)
    return 0


def _architecture_policy_from_arguments(args: argparse.Namespace) -> ArchitecturePolicy:
    """Parse strict architecture layer policy arguments.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed architecture-report command arguments.

    Returns
    -------
    codira.architecture.ArchitecturePolicy
        Ordered layers and explicit forbidden dependency rules.

    Raises
    ------
    ConfigError
        If one layer or forbidden-rule argument is malformed.
    """
    layers: list[ArchitectureLayer] = []
    for value in args.layer:
        name, separator, path_prefix = value.partition("=")
        if not separator or not name or not path_prefix:
            msg = "Architecture layers must use NAME=PATH_PREFIX."
            raise ConfigError(msg)
        layers.append(ArchitectureLayer(name=name, path_prefix=path_prefix))
    rules: list[ArchitectureForbiddenDependencyRule] = []
    for value in args.forbid:
        fields = value.split(":")
        if len(fields) != 4 or any(not field for field in fields):
            msg = (
                "Architecture forbidden rules must use "
                "RULE:SOURCE_LAYER:DESTINATION_LAYER:SEVERITY."
            )
            raise ConfigError(msg)
        rule_id, source_layer, destination_layer, severity = fields
        rules.append(
            ArchitectureForbiddenDependencyRule(
                rule_id=rule_id,
                source_layer=source_layer,
                destination_layer=destination_layer,
                severity=severity,
            )
        )
    return ArchitecturePolicy(
        layers=tuple(layers),
        forbidden_dependencies=tuple(rules),
    )


def _run_embeddings_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the ``emb`` command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the embedding command.

    Raises
    ------
    ConfigError
        If no query or maintenance submode is supplied, or if maintenance-only
        options are combined with a search query.
    """
    if args.query == "purge":
        return _run_embedding_purge_command(args, root)
    if args.query == "similarity-purge":
        return _run_similarity_purge_command(args, root)
    if args.query == "rebuild":
        return _run_embedding_rebuild_command(args, root)
    if args.query == "reset":
        return _run_embedding_reset_command(args, root)
    if args.query is None:
        msg = "codira emb requires a query, `purge`, `rebuild`, or `reset`"
        raise ConfigError(msg)
    if (
        args.stale
        or args.all_sets
        or args.dry_run
        or args.backend is not None
        or args.older_than is not None
        or args.keep
        or args.yes
        or args.allow_remote_orphans
    ):
        msg = "emb purge options require `codira emb purge`"
        raise ConfigError(msg)
    routing = _route_eligible_cli_read(
        root,
        "cli.emb",
        {
            "query": args.query,
            "limit": args.limit,
            "search_profile": args.search_profile,
            "as_json": args.json,
            "prefix": None if prefix is None else None,
            "query_prefix": raw_prefix,
        },
        supported=prefix is None,
    )
    if routing.stdout is not None:
        print(routing.stdout, end="")
        emit_execution_mode(routing, requested=args.execution_mode)
        return cast("int", routing.exit_code)
    _ensure_index(root)
    result = _run_embeddings(
        EmbeddingCommandRequest(
            root=root,
            query=args.query,
            limit=args.limit,
            prefix=prefix,
            as_json=args.json,
            query_prefix=raw_prefix,
            search_profile=args.search_profile,
        )
    )
    emit_execution_mode(routing, requested=args.execution_mode)
    return result


def _purge_result_payload(result: VectorStorePurgeResult) -> dict[str, object]:
    """
    Convert a vector-store purge result into JSON-compatible output.

    Parameters
    ----------
    result : codira.contracts.VectorStorePurgeResult
        Purge result from the active vector-store plugin.

    Returns
    -------
    dict[str, object]
        JSON-compatible result payload.
    """

    return {
        "store": result.store,
        "mode": result.mode,
        "dry_run": result.dry_run,
        "active_vector_set_id": result.active_vector_set_id,
        "stale_vector_sets": result.stale_vector_sets,
        "kept_stale_vector_sets": result.kept_stale_vector_sets,
        "deleted_vectors": result.deleted_vectors,
        "deleted_cached_vectors": result.deleted_cached_vectors,
        "deleted_pending_vectors": result.deleted_pending_vectors,
        "deleted_vector_sets": result.deleted_vector_sets,
        "size_before_bytes": result.size_before_bytes,
        "size_after_bytes": result.size_after_bytes,
        "note": result.note,
    }


def _run_embedding_rebuild_command(args: argparse.Namespace, root: Path) -> int:
    """Rebuild configured derived similarity state without embedding inference.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed embedding command arguments.
    root : pathlib.Path
        Repository root whose derived semantic state is rebuilt.

    Returns
    -------
    int
        Zero after every authoritative snapshot was rebuilt consistently.

    Raises
    ------
    ConfigError
        If the source vector revision changes while the rebuild is running.
    """
    if (
        args.stale
        or args.all_sets
        or args.dry_run
        or args.backend
        or args.older_than
        or args.keep
        or args.yes
        or getattr(args, "allow_remote_orphans", False)
    ):
        msg = "emb rebuild does not accept purge options"
        raise ConfigError(msg)
    with acquire_index_lock(root):
        result = rebuild_active_similarity_index(root)
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "emb rebuild",
                "status": "ok",
                "index": result.index,
                "source_revisions": result.source_revisions,
            }
        )
    else:
        print(f"Rebuilt similarity index: {result.index}")
        print(f"Source revisions: {result.source_revisions}")
    return 0


def _run_embedding_reset_command(args: argparse.Namespace, root: Path) -> int:
    """Remove confirmed repository-local semantic storage without migration.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed embedding command arguments.
    root : pathlib.Path
        Repository root whose semantic state may be removed.

    Returns
    -------
    int
        Zero after confirmed known vector-store files are removed.

    Raises
    ------
    ConfigError
        If the destructive operation lacks explicit confirmation.
    """
    if not args.yes:
        msg = "codira emb reset requires --yes; semantic state is unrecoverable."
        raise ConfigError(msg)
    if (
        args.stale
        or args.all_sets
        or args.dry_run
        or args.backend
        or args.older_than
        or args.keep
    ):
        msg = "emb reset does not accept purge options"
        raise ConfigError(msg)
    state_root = get_codira_dir(root)
    candidates = (
        state_root / "embeddings.db",
        state_root / "embeddings.db-shm",
        state_root / "embeddings.db-wal",
        state_root / "embeddings.duckdb",
    )
    removed: list[str] = []
    remote_orphan_hashes: tuple[str, ...] = ()
    with acquire_index_lock(root):
        derived_root = state_root / "similarity-indexes"
        qdrant_ledger = derived_root / "qdrant" / "ownership.json"
        if qdrant_ledger.exists():
            active_index = active_similarity_index(root=root)
            if active_index.name != "qdrant":
                if not getattr(args, "allow_remote_orphans", False):
                    msg = (
                        "emb reset stopped because Qdrant ownership remains while "
                        "another similarity index is configured; restore Qdrant for "
                        "cleanup or pass --allow-remote-orphans."
                    )
                    raise ConfigError(msg)
                remote_orphan_hashes = _qdrant_ledger_artifact_hashes(qdrant_ledger)
            else:
                try:
                    purge_active_similarity_index(root, preview=False)
                except (BackendError, ConfigError, OSError, RuntimeError, ValueError):
                    if not getattr(args, "allow_remote_orphans", False):
                        msg = (
                            "emb reset stopped because Qdrant remote cleanup failed; "
                            "retry it or pass --allow-remote-orphans."
                        )
                        raise ConfigError(msg) from None
                    remote_orphan_hashes = _qdrant_ledger_artifact_hashes(qdrant_ledger)
        for path in candidates:
            if path.exists():
                path.unlink()
                removed.append(str(path.relative_to(root)))
        if derived_root.exists():
            shutil.rmtree(derived_root)
            removed.append(str(derived_root.relative_to(root)))
        # Reset is the recovery path for an unavailable or incompatible
        # configured plugin; the command process owns no lasting cache.
        with contextlib.suppress(ValueError):
            active_similarity_index(root=root).reset_runtime_caches()
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "emb reset",
                "status": "ok",
                "removed": removed,
                "remote_orphan_artifact_hashes": remote_orphan_hashes,
                "next": "codira index --full",
            }
        )
    else:
        print("Removed semantic state: " + (", ".join(removed) or "none"))
        if remote_orphan_hashes:
            print(
                "Remote Qdrant artifacts may remain: " + ", ".join(remote_orphan_hashes)
            )
        print("Next: codira index --full")
    return 0


def _qdrant_ledger_artifact_hashes(path: Path) -> tuple[str, ...]:
    """Return opaque artifact hashes retained in a local Qdrant ownership ledger.

    Parameters
    ----------
    path : pathlib.Path
        Local ownership ledger inspected only for explicit reset recovery output.

    Returns
    -------
    tuple[str, ...]
        Sorted opaque artifact hashes, or no hashes when the ledger is unreadable.
    """

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ()
    records = document.get("records") if isinstance(document, dict) else None
    if not isinstance(records, list):
        return ()
    hashes = {
        artifact_hash
        for record in records
        if isinstance(record, dict)
        for collection in (record.get("retained_collections"),)
        if isinstance(collection, list)
        for item in collection
        if isinstance(item, dict)
        for artifact_hash in (item.get("artifact_hash"),)
        if isinstance(artifact_hash, str)
        and artifact_hash
        and all(marker not in artifact_hash for marker in ("/", "\\", "://"))
    }
    return tuple(sorted(hashes))


def _run_similarity_purge_command(args: argparse.Namespace, root: Path) -> int:
    """Inventory or delete selected remote derived similarity-index artifacts.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed embedding maintenance arguments.
    root : pathlib.Path
        Repository root owning the selected remote derived artifacts.

    Returns
    -------
    int
        Zero after a preview or explicitly confirmed cleanup.

    Raises
    ------
    ConfigError
        If vector-store purge options are mixed with remote cleanup.
    """

    if (
        args.stale
        or args.all_sets
        or args.backend is not None
        or args.older_than is not None
        or args.keep
        or getattr(args, "allow_remote_orphans", False)
    ):
        msg = "emb similarity-purge does not accept vector purge options"
        raise ConfigError(msg)
    preview = bool(args.dry_run or not args.yes)
    with acquire_index_lock(root):
        result = purge_active_similarity_index(root, preview=preview)
    payload = {
        "index": result.index,
        "preview": result.preview,
        "removed_artifact_hashes": result.removed_artifact_hashes,
        "skipped_artifact_hashes": result.skipped_artifact_hashes,
    }
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "emb similarity-purge",
                "status": "dry_run" if preview else "ok",
                "result": payload,
            }
        )
    else:
        verb = "Would delete" if preview else "Deleted"
        print(f"Similarity index: {result.index}")
        print(f"{verb} owned remote artifacts: {len(result.removed_artifact_hashes)}")
        print(f"Skipped remote artifacts: {len(result.skipped_artifact_hashes)}")
        if preview and not args.dry_run:
            print("Dry run only; pass --yes to delete.")
    return 0


def _run_embedding_purge_command(args: argparse.Namespace, root: Path) -> int:
    """
    Run ``codira emb purge`` against the active vector store.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed embedding command arguments.
    root : pathlib.Path
        Repository root containing vector-store state.

    Returns
    -------
    int
        Zero after reporting or executing the purge.

    Raises
    ------
    ConfigError
        If purge retention options are invalid or incompatible.
    """

    stale = bool(args.stale)
    all_sets = bool(args.all_sets)
    dry_run = bool(args.dry_run or not args.yes)
    older_than = cast("int | None", args.older_than)
    keep = int(args.keep)
    if not stale and not all_sets:
        stale = True
    if older_than is not None and older_than < 0:
        msg = "--older-than must be >= 0"
        raise ConfigError(msg)
    if keep < 0:
        msg = "--keep must be >= 0"
        raise ConfigError(msg)
    if all_sets and (older_than is not None or keep):
        msg = "--older-than and --keep can only be used with --stale"
        raise ConfigError(msg)
    if not dry_run and not args.yes:
        msg = "codira emb purge requires --yes unless --dry-run is used"
        raise ConfigError(msg)

    context = active_vector_store_context(root, vector_store_name=args.backend)
    result = context.store.purge_vector_sets(
        VectorStorePurgeRequest(
            root=root,
            identity=context.identity,
            config=context.config,
            stale=stale,
            all_sets=all_sets,
            dry_run=dry_run,
            older_than_days=older_than,
            keep=keep,
        )
    )
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "emb purge",
                "status": "dry_run" if result.dry_run else "ok",
                "backend": context.store.name,
                "results": _purge_result_payload(result),
            }
        )
        return 0

    verb = "Would delete" if result.dry_run else "Deleted"
    print(f"Vector store backend: {context.store.name}")
    print(f"{verb} vector sets: {result.deleted_vector_sets}")
    print(f"{verb} materialized vectors: {result.deleted_vectors}")
    print(f"{verb} cached vectors: {result.deleted_cached_vectors}")
    print(f"{verb} pending vectors: {result.deleted_pending_vectors}")
    print(f"Kept stale vector sets: {result.kept_stale_vector_sets}")
    print(
        "Database size: "
        f"{_format_bytes(result.size_before_bytes)} -> "
        f"{_format_bytes(result.size_after_bytes)}"
    )
    if result.note:
        print(f"Note: {result.note}")
    if result.dry_run and not args.dry_run:
        print("Dry run only; pass --yes to delete.")
    return 0


def _run_docs_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the ``docs`` command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the documentation command.
    """
    _ensure_index(root)
    return _run_documentation_lookup(
        DocumentationCommandRequest(
            root=root,
            query=args.query,
            limit=args.limit,
            prefix=prefix,
            as_json=args.json,
            explain=args.explain,
            query_prefix=raw_prefix,
            search_profile=args.search_profile,
        )
    )


def _run_symbol_inventory_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the ``symlist`` command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the symbol inventory command.
    """
    _ensure_index(root)
    return _run_symbol_inventory(
        SymbolInventoryCommandRequest(
            root=root,
            prefix=prefix,
            include_tests=args.include_tests,
            limit=args.limit,
            as_json=args.json,
            query_prefix=raw_prefix,
        )
    )


def _validate_relation_output_flags(
    parser: argparse.ArgumentParser,
    *,
    command: str,
    dot: bool,
    tree: bool,
    as_json: bool,
) -> None:
    """
    Validate mutually constrained output flags for relation commands.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Active top-level parser used for error reporting.
    command : str
        Command name shown in parser errors.
    dot : bool
        Whether DOT output was requested.
    tree : bool
        Whether tree output was requested.
    as_json : bool
        Whether JSON output was requested.

    Returns
    -------
    None
        Invalid flag combinations terminate through ``parser.error``.
    """
    if dot and not tree:
        parser.error(f"--dot requires --tree for {command}")
    if dot and as_json:
        parser.error(f"--dot cannot be combined with --json for {command}")


def _run_relation_subcommand(
    request: RelationSubcommandRequest,
) -> int:
    """
    Run one relation-oriented subcommand after shared validation.

    Parameters
    ----------
    request : RelationSubcommandRequest
        Shared relation-subcommand runtime context.

    Returns
    -------
    int
        Process exit status for the relation command.
    """
    _validate_relation_output_flags(
        request.parser,
        command=request.command,
        dot=request.args.dot,
        tree=request.args.tree,
        as_json=request.args.json,
    )
    _ensure_index(request.root)
    relation_request = RelationCommandRequest(
        root=request.root,
        name=request.args.name,
        module=request.args.module,
        incoming=request.args.incoming,
        as_tree=request.args.tree,
        as_dot=request.args.dot,
        max_depth=request.args.max_depth,
        max_nodes=request.args.max_nodes,
        prefix=request.prefix,
        as_json=request.args.json,
        query_prefix=request.raw_prefix,
    )
    if request.command == "calls":
        return _run_calls(relation_request)
    return _run_refs(relation_request)


def _run_audit_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the docstring audit command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the audit command.
    """
    _ensure_index(root)
    return _run_audit_docstrings(
        root,
        prefix=prefix,
        as_json=args.json,
        query_prefix=raw_prefix,
    )


def _run_context_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
) -> int:
    """
    Run the context command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.

    Returns
    -------
    int
        Zero after printing the rendered context output.
    """
    routing = _route_eligible_cli_read(
        root,
        "cli.ctx",
        {
            "query": args.query,
            "as_json": args.json,
            "as_prompt": args.prompt,
            "explain": args.explain,
            "search_profile": args.search_profile,
        },
        supported=prefix is None,
    )
    if routing.stdout is not None:
        print(routing.stdout, end="")
        emit_execution_mode(routing, requested=args.execution_mode)
        return cast("int", routing.exit_code)
    _ensure_index(root)
    result = context_for(
        ContextRequest(
            root=root,
            query=args.query,
            prefix=prefix,
            as_json=args.json,
            as_prompt=args.prompt,
            explain=args.explain,
            search_profile=args.search_profile,
        )
    )
    print(result)
    emit_execution_mode(routing, requested=args.execution_mode)
    return 0


def _route_eligible_cli_read(
    root: Path,
    operation: str,
    arguments: dict[str, object],
    *,
    supported: bool = True,
) -> CliRouteResult:
    """Attempt one configuration-enabled CLI warm read without mutation.

    Parameters
    ----------
    root : pathlib.Path
        Resolved repository root for the current command.
    operation : str
        Fixed daemon CLI operation name.
    arguments : dict[str, object]
        Path-free request options.
    supported : bool, optional
        Whether this CLI invocation has a daemon-compatible option shape.

    Returns
    -------
    codira.query_daemon_cli.CliRouteResult
        Warm output when available, otherwise the direct/fallback state.
    """
    if not supported:
        return CliRouteResult(mode="direct")
    return route_cli_read(
        root,
        operation,
        arguments,
        enabled=load_effective_config(root=root).query_daemon.enabled,
    )


def build_query_daemon_cli_operations(
    root: Path,
) -> dict[
    str, Callable[[dict[str, object], BackendQueryConnection], dict[str, object]]
]:
    """Build fixed-root daemon handlers for eligible read-only CLI commands.

    Parameters
    ----------
    root : pathlib.Path
        Startup-trusted repository root.

    Returns
    -------
    dict[str, object]
        IPC operation handlers that preserve CLI stdout and exit codes.
    """
    trusted_root = root.resolve()

    def required(arguments: dict[str, object], name: str) -> str:
        """Return one required string request value.

        Parameters
        ----------
        arguments : dict[str, object]
            IPC request arguments.
        name : str
            Required argument name.

        Returns
        -------
        str
            Validated string value.

        Raises
        ------
        TypeError
            If the request value is not a string.
        """
        value = arguments.get(name)
        if not isinstance(value, str):
            msg = f"CLI daemon argument must be a string: {name}."
            raise TypeError(msg)
        return value

    def optional_bool(arguments: dict[str, object], name: str) -> bool:
        """Return one optional boolean request value.

        Parameters
        ----------
        arguments : dict[str, object]
            IPC request arguments.
        name : str
            Optional argument name.

        Returns
        -------
        bool
            Validated value or ``False``.

        Raises
        ------
        TypeError
            If the request value is not boolean.
        """
        value = arguments.get(name, False)
        if not isinstance(value, bool):
            msg = f"CLI daemon argument must be boolean: {name}."
            raise TypeError(msg)
        return value

    def capture(operation: Callable[[], int]) -> dict[str, object]:
        """Capture one existing CLI renderer without changing its output.

        Parameters
        ----------
        operation : collections.abc.Callable[[], int]
            Read-only CLI implementation to execute in the warm worker.

        Returns
        -------
        dict[str, object]
            Captured stdout and original exit code.
        """
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = operation()
        return {"stdout": output.getvalue(), "exit_code": exit_code}

    def context_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute a daemon-owned context read.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free context CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        return capture(
            lambda: _run_context_without_freshness_check(
                trusted_root,
                query=required(arguments, "query"),
                as_json=optional_bool(arguments, "as_json"),
                as_prompt=optional_bool(arguments, "as_prompt"),
                explain=optional_bool(arguments, "explain"),
                search_profile=cast("str | None", arguments.get("search_profile")),
            )
        )

    def embedding_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute a daemon-owned embedding-search read.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free embedding CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        limit = arguments.get("limit")
        if not isinstance(limit, int) or limit <= 0:
            msg = "CLI daemon embedding limit must be positive."
            raise TypeError(msg)
        return capture(
            lambda: _run_embeddings(
                EmbeddingCommandRequest(
                    root=trusted_root,
                    query=required(arguments, "query"),
                    limit=limit,
                    prefix=None,
                    as_json=optional_bool(arguments, "as_json"),
                    query_prefix=cast("str | None", arguments.get("query_prefix")),
                    search_profile=cast("str | None", arguments.get("search_profile")),
                )
            )
        )

    def plugins_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute daemon-owned plugin diagnostics.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free plugin CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        return capture(
            lambda: _run_plugins(
                root=trusted_root, as_json=optional_bool(arguments, "as_json")
            )
        )

    def capabilities_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute daemon-owned capability diagnostics.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free capability CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        return capture(
            lambda: _run_capabilities(
                root=trusted_root,
                as_json=optional_bool(arguments, "as_json"),
                strict=optional_bool(arguments, "strict"),
            )
        )

    return {
        "cli.ctx": context_handler,
        "cli.emb": embedding_handler,
        "cli.plugins": plugins_handler,
        "cli.caps": capabilities_handler,
    }


def _run_context_without_freshness_check(  # noqa: PLR0913
    root: Path,
    *,
    query: str,
    as_json: bool,
    as_prompt: bool,
    explain: bool,
    search_profile: str | None,
) -> int:
    """Render context in the daemon after its generation check already passed.

    Parameters
    ----------
    root : pathlib.Path
        Startup-trusted repository root.
    query : str
        Context retrieval query.
    as_json : bool
        Whether to render structured JSON.
    as_prompt : bool
        Whether to render a prompt.
    explain : bool
        Whether to render retrieval diagnostics.
    search_profile : str | None
        Named similarity-index runtime profile for semantic retrieval channels.

    Returns
    -------
    int
        Zero after emitting the existing context rendering.
    """
    print(
        context_for(
            ContextRequest(
                root=root,
                query=query,
                prefix=None,
                as_json=as_json,
                as_prompt=as_prompt,
                explain=explain,
                search_profile=search_profile,
            )
        )
    )
    return 0


def _config_origin_payload(origin: ConfigOrigin) -> dict[str, object]:
    """
    Convert config origin metadata into a JSON-friendly mapping.

    Parameters
    ----------
    origin : object
        Origin object returned by the config layer.

    Returns
    -------
    dict[str, object]
        JSON-serializable origin payload.
    """

    return {
        "level": origin.level,
        "path": None if origin.path is None else str(origin.path),
        "detail": origin.detail,
    }


def _run_config_init(args: argparse.Namespace, root: Path) -> int:
    """
    Create one generated Codira configuration file.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed config command arguments.
    root : pathlib.Path
        Repository root used for repo-level config paths.

    Returns
    -------
    int
        Zero after writing the config file.
    """

    level = cast("LevelName", args.level)
    profile = cast("ProfileName", args.profile)
    path = config_path(level, root=root)
    write_config_file(path, profile=profile, force=args.force, full=args.full)
    print(f"Wrote {level} config: {path}")
    return 0


def _run_config_dump(args: argparse.Namespace, root: Path) -> int:
    """
    Print one config file or the effective configuration.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed config command arguments.
    root : pathlib.Path
        Repository root used for repo-level config paths.

    Returns
    -------
    int
        Zero after printing the requested config.
    """

    level = cast("LevelName", args.level)
    if level == "effective":
        config = load_effective_config(root=root)
        payload = config_to_mapping(config)
        if args.json:
            _emit_json(
                {
                    "schema_version": QUERY_JSON_SCHEMA_VERSION,
                    "command": "config dump",
                    "status": "ok",
                    "level": level,
                    "results": payload,
                    "origins": {
                        key: _config_origin_payload(origin)
                        for key, origin in sorted(config.origins.items())
                    },
                }
            )
            return 0
        print(render_config_toml(payload), end="")
        return 0

    path = config_path(level, root=root)
    values = load_config_level(level, root=root)
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "config dump",
                "status": "ok",
                "level": level,
                "path": str(path),
                "results": values,
            }
        )
        return 0
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def _run_config_explain(args: argparse.Namespace, root: Path) -> int:
    """
    Explain one effective configuration value and origin.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed config command arguments.
    root : pathlib.Path
        Repository root used for repo-level config resolution.

    Returns
    -------
    int
        Zero after printing explanation output.
    """

    config = load_effective_config(root=root)
    value, origin = explain_key(config, args.key)
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "config explain",
                "status": "ok",
                "key": args.key,
                "value": value,
                "origin": _config_origin_payload(origin),
            }
        )
        return 0
    origin_path = "" if origin.path is None else f" path={origin.path}"
    print(f"{args.key} = {value!r}")
    print(f"origin = {origin.level}{origin_path} ({origin.detail})")
    return 0


def _run_config_validate(args: argparse.Namespace, root: Path) -> int:
    """
    Validate one config level or the effective configuration.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed config command arguments.
    root : pathlib.Path
        Repository root used for repo-level config paths.

    Returns
    -------
    int
        Zero after successful validation.
    """

    level = cast("LevelName", args.level)
    warnings: list[dict[str, object]] = []
    if level == "effective":
        config = load_effective_config(root=root)
        validate_config_mapping(config_to_mapping(config))
        _validate_config_runtime_plugins(config.backend.name, root=root)
        warnings = [
            {"key": warning.key, "reason": warning.reason}
            for warning in validate_plugin_configuration(root=root)
        ]
        path: str | None = None
    else:
        path_obj = config_path(level, root=root)
        validate_config_mapping(load_config_level(level, root=root))
        path = str(path_obj)

    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "config validate",
                "status": "ok_with_warnings" if warnings else "ok",
                "level": level,
                "path": path,
                "warnings": warnings,
            }
        )
        return 0
    print(f"Config valid: {level}" if path is None else f"Config valid: {path}")
    for warning in warnings:
        print(f"Warning: plugins.{warning['key']}: {warning['reason']}")
    return 0


def _validate_config_runtime_plugins(
    backend_name: str,
    *,
    root: Path | None = None,
) -> None:
    """
    Validate plugin names that require registry discovery.

    Parameters
    ----------
    backend_name : str
        Effective backend name to validate.
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in plugin
        diagnostics.

    Returns
    -------
    None
        Runtime plugin references are valid.

    Raises
    ------
    ConfigError
        If the configured backend is not loaded.
    ValueError
        If registry-level analyzer validation fails.
    """

    registrations = plugin_registrations(root=root)
    loaded_backends = {
        registration.name
        for registration in registrations
        if registration.family == "backend" and registration.status == "loaded"
    }
    if backend_name not in loaded_backends:
        available = ", ".join(sorted(loaded_backends))
        msg = (
            f"Unsupported configured backend '{backend_name}'. "
            f"Available backends: {available}"
        )
        raise ConfigError(msg)


def _run_config_command(args: argparse.Namespace, root: Path) -> int:
    """
    Dispatch one ``codira config`` subcommand.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root used for repo-level config paths.

    Returns
    -------
    int
        Process exit status for the config subcommand.

    Raises
    ------
    ConfigError
        If the parsed config action is not supported.
    """

    action = args.config_action or "dump"
    if action == "init":
        return _run_config_init(args, root)
    if action == "dump":
        return _run_config_dump(args, root)
    if action == "explain":
        return _run_config_explain(args, root)
    if action == "validate":
        return _run_config_validate(args, root)
    msg = f"Unsupported config action: {action}"
    raise ConfigError(msg)


def _workspace_payload(
    definition: WorkspaceDefinition | ResolvedWorkspace,
    *,
    status: str,
) -> dict[str, object]:
    """Render one workspace definition as deterministic JSON-compatible data.

    Parameters
    ----------
    definition : object
        Workspace definition or resolved workspace object.
    status : str
        Stable operation status.

    Returns
    -------
    dict[str, object]
        Versioned workspace operation payload.
    """
    return {
        "schema_version": "1.0",
        "status": status,
        "workspace": {
            "name": definition.name,
            "repository_root": str(definition.repository_root),
            "state_root": str(definition.state_root),
            "config_file": (
                str(definition.config_file)
                if definition.config_file is not None
                else None
            ),
        },
    }


def _run_workspace_command(args: argparse.Namespace) -> int:
    """Dispatch deterministic named workspace administration.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed workspace subcommand arguments.

    Returns
    -------
    int
        Zero after a successful workspace operation.
    """
    registry = WorkspaceRegistry.default()
    action = args.workspace_action or "list"
    if action == "list":
        definitions = registry.list_definitions()
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "status": "ok",
            "workspaces": [
                _workspace_payload(definition, status="ok")["workspace"]
                for definition in definitions
            ],
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for definition in definitions:
                print(f"{definition.name}\t{definition.repository_root}")
        return 0
    if action == "migrate":
        plan = preview_workspace_migration(
            registry,
            name=args.name,
            repository_root=Path(args.path),
            state_root=Path(args.state_root) if args.state_root else None,
            config_source=Path(args.config_file) if args.config_file else None,
            config_mode=ConfigMigrationMode(args.config_mode),
            state_source=Path(args.state_source) if args.state_source else None,
            state_mode=StateMigrationMode(args.state_mode),
            model_imports=tuple(
                _parse_model_import(value) for value in args.model_import
            ),
            model_root=Path(args.model_root) if args.model_root else None,
        )
        if args.apply:
            apply_workspace_migration(registry, plan)
        payload = {
            "schema_version": "1.0",
            "status": "applied" if args.apply else "preview",
            "migration": migration_payload(plan),
        }
    elif action in {"add", "update"}:
        definition = registry.with_defaults(
            name=args.name,
            repository_root=Path(args.path),
            state_root=Path(args.state_root) if args.state_root else None,
            config_file=Path(args.config_file) if args.config_file else None,
        )
        if action == "add":
            definition, created = registry.add(definition)
            status = "created" if created else "unchanged"
        else:
            definition = registry.update(definition)
            status = "updated"
        payload = _workspace_payload(definition, status=status)
    elif action == "show":
        payload = _workspace_payload(registry.show(args.name), status="ok")
    elif action == "validate":
        payload = _workspace_payload(registry.validate(args.name), status="valid")
    elif action == "remove":
        payload = _workspace_payload(registry.remove(args.name), status="removed")
    else:
        msg = f"Unsupported workspace action: {action}"
        raise WorkspaceError(msg)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        workspace = payload["workspace"]
        assert isinstance(workspace, dict)
        print(f"{payload['status']}: {workspace['name']}")
    return 0


def _parse_model_import(value: str) -> ModelImport:
    """Parse one explicit model-import CLI value.

    Parameters
    ----------
    value : str
        ``ENGINE|MODEL|VERSION|ARTIFACT|PATH`` import specification.

    Returns
    -------
    codira.migration.ModelImport
        Typed immutable model import request.

    Raises
    ------
    argparse.ArgumentTypeError
        If the value does not contain exactly five non-empty components.
    """
    parts = value.split("|", maxsplit=4)
    if len(parts) != 5 or any(not part.strip() for part in parts):
        msg = "model import must be ENGINE|MODEL|VERSION|ARTIFACT|PATH"
        raise argparse.ArgumentTypeError(msg)
    engine, model, version, artifact, source = parts
    return ModelImport(ModelIdentity(engine, model, version, artifact), Path(source))


def _service_specification(
    *,
    kind: str,
    root: Path,
    runtime_paths: ResolvedRuntimePaths | None,
) -> ServiceSpecification:
    """Build one current direct-path or workspace-bound service specification.

    Parameters
    ----------
    kind : {"daemon", "query-daemon"}
        Foreground service family to specify.
    root : pathlib.Path
        Canonical repository root selected for the command.
    runtime_paths : codira.path_resolution.ResolvedRuntimePaths | None
        Fully resolved command routing, including workspace fingerprint when
        startup selected a workspace.

    Returns
    -------
    codira.daemon.service_spec.ServiceSpecification
        Fixed service definition suitable for rendering and drift checks.
    """
    output_root = get_storage_root(root)
    if (
        runtime_paths is not None
        and runtime_paths.workspace_name is not None
        and runtime_paths.workspace_descriptor_fingerprint is not None
    ):
        return ServiceSpecification.workspace(
            kind=kind,
            root=root,
            output_root=output_root,
            workspace_name=runtime_paths.workspace_name,
            descriptor_fingerprint=runtime_paths.workspace_descriptor_fingerprint,
            effective_config=config_to_mapping(load_effective_config(root=root)),
        )
    if kind == "daemon":
        return ServiceSpecification.indexing(root, output_root)
    return ServiceSpecification.query(root, output_root)


def _run_daemon_command(
    args: argparse.Namespace,
    root: Path,
    specification: ServiceSpecification,
) -> int:
    """Run foreground daemon mode or report unavailable service operations.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed daemon command arguments.
    root : pathlib.Path
        Repository root used to resolve effective daemon configuration.

    Returns
    -------
    int
        Zero after foreground daemon shutdown, otherwise nonzero for disabled
        configuration or a service command not implemented in this slice.
    """

    action = args.daemon_action or "help"
    if action == "run":
        config = load_effective_config(root=root)
        if not config.daemon.enabled:
            print(
                "[codira] daemon run requires daemon.enabled = true.",
                file=sys.stderr,
            )
            return 2
        with contextlib.suppress(KeyboardInterrupt):
            run_foreground_daemon(root, config.daemon)
        return 0
    if action not in {"install", "uninstall", "start", "stop", "status"}:
        print(f"[codira] Unsupported daemon action: {action}", file=sys.stderr)
        return 2
    if sys.platform.startswith("linux"):
        service = (
            SystemdUserService(root, specification=specification)
            if specification.workspace_name is not None
            else SystemdUserService(root)
        )
        service_kind = "systemd user unit"
    elif sys.platform == "darwin":
        service = (
            LaunchdUserAgent(root, specification=specification)
            if specification.workspace_name is not None
            else LaunchdUserAgent(root)
        )
        service_kind = "launchd user agent"
    elif sys.platform == "win32":
        service = (
            WindowsScmService(root, specification=specification)
            if specification.workspace_name is not None
            else WindowsScmService(root)
        )
        service_kind = "Windows SCM service"
    else:
        print(
            "[codira] daemon service commands require Linux systemd, macOS launchd, or Windows SCM services.",
            file=sys.stderr,
        )
        return 2
    if action in {"install", "start"}:
        config = load_effective_config(root=root)
        if not config.daemon.enabled:
            print(
                f"[codira] daemon {action} requires daemon.enabled = true.",
                file=sys.stderr,
            )
            return 2
    if action == "install":
        print(f"[codira] Installed {service_kind}: {service.install()}")
        return 0
    if action == "uninstall":
        service.uninstall()
        print(f"[codira] Uninstalled {service_kind}: {service.identifier}")
        return 0
    if action == "start":
        service.start()
        print(f"[codira] Started {service_kind}: {service.identifier}")
        return 0
    if action == "stop":
        service.stop()
        print(f"[codira] Stopped {service_kind}: {service.identifier}")
        return 0
    status = service.status()
    state = "active" if status.active else "inactive"
    print(f"[codira] {service_kind.capitalize()} {service.identifier}: {state}")
    durable_status = DaemonStatusStore(root).read()
    if durable_status is None:
        print("[codira] No durable daemon status record.")
        return 0
    print(
        "[codira] Daemon reconciliation: "
        f"{durable_status.state.value}; "
        f"pending={durable_status.pending_reconciliation}; "
        f"commit={durable_status.last_reconciled_commit or '-'}; "
        f"last_success={durable_status.last_success_at or '-'}; "
        f"last_error={durable_status.last_error or '-'}"
    )
    return 0


def _run_query_daemon_command(
    args: argparse.Namespace,
    root: Path,
    specification: ServiceSpecification,
) -> int:
    """Run or inspect the repository-local foreground query daemon.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed query-daemon command arguments.
    root : pathlib.Path
        Repository root used to resolve effective configuration.

    Returns
    -------
    int
        Zero after foreground shutdown or status inspection; ``2`` for
        disabled foreground mode or service actions deferred to Slice 6.
    """
    action = args.query_daemon_action or "help"
    config = load_effective_config(root=root)
    identity = QueryDaemonIdentity.from_paths(root, get_storage_root(root))
    if action == "status":
        specification.require_current_definition()
        try:
            status = QueryDaemonStatusStore(identity).read()
        except ValueError as error:
            print(f"[codira] Query daemon status is corrupt: {error}", file=sys.stderr)
            return 2
        if status is None:
            print("[codira] No durable query-daemon status record.")
            return 0
        print(
            "[codira] Query daemon: "
            f"{status.state.value}; "
            f"identity={status.identity}; "
            f"pid={status.pid or '-'}; "
            f"backend={status.backend}; "
            f"embedding={status.embedding_backend}; "
            f"current_generation={status.current_generation or '-'}; "
            f"observed_generation={status.observed_generation or '-'}; "
            f"connection_warm={status.connection_warm}; "
            f"model_warm={status.model_warm}; "
            f"queued={status.queued_requests}; "
            f"active={status.active_requests}; "
            f"fallback={status.fallback_available}; "
            f"last_error={status.last_error or '-'}"
        )
        return 0
    if action == "run":
        if not config.query_daemon.enabled:
            print(
                "[codira] query-daemon run requires query_daemon.enabled = true.",
                file=sys.stderr,
            )
            return 2
        stop_event = Event()
        restore_handlers = install_query_daemon_signal_handlers(stop_event)
        try:
            run_foreground_query_daemon(identity, config, stop_event=stop_event)
        finally:
            restore_handlers()
        return 0
    if action not in {"install", "uninstall", "start", "stop"}:
        print(f"[codira] Unsupported query-daemon action: {action}", file=sys.stderr)
        return 2
    if not config.query_daemon.enabled:
        print(
            f"[codira] query-daemon {action} requires query_daemon.enabled = true.",
            file=sys.stderr,
        )
        return 2
    output_root = get_storage_root(root)
    if sys.platform.startswith("linux"):
        service = (
            SystemdUserService(root, specification=specification)
            if specification.workspace_name is not None
            else QueryDaemonSystemdUserService(root, output_root)
        )
    elif sys.platform == "darwin":
        service = (
            LaunchdUserAgent(root, specification=specification)
            if specification.workspace_name is not None
            else QueryDaemonLaunchdUserAgent(root, output_root)
        )
    elif sys.platform == "win32":
        service = (
            QueryDaemonWindowsScmService(
                root,
                output_root,
                specification=specification,
            )
            if specification.workspace_name is not None
            else QueryDaemonWindowsScmService(root, output_root)
        )
    else:
        print(
            "[codira] query-daemon services require Linux, macOS, or Windows.",
            file=sys.stderr,
        )
        return 2
    if action == "install":
        print(f"[codira] Installed query-daemon service: {service.install()}")
    elif action == "uninstall":
        service.uninstall()
        print(f"[codira] Uninstalled query-daemon service: {service.identifier}")
    elif action == "start":
        service.start()
        print(f"[codira] Started query-daemon service: {service.identifier}")
    else:
        service.stop()
        print(f"[codira] Stopped query-daemon service: {service.identifier}")
    return 0


def _run_calibrate_embeddings(args: argparse.Namespace) -> int:
    """
    Run embeddings calibration and emit or write config-compatible output.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed calibration command arguments.

    Returns
    -------
    int
        Zero after successful calibration output handling.
    """

    result = calibrate_embeddings()
    snippet = render_embeddings_calibration_toml(result)
    output_path = cast("Path | None", args.output)
    if args.write:
        path = user_config_path()
        update_config_file(path, embeddings_config_update(result))
        print(f"Wrote user config: {path}")
        return 0
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(snippet, encoding="utf-8")
        print(f"Wrote calibration output: {output_path}")
        return 0
    print(snippet, end="")
    return 0


def _run_calibrate_command(args: argparse.Namespace) -> int:
    """
    Dispatch one ``codira calibrate`` target command.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    int
        Process exit status for the calibration target.

    Raises
    ------
    ConfigError
        If the parsed calibration target is not supported.
    """

    target = args.calibration_target
    if target == "embeddings":
        return _run_calibrate_embeddings(args)
    msg = f"Unsupported calibration target: {target}"
    raise ConfigError(msg)


def _run_setup(arguments: list[str]) -> int:
    """Delegate setup to the optional coordinated installer provider.

    Parameters
    ----------
    arguments : list[str]
        Arguments forwarded unchanged to the provider.

    Returns
    -------
    int
        Provider exit status, or ``2`` when the provider is unavailable.
    """
    try:
        provider = importlib.import_module("codira_installer.cli")
    except ModuleNotFoundError as exc:
        if exc.name != "codira_installer":
            raise
        print(
            "[codira] setup requires the coordinated codira-installer package. "
            "Install codira-installer with the same Codira version.",
            file=sys.stderr,
        )
        return 2
    provider_main = getattr(provider, "main", None)
    if not callable(provider_main):
        print(
            "[codira] installed setup provider has no callable main.", file=sys.stderr
        )
        return 2
    return int(provider_main(arguments))


def _command_handlers(  # noqa: PLR0913
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
    runtime_paths: ResolvedRuntimePaths | None = None,
) -> dict[str, Callable[[], int]]:
    """
    Build the subcommand dispatch table for the CLI.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    parser : argparse.ArgumentParser
        Active top-level parser.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.
    runtime_paths : codira.path_resolution.ResolvedRuntimePaths | None, optional
        Resolved service routing retained for workspace-aware daemon commands.

    Returns
    -------
    dict[str, collections.abc.Callable[[], int]]
        Command-to-callable dispatch table.
    """
    return {
        "help": lambda: _run_help(parser),
        "setup": lambda: _run_setup(args.setup_args),
        "index": lambda: _run_index(
            IndexCommandRequest(
                root=root,
                full=args.full,
                explain=args.explain,
                require_full_coverage=args.require_full_coverage,
                defer_embeddings=args.defer_embeddings,
                embeddings_only=args.embeddings_only,
                concurrency=args.concurrency,
                jobs=args.jobs,
                as_json=args.json,
            )
        ),
        "cov": lambda: _run_coverage(root, as_json=args.json),
        "sym": lambda: _run_symbol_command(
            args,
            root,
            prefix=prefix,
            raw_prefix=raw_prefix,
        ),
        "symlist": lambda: _run_symbol_inventory_command(
            args,
            root,
            prefix=prefix,
            raw_prefix=raw_prefix,
        ),
        "arch": lambda: _run_architecture_report_command(args, root),
        "emb": lambda: _run_embeddings_command(
            args,
            root,
            prefix=prefix,
            raw_prefix=raw_prefix,
        ),
        "docs": lambda: _run_docs_command(
            args,
            root,
            prefix=prefix,
            raw_prefix=raw_prefix,
        ),
        "calls": lambda: _run_relation_subcommand(
            RelationSubcommandRequest(
                args=args,
                parser=parser,
                root=root,
                prefix=prefix,
                raw_prefix=raw_prefix,
                command="calls",
            )
        ),
        "refs": lambda: _run_relation_subcommand(
            RelationSubcommandRequest(
                args=args,
                parser=parser,
                root=root,
                prefix=prefix,
                raw_prefix=raw_prefix,
                command="refs",
            )
        ),
        "audit": lambda: _run_audit_command(
            args,
            root,
            prefix=prefix,
            raw_prefix=raw_prefix,
        ),
        "plugins": lambda: _run_plugins_command(args, root),
        "caps": lambda: _run_capabilities_command(args, root),
        "ctx": lambda: _run_context_command(
            args,
            root,
            prefix=prefix,
        ),
        "config": lambda: _run_config_command(args, root),
        "workspace": lambda: _run_workspace_command(args),
        "daemon": lambda: _run_daemon_command(
            args,
            root,
            _service_specification(
                kind="daemon",
                root=root,
                runtime_paths=runtime_paths,
            ),
        ),
        "query-daemon": lambda: _run_query_daemon_command(
            args,
            root,
            _service_specification(
                kind="query-daemon",
                root=root,
                runtime_paths=runtime_paths,
            ),
        ),
        "calibrate": lambda: _run_calibrate_command(args),
    }


def main() -> int:
    """
    Dispatch the codira command-line interface.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status for the selected subcommand.
    """
    if (
        len(sys.argv) >= 4
        and sys.argv[1:3] == ["emb", "purge"]
        and any(arg in {"-h", "--help"} for arg in sys.argv[3:])
    ):
        _print_embedding_purge_help()
        return 0

    parser = build_parser()
    args, unknown = parser.parse_known_args()
    if args.command == "setup":
        args.setup_args = sys.argv[2:]
    elif unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    if args.version:
        return _run_version()
    command = args.command or "help"
    storage_context: contextlib.AbstractContextManager[None]
    resolved_paths: ResolvedRuntimePaths | None = None
    if command in _REPO_PATH_COMMANDS:
        resolved_paths = resolve_runtime_paths(parser, args)
        root = resolved_paths.target_root
        storage_context = override_storage_root(root, resolved_paths.output_root)
        repo_config_file = resolved_paths.repo_config_file
    else:
        root = Path.cwd()
        storage_context = contextlib.nullcontext()
        repo_config_file = None
    raw_prefix = getattr(args, "prefix", None)
    prefix = _resolve_prefix_argument(parser, root, raw_prefix)

    try:
        if command not in {"help", "config", "workspace", "calibrate"}:
            ensure_user_config()
        with (
            storage_context,
            override_repo_config_path(repo_config_file),
            effective_config_cache(),
            active_plugin_instance_cache(),
        ):
            handlers = _command_handlers(
                args,
                parser,
                root,
                prefix=prefix,
                raw_prefix=raw_prefix,
                runtime_paths=resolved_paths,
            )
            handler = handlers.get(command)
            if handler is not None:
                return handler()
    except EmbeddingBackendError as exc:
        print(f"[codira] {exc}", file=sys.stderr)
        return 2
    except (BackendError, ConfigError, OSError, RuntimeError, ValueError) as exc:
        print(
            f"[codira] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    parser.print_help()
    return 0
