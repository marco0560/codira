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
import ast
import contextlib
import json
import shutil
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.calibration import (
    calibrate_embeddings,
    embeddings_config_update,
    render_embeddings_calibration_toml,
)
from codira.capabilities import build_capability_contract
from codira.config import (
    ConfigError,
    ConfigOrigin,
    LevelName,
    ProfileName,
    config_path,
    config_to_mapping,
    effective_config_cache,
    ensure_user_config,
    explain_key,
    load_config_level,
    load_effective_config,
    render_config_toml,
    update_config_file,
    user_config_path,
    validate_config_mapping,
    write_config_file,
)
from codira.contracts import BackendError
from codira.indexer import (
    CoverageIssue,
    IndexFailure,
    IndexReport,
    IndexWarning,
    audit_repo_coverage,
    index_repo,
)
from codira.path_resolution import (
    CODIRA_OUTPUT_DIR_ENV,
    CODIRA_TARGET_DIR_ENV,
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
from codira.registry import (
    active_index_backend,
    active_language_analyzers,
    active_plugin_instance_cache,
    configured_index_backend_name,
    plugin_registrations,
    validate_plugin_configuration,
)
from codira.scanner import iter_project_files
from codira.semantic.embeddings import EmbeddingBackendError, get_embedding_backend
from codira.semantic.search import (
    DocumentationCandidatesRequest,
    EmbeddingCandidatesRequest,
    documentation_candidates,
    embedding_candidates,
)
from codira.storage import (
    _read_metadata_file,
    _write_metadata_file,
    acquire_index_lock,
    get_metadata_path,
    override_storage_root,
)
from codira.vector_store import active_vector_store_context
from codira.version import installed_distribution_version, package_version

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Protocol

    import codira.indexer as indexer_types
    from codira.contracts import (
        BackendGraphMetric,
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

QUERY_JSON_SCHEMA_VERSION = "1.0"
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
        "emb",
        "docs",
        "calls",
        "refs",
        "audit",
        "ctx",
        "config",
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
    as_json: bool


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
    """

    root: Path
    query: str
    limit: int
    prefix: str | None = None
    as_json: bool = False
    query_prefix: str | None = None


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
    """

    root: Path
    query: str
    limit: int
    prefix: str | None = None
    as_json: bool = False
    explain: bool = False
    query_prefix: str | None = None


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


def _collapsed_ast_source(source: str, node: ast.AST) -> str:
    """
    Return one AST node's source text collapsed to stable single spacing.

    Parameters
    ----------
    source : str
        Full source text containing the node.
    node : ast.AST
        Syntax node whose source should be rendered.

    Returns
    -------
    str
        Source segment with whitespace collapsed deterministically.
    """
    segment = ast.get_source_segment(source, node)
    if segment is None:
        segment = ast.unparse(node)
    return " ".join(segment.split())


def _python_constant_json_detail(
    *,
    file_path: str,
    symbol_name: str,
    lineno: int,
) -> dict[str, object] | None:
    """
    Return detail metadata for one indexed Python constant symbol.

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
        matching module-level constant declaration at the indexed location.
    """
    path = Path(file_path)
    if path.suffix != ".py":
        return None

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=file_path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None

        if isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        else:
            continue

        if not isinstance(target, ast.Name):
            continue
        if target.id != symbol_name or node.lineno != lineno or value is None:
            continue

        annotation: str | None = None
        if isinstance(node, ast.AnnAssign):
            annotation = _collapsed_ast_source(source, node.annotation)

        return {
            "kind": "constant_detail",
            "annotation": annotation,
            "value": _collapsed_ast_source(source, value),
        }

    return None


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
            {"analyzer": 0, "backend": 1}.get(item[1], 99),
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
    Return whether one plugin row is the configured active backend.

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
        ``True`` when the row represents the currently configured backend.
    """

    return family == "backend" and name == configured_index_backend_name(root=root)


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
            "--path",
            help=(
                f"Repository target directory to read (env: {CODIRA_TARGET_DIR_ENV})"
            ),
        )
        command_parser.add_argument(
            "--output-dir",
            help=(
                "Directory under which .codira state is stored "
                f"(env: {CODIRA_OUTPUT_DIR_ENV})"
            ),
        )

    parser = argparse.ArgumentParser(
        prog="codira",
        description=(
            "Index a repository, precompute semantic embeddings, inspect exact "
            "symbols and static relations, and retrieve task-focused context."
        ),
        epilog=(
            "Examples:\n"
            "  codira index\n"
            "  codira index --require-full-coverage\n"
            "  codira index --path /mnt/readonly/repo --output-dir /tmp/codira-run\n"
            "  codira sym build_parser\n"
            '  codira emb "schema migration rules"\n'
            '  codira docs "release process"\n'
            "  codira symlist --limit 20\n"
            '  codira ctx "find schema migration logic"\n'
            "  codira ctx --prompt "
            '"add a regression test for symbol lookup"\n'
            '  codira ctx --explain "why does symbol lookup rank this result?"\n'
            "  codira calls caller --tree\n"
            "  codira refs _retrieve_script_candidates --incoming --tree --dot"
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
            "{help,index,cov,sym,symlist,emb,docs,calls,refs,audit,ctx,plugins,"
            "caps,config,calibrate}"
        ),
    )

    sub.add_parser("help", help="Show help")
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
            "  codira index\n"
            "  codira index --explain\n"
            "  codira index --full\n"
            "  codira index --require-full-coverage\n"
            "  codira index --path /mnt/readonly/repo --output-dir /tmp/codira-run"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    index_parser.add_argument(
        "--full",
        action="store_true",
        help="Force a full rebuild instead of reusing unchanged files",
    )
    index_parser.add_argument(
        "--explain",
        "--verbose",
        dest="explain",
        action="store_true",
        help="Show per-file indexing decisions after the summary",
    )
    index_parser.add_argument(
        "--require-full-coverage",
        action="store_true",
        help=(
            "Fail before indexing when canonical directories contain "
            "uncovered tracked files"
        ),
    )
    index_parser.add_argument(
        "--defer-embeddings",
        action="store_true",
        help="Record index data now and leave eligible embeddings pending",
    )
    index_parser.add_argument(
        "--embeddings-only",
        action="store_true",
        help="Compute pending embeddings without reparsing source files",
    )
    index_parser.add_argument(
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
        epilog=("Examples:\n  codira cov\n  codira cov --json"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    coverage_parser.add_argument(
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
            "  codira sym build_parser\n"
            "  codira sym build_parser --json\n"
            "  codira sym build_parser --prefix src/codira"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    symbol_parser.add_argument("name", help="Exact symbol name to look up")
    symbol_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    symbol_parser.add_argument(
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
            "  codira symlist\n"
            "  codira symlist --json\n"
            "  codira symlist --limit 20\n"
            "  codira symlist --include-tests\n"
            "  codira symlist --prefix src/codira"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    symlist_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    symlist_parser.add_argument(
        "--prefix",
        help="Restrict symbols to files under this repo-root-relative path prefix",
    )
    symlist_parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include symbols from tests modules",
    )
    symlist_parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum number of symbols to print after sorting (default: 1000)",
    )
    _add_repo_path_arguments(symlist_parser)

    embeddings_parser = sub.add_parser(
        "emb",
        help="Inspect embedding-channel matches",
        description=(
            "Inspect the active embedding backend and show top embedding-only "
            "matches for a natural-language query."
        ),
        epilog=(
            "Examples:\n"
            '  codira emb "schema migration rules"\n'
            '  codira emb "schema migration rules" --json\n'
            '  codira emb "numpy docstring sections" --limit 3\n'
            '  codira emb "numpy docstring sections" --prefix '
            "src/codira/query"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    embeddings_parser.add_argument(
        "query",
        help="Natural-language query to score against stored embeddings",
    )
    embeddings_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of embedding matches to print",
    )
    embeddings_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    embeddings_parser.add_argument(
        "--prefix",
        help="Restrict matches to files under this repo-root-relative path prefix",
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
            '  codira docs "release process"\n'
            '  codira docs "release process" --json\n'
            '  codira docs "architecture decisions" --explain\n'
            '  codira docs "plugin loading" --prefix docs'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    docs_parser.add_argument(
        "query",
        help="Natural-language query to score against stored documentation",
    )
    docs_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of documentation matches to print",
    )
    docs_mode_group = docs_parser.add_mutually_exclusive_group()
    docs_mode_group.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    docs_mode_group.add_argument(
        "--explain",
        action="store_true",
        help="Show docs-only retrieval diagnostics",
    )
    docs_parser.add_argument(
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
            "  codira calls caller\n"
            "  codira calls caller --json\n"
            "  codira calls caller --tree\n"
            "  codira calls caller --tree --dot\n"
            "  codira calls imported_helper --module pkg.b --incoming\n"
            "  codira calls caller --prefix src/codira/query"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    calls_parser.add_argument(
        "name",
        help="Exact logical caller or callee name to inspect",
    )
    calls_parser.add_argument(
        "--module",
        help="Restrict the caller or callee side to one exact module",
    )
    calls_parser.add_argument(
        "--incoming",
        action="store_true",
        help="Show callers of the named callee instead of outgoing edges",
    )
    calls_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    calls_parser.add_argument(
        "--dot",
        action="store_true",
        help="Render a bounded tree as Graphviz DOT; requires --tree",
    )
    calls_parser.add_argument(
        "--tree",
        action="store_true",
        help="Render a bounded traversal tree instead of a flat edge list",
    )
    calls_parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="Maximum traversal depth used by --tree (default: 2)",
    )
    calls_parser.add_argument(
        "--max-nodes",
        type=int,
        default=20,
        help="Maximum number of rendered nodes used by --tree (default: 20)",
    )
    calls_parser.add_argument(
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
            "  codira refs helper\n"
            "  codira refs helper --json\n"
            "  codira refs helper --incoming --tree\n"
            "  codira refs helper --tree --dot\n"
            "  codira refs _retrieve_script_candidates --incoming\n"
            "  codira refs imported_helper --module pkg.b --incoming\n"
            "  codira refs helper --prefix src/codira/query"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    refs_parser.add_argument(
        "name",
        help="Exact logical owner or target name to inspect",
    )
    refs_parser.add_argument(
        "--module",
        help="Restrict the owner or target side to one exact module",
    )
    refs_parser.add_argument(
        "--incoming",
        action="store_true",
        help="Show owners of the named target instead of outgoing references",
    )
    refs_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    refs_parser.add_argument(
        "--dot",
        action="store_true",
        help="Render a bounded tree as Graphviz DOT; requires --tree",
    )
    refs_parser.add_argument(
        "--tree",
        action="store_true",
        help="Render a bounded traversal tree instead of a flat reference list",
    )
    refs_parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="Maximum traversal depth used by --tree (default: 2)",
    )
    refs_parser.add_argument(
        "--max-nodes",
        type=int,
        default=20,
        help="Maximum number of rendered nodes used by --tree (default: 20)",
    )
    refs_parser.add_argument(
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
            "  codira audit\n"
            "  codira audit --json\n"
            "  codira audit --prefix src/codira/query"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    audit_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    audit_parser.add_argument(
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
            '  codira ctx "find schema migration logic"\n'
            '  codira ctx --json "schema migration rules"\n'
            '  codira ctx --prompt "add a test for imported calls"\n'
            "  codira ctx --explain "
            '"why does symbol lookup rank this result?"\n'
            '  codira ctx "find schema migration logic" --prefix '
            "src/codira/query\n"
            '  codira ctx "static call graph"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    context_parser.add_argument(
        "query", type=str, help="Natural-language query to retrieve context for"
    )
    mode_group = context_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON (agent mode)",
    )
    mode_group.add_argument(
        "--prompt",
        action="store_true",
        help="Output a Codex-ready deterministic prompt",
    )
    mode_group.add_argument(
        "--explain",
        action="store_true",
        help="Show retrieval routing and merge diagnostics",
    )
    context_parser.add_argument(
        "--prefix",
        help="Restrict retrieval to files under this repo-root-relative path prefix",
    )
    _add_repo_path_arguments(context_parser)

    plugins_parser = sub.add_parser(
        "plugins",
        help="List built-in and third-party plugins",
        description=(
            "List analyzer and backend plugins discovered from built-ins and "
            "installed Python entry points."
        ),
        epilog=("Examples:\n  codira plugins\n  codira plugins --json"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    plugins_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )

    capabilities_parser = sub.add_parser(
        "caps",
        aliases=["capabilities"],
        help="Export the machine-readable capability contract",
        description=(
            "Export codira's deterministic Layer 0 capability contract, "
            "including ontology, command, channel, analyzer, and retrieval "
            "producer declarations."
        ),
        epilog=(
            "Examples:\n"
            "  codira caps\n"
            "  codira caps --json\n"
            "  codira caps --strict --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    capabilities_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    capabilities_parser.add_argument(
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
            "  codira config init\n"
            "  codira config init --level repo --profile low-memory\n"
            "  codira config dump --level effective\n"
            "  codira config explain embeddings.batch_size\n"
            "  codira config validate"
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
    config_init_parser.add_argument(
        "--level",
        choices=("user", "repo", "system"),
        default="user",
        help="Config level to create (default: user)",
    )
    config_init_parser.add_argument(
        "--profile",
        choices=("default", "low-memory", "gpu"),
        default="default",
        help="Generated profile to write (default: default)",
    )
    config_init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config file",
    )
    config_init_parser.add_argument(
        "--full",
        action="store_true",
        help="Include all known first-party plugin options with default values",
    )
    config_dump_parser = config_sub.add_parser(
        "dump",
        help="Print one config level or the effective config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_dump_parser.add_argument(
        "--level",
        choices=("system", "user", "repo", "effective"),
        default="effective",
        help="Config level to dump (default: effective)",
    )
    config_dump_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    config_explain_parser = config_sub.add_parser(
        "explain",
        help="Explain one effective config key",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_explain_parser.add_argument("key", help="Dotted config key to explain")
    config_explain_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )
    config_validate_parser = config_sub.add_parser(
        "validate",
        help="Validate one config level or the effective config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_validate_parser.add_argument(
        "--level",
        choices=("system", "user", "repo", "effective"),
        default="effective",
        help="Config level to validate (default: effective)",
    )
    config_validate_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )

    calibrate_parser = sub.add_parser(
        "calibrate",
        help="Calibrate hardware-aware Codira runtime settings",
        description=(
            "Run deterministic bounded calibration workflows and emit "
            "configuration-compatible output."
        ),
        epilog=(
            "Examples:\n"
            "  codira calibrate embeddings\n"
            "  codira calibrate embeddings --print\n"
            "  codira calibrate embeddings --write\n"
            "  codira calibrate embeddings --output /tmp/codira-embeddings.toml"
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
        "--print",
        dest="print_output",
        action="store_true",
        help="Print the calibrated TOML snippet to stdout",
    )
    calibration_mode.add_argument(
        "--write",
        action="store_true",
        help="Merge calibrated values into the user config file",
    )
    calibration_mode.add_argument(
        "--output",
        type=Path,
        help="Write the calibrated TOML snippet to a file",
    )

    return parser


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


def _run_capabilities(*, as_json: bool, strict: bool) -> int:
    """
    Render the deterministic capability contract.

    Parameters
    ----------
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
    payload = build_capability_contract(strict=strict)
    if as_json:
        _emit_json(payload)
        return 0

    ontology = payload["ontology"]
    commands = payload["commands"]
    analyzers = payload["analyzers"]
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
    if isinstance(validation, dict):
        print(f"validation: {validation['status']}")
        issues = validation.get("issues")
        if isinstance(issues, list) and issues:
            print("validation_issues: " + "; ".join(str(issue) for issue in issues))
    return 0


def _run_index(request: IndexCommandRequest) -> int:
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

    active_index_backend(root=root).initialize(root)
    report = index_repo(
        root,
        full=full,
        embedding_index_mode=effective_embedding_index_mode,
    )
    _write_index_head_metadata(
        root,
        indexed_file_count=report.indexed + report.reused,
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
        return 0
    _render_index_report(root, report)
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
    grouped: OrderedDict[str, tuple[int, OrderedDict[str, None]]] = OrderedDict()
    for issue in issues:
        rel_path = Path(str(issue.path))
        try:
            rel_text = rel_path.relative_to(root).as_posix()
        except ValueError:
            rel_text = str(issue.path)
        top_level_directory = rel_text.split("/", 1)[0]
        count, directories = grouped.setdefault(issue.suffix, (0, OrderedDict()))
        directories[top_level_directory] = None
        grouped[issue.suffix] = (count + 1, directories)
    for suffix, (count, directories) in grouped.items():
        directory_list = ", ".join(directories)
        print(
            "coverage: "
            f"{suffix} x{count} in {directory_list} "
            f"({suffix}, no registered analyzer accepts this file "
            "type/content combination)"
        )


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

    if as_json:
        _emit_json(
            _query_payload(
                "cov",
                "ok" if not issues else "incomplete",
                {
                    "canonical_directories": ["src", "tests", "scripts"],
                },
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
                    constant_detail = _python_constant_json_detail(
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
                        "stable_id": stable_id,
                        "symbol_type": symbol_type,
                        "module": module_name,
                        "name": symbol_name,
                        "file": file_path,
                        "lineno": lineno,
                        "end_lineno": end_lineno,
                    }
                    for (
                        issue_type,
                        message,
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
        )
    )
    if request.as_json:
        _emit_json(
            _query_payload(
                "emb",
                "ok" if matches else "no_matches",
                {
                    "text": request.query,
                    "limit": request.limit,
                    "prefix": request.query_prefix,
                },
                [
                    {
                        "score": round(score, 2),
                        "type": symbol_type,
                        "module": module_name,
                        "name": name,
                        "file": file_path,
                        "lineno": lineno,
                    }
                    for score, (
                        symbol_type,
                        module_name,
                        name,
                        file_path,
                        lineno,
                    ) in matches
                ],
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
        )
    )

    if request.as_json:
        _emit_json(
            _query_payload(
                "docs",
                "ok" if matches else "no_matches",
                {
                    "text": request.query,
                    "limit": request.limit,
                    "prefix": request.query_prefix,
                },
                [
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
                    }
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
                    ) in matches
                ],
                backend={
                    "name": backend.name,
                    "version": backend.version,
                    "dim": backend.dim,
                },
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
    try:
        result = subprocess.run(
            [GIT_EXE, "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


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
        return normalize_prefix(root, prefix)
    except ValueError as exc:
        parser.error(str(exc))


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
    report = index_repo(root)
    _write_index_metadata(
        root,
        _build_index_metadata(
            root,
            indexed_file_count=report.indexed + report.reused,
        ),
    )
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
    """
    _ensure_index(root)
    return _run_embeddings(
        EmbeddingCommandRequest(
            root=root,
            query=args.query,
            limit=args.limit,
            prefix=prefix,
            as_json=args.json,
            query_prefix=raw_prefix,
        )
    )


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
    _ensure_index(root)
    result = context_for(
        ContextRequest(
            root=root,
            query=args.query,
            prefix=prefix,
            as_json=args.json,
            as_prompt=args.prompt,
            explain=args.explain,
        )
    )
    print(result)
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


def _command_handlers(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
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

    Returns
    -------
    dict[str, collections.abc.Callable[[], int]]
        Command-to-callable dispatch table.
    """
    return {
        "help": lambda: _run_help(parser),
        "index": lambda: _run_index(
            IndexCommandRequest(
                root=root,
                full=args.full,
                explain=args.explain,
                require_full_coverage=args.require_full_coverage,
                defer_embeddings=args.defer_embeddings,
                embeddings_only=args.embeddings_only,
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
        "plugins": lambda: _run_plugins(root=root, as_json=args.json),
        "caps": lambda: _run_capabilities(as_json=args.json, strict=args.strict),
        "capabilities": lambda: _run_capabilities(
            as_json=args.json,
            strict=args.strict,
        ),
        "ctx": lambda: _run_context_command(
            args,
            root,
            prefix=prefix,
        ),
        "config": lambda: _run_config_command(args, root),
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
    parser = build_parser()
    args = parser.parse_args()
    if args.version:
        return _run_version()
    command = args.command or "help"
    storage_context: contextlib.AbstractContextManager[None]
    if command in _REPO_PATH_COMMANDS:
        resolved_paths = resolve_runtime_paths(parser, args)
        root = resolved_paths.target_root
        storage_context = override_storage_root(root, resolved_paths.output_root)
    else:
        root = Path.cwd()
        storage_context = contextlib.nullcontext()
    raw_prefix = getattr(args, "prefix", None)
    prefix = _resolve_prefix_argument(parser, root, raw_prefix)

    try:
        if command not in {"help", "config", "calibrate"}:
            ensure_user_config()
        with storage_context, effective_config_cache(), active_plugin_instance_cache():
            handlers = _command_handlers(
                args,
                parser,
                root,
                prefix=prefix,
                raw_prefix=raw_prefix,
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
