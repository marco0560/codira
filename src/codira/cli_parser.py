"""Argument-parser construction and focused CLI help rendering."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from codira.migration import (
    ConfigMigrationMode,
    StateMigrationMode,
)
from codira.path_resolution import (
    CODIRA_CONFIG_FILE_ENV,
    CODIRA_OUTPUT_DIR_ENV,
    CODIRA_TARGET_DIR_ENV,
)
from codira.version import package_version

if TYPE_CHECKING:
    from typing import Protocol

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
        "usage: codira emb purge [-h] [-S | -A] [-n] [-b BACKEND] "
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
        "  -b, --backend BACKEND\n"
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
        "  codira emb purge --stale --backend warehouse --keep 1 --yes  # purge "
        "one registered store's stale sets except the newest one\n"
        "  codira emb purge --all --backend warehouse --yes  # delete every "
        "registered store vector set\n"
    )
