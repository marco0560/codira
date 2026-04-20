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
import json
import shutil
import sqlite3
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from codira.capabilities import build_capability_contract
from codira.indexer import (
    CoverageIssue,
    IndexFailure,
    IndexReport,
    IndexWarning,
    audit_repo_coverage,
    index_repo,
)
from codira.prefix import normalize_prefix
from codira.query.context import context_for
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
)
from codira.registry import (
    active_index_backend,
    active_language_analyzers,
    plugin_registrations,
)
from codira.scanner import iter_project_files
from codira.schema import SCHEMA_VERSION
from codira.semantic.embeddings import EmbeddingBackendError, get_embedding_backend
from codira.semantic.search import EmbeddingCandidatesRequest, embedding_candidates
from codira.storage import (
    _read_metadata_file,
    _write_metadata_file,
    acquire_index_lock,
    get_db_path,
    get_metadata_path,
    init_db,
)
from codira.version import installed_distribution_version, package_version

if TYPE_CHECKING:
    import codira.indexer as indexer_types
    from codira.types import DocstringIssueRow

GIT_EXE = shutil.which("git") or "git"
__version__ = package_version()

QUERY_JSON_SCHEMA_VERSION = "1.0"


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


def _current_analyzer_inventory() -> list[tuple[str, str, str]]:
    """
    Return the active analyzer inventory in persisted comparison form.

    Parameters
    ----------
    None

    Returns
    -------
    list[tuple[str, str, str]]
        Active analyzer rows as ``(name, version, discovery_globs_json)``
        ordered by analyzer name.
    """
    return [
        (
            str(analyzer.name),
            str(analyzer.version),
            json.dumps(tuple(analyzer.discovery_globs)),
        )
        for analyzer in sorted(
            active_language_analyzers(),
            key=lambda item: str(item.name),
        )
    ]


def _loaded_plugin_registrations() -> list[tuple[str, str, str, str]]:
    """
    Return loaded plugin registrations in deterministic display order.

    Parameters
    ----------
    None

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
            for registration in plugin_registrations()
            if registration.status == "loaded"
        ],
        key=lambda item: (
            {"first_party": 0, "third_party": 1, "core": 2}.get(item[0], 99),
            {"analyzer": 0, "backend": 1}.get(item[1], 99),
            item[2],
            item[3],
        ),
    )


def _render_version_report() -> str:
    """
    Return the multi-line CLI version report.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Human-readable version report including the core package and installed
        plugins discovered in the current environment.
    """
    lines = [f"codira {__version__}"]
    bundle_version = installed_distribution_version("codira-bundle-official")
    registrations = _loaded_plugin_registrations()
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
            lines.append(f"  {family} {name} {version}")
    elif first_party_plugins:
        lines.append("first-party plugins:")
        for _origin, family, name, version in first_party_plugins:
            lines.append(f"  {family} {name} {version}")

    if third_party_plugins:
        lines.append("third-party plugins:")
        for _origin, family, name, version in third_party_plugins:
            lines.append(f"  {family} {name} {version}")

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
            "  codira sym build_parser\n"
            '  codira emb "schema migration rules"\n'
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
        metavar=("{help,index,cov,sym,emb,calls,refs,audit,ctx,plugins,caps}"),
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
            "  codira index --require-full-coverage"
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
        "--json",
        action="store_true",
        help="Output structured JSON for machine consumption",
    )

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


def _run_index(
    root: Path,
    *,
    full: bool,
    explain: bool,
    require_full_coverage: bool,
    as_json: bool = False,
) -> int:
    """
    Build or refresh the repository index.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose supported source files should be indexed.
    full : bool
        Whether to force a full rebuild instead of incremental reuse.
    explain : bool
        Whether to print per-file indexing decisions after the summary.
    require_full_coverage : bool
        Whether to fail before indexing when canonical directories are not
        fully covered by the active analyzer set.
    as_json : bool, optional
        Whether to render structured JSON output.

    Returns
    -------
    int
        Process exit status for a successful indexing run.
    """
    coverage_issues = audit_repo_coverage(root)
    if require_full_coverage and coverage_issues:
        if as_json:
            _emit_json(
                _index_payload(
                    full=full,
                    explain=explain,
                    require_full_coverage=require_full_coverage,
                    status="coverage_incomplete",
                    report=None,
                    coverage_issues=coverage_issues,
                )
            )
        else:
            _render_required_coverage_failure(root, coverage_issues)
        return 2

    init_db(root)
    report = index_repo(root, full=full)
    _write_index_head_metadata(root)
    if as_json:
        _emit_json(
            _index_payload(
                full=full,
                explain=explain,
                require_full_coverage=require_full_coverage,
                status="ok",
                report=report,
                coverage_issues=report.coverage_issues,
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
    *,
    full: bool,
    explain: bool,
    require_full_coverage: bool,
    status: str,
    report: IndexReport | None,
    coverage_issues: list[CoverageIssue],
) -> dict[str, object]:
    """
    Build the structured JSON payload for one index command run.

    Parameters
    ----------
    full : bool
        Whether the caller requested a full rebuild.
    explain : bool
        Whether the caller requested per-file decision details.
    require_full_coverage : bool
        Whether strict coverage gating was enabled.
    status : str
        Stable status code for the current command outcome.
    report : codira.indexer.IndexReport | None
        Completed index report, or ``None`` when indexing stopped early.
    coverage_issues : list[codira.indexer.CoverageIssue]
        Coverage issues relevant to the command outcome.

    Returns
    -------
    dict[str, object]
        JSON-serializable payload for ``codira index --json``.
    """
    return {
        "schema_version": QUERY_JSON_SCHEMA_VERSION,
        "command": "index",
        "status": status,
        "query": {
            "full": full,
            "explain": explain,
            "require_full_coverage": require_full_coverage,
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
        },
        "coverage_issues": [
            {
                "path": issue.path,
                "directory": issue.directory,
                "suffix": issue.suffix,
                "reason": issue.reason,
            }
            for issue in coverage_issues
        ],
        "warnings": [] if report is None else _index_warning_payload(report.warnings),
        "failures": [] if report is None else _index_failure_payload(report.failures),
        "decisions": (
            []
            if report is None or not explain
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


def _write_index_head_metadata(root: Path) -> None:
    """
    Persist index metadata derived from the current repository head.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose metadata should be updated.

    Returns
    -------
    None
        Index metadata is updated in place.
    """
    commit = _get_head_commit(root)
    metadata = _read_index_metadata(root)
    metadata["schema_version"] = str(SCHEMA_VERSION)
    if commit:
        metadata["commit"] = commit
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
            f"({suffix}, no registered analyzer covers this canonical file)"
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
        Zero when coverage is complete, otherwise one.
    """
    analyzers = sorted(active_language_analyzers(), key=lambda item: str(item.name))
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
        return 0 if not issues else 1

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
    rows = find_symbol(root, name, prefix=prefix)

    if as_json:
        _emit_json(
            _query_payload(
                "sym",
                "ok" if rows else "no_matches",
                {"name": name, "prefix": query_prefix},
                [
                    {
                        "type": symbol_type,
                        "module": module_name,
                        "name": symbol_name,
                        "file": file_path,
                        "lineno": lineno,
                    }
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
            print(f"{symbol_type}: {module_name}.{symbol_name} {file_path}:{lineno}")

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
    root: Path,
    query: str,
    *,
    limit: int,
    prefix: str | None = None,
    as_json: bool = False,
    query_prefix: str | None = None,
) -> int:
    """
    Print embedding-backend metadata and top embedding matches.

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

    Returns
    -------
    int
        Zero when embedding inventory exists, otherwise one.
    """
    backend = get_embedding_backend()
    inventory = embedding_inventory(root)

    if not inventory:
        if as_json:
            _emit_json(
                _query_payload(
                    "emb",
                    "not_indexed",
                    {
                        "text": query,
                        "limit": limit,
                        "prefix": query_prefix,
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
            query=query,
            limit=limit,
            min_score=0.0,
            prefix=prefix,
        )
    )
    if as_json:
        _emit_json(
            _query_payload(
                "emb",
                "ok" if matches else "no_matches",
                {
                    "text": query,
                    "limit": limit,
                    "prefix": query_prefix,
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


def _run_calls(
    root: Path,
    name: str,
    *,
    module: str | None,
    incoming: bool,
    as_tree: bool = False,
    as_dot: bool = False,
    max_depth: int = 2,
    max_nodes: int = 20,
    prefix: str | None = None,
    as_json: bool = False,
    query_prefix: str | None = None,
) -> int:
    """
    Print indexed static call edges for one logical name.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    name : str
        Exact logical caller or callee name to inspect.
    module : str | None
        Optional exact module filter for the selected side of the edge.
    incoming : bool
        Whether to show incoming edges for a callee instead of outgoing edges
        for a caller.
    as_tree : bool, optional
        Whether to render a bounded traversal tree instead of a flat edge list.
    as_dot : bool, optional
        Whether to render the bounded tree as Graphviz DOT.
    max_depth : int, optional
        Maximum traversal depth used by the tree mode.
    max_nodes : int, optional
        Maximum number of rendered nodes used by the tree mode.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict caller files.
    as_json : bool, optional
        Whether to render structured JSON output.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Zero when at least one edge is found, otherwise one.
    """
    if max_depth < 0:
        print("--max-depth must be >= 0", file=sys.stderr)
        return 2
    if max_nodes < 1:
        print("--max-nodes must be >= 1", file=sys.stderr)
        return 2

    if as_tree:
        tree = build_call_tree(
            TreeQueryRequest(
                root=root,
                name=name,
                module=module,
                incoming=incoming,
                prefix=prefix,
                max_depth=max_depth,
                max_nodes=max_nodes,
            )
        )
        if as_json:
            _emit_json(
                _query_payload(
                    "calls",
                    "ok" if tree is not None else "no_matches",
                    {
                        "name": name,
                        "module": module,
                        "incoming": incoming,
                        "tree": True,
                        "max_depth": max_depth,
                        "max_nodes": max_nodes,
                        "prefix": query_prefix,
                    },
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
            direction = "callee" if incoming else "caller"
            if module is None:
                print(f"No call edges found for {direction}: {name}")
            else:
                print(f"No call edges found for {direction}: {module}.{name}")
            return 1

        if as_dot:
            for line in _render_relation_tree_dot(tree, graph_name="codira_calls"):
                print(line)
            return 0

        for line in _render_call_tree_lines(tree):
            print(line)
        if tree.truncated_by_depth or tree.truncated_by_nodes:
            truncation_bits: list[str] = []
            if tree.truncated_by_depth:
                truncation_bits.append(f"max_depth={max_depth}")
            if tree.truncated_by_nodes:
                truncation_bits.append(f"max_nodes={max_nodes}")
            print(f"truncated: {', '.join(truncation_bits)}")
        return 0

    rows = find_call_edges(
        EdgeQueryRequest(
            root=root,
            name=name,
            module=module,
            incoming=incoming,
            prefix=prefix,
        )
    )

    if as_json:
        _emit_json(
            _query_payload(
                "calls",
                "ok" if rows else "no_matches",
                {
                    "name": name,
                    "module": module,
                    "incoming": incoming,
                    "prefix": query_prefix,
                },
                [
                    {
                        "caller_module": caller_module,
                        "caller_name": caller_name,
                        "callee_module": callee_module,
                        "callee_name": callee_name,
                        "resolved": bool(resolved),
                    }
                    for (
                        caller_module,
                        caller_name,
                        callee_module,
                        callee_name,
                        resolved,
                    ) in rows
                ],
            )
        )
        return 0 if rows else 1

    if not rows:
        direction = "callee" if incoming else "caller"
        if module is None:
            print(f"No call edges found for {direction}: {name}")
        else:
            print(f"No call edges found for {direction}: {module}.{name}")
        return 1

    for caller_module, caller_name, callee_module, callee_name, resolved in rows:
        caller = f"{caller_module}.{caller_name}"
        if resolved:
            assert callee_module is not None
            assert callee_name is not None
            callee = f"{callee_module}.{callee_name}"
        else:
            callee = "<unresolved>"
        print(f"{caller} -> {callee}")

    return 0


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
    return {
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
    root: Path,
    name: str,
    *,
    module: str | None,
    incoming: bool,
    as_tree: bool = False,
    as_dot: bool = False,
    max_depth: int = 2,
    max_nodes: int = 20,
    prefix: str | None = None,
    as_json: bool = False,
    query_prefix: str | None = None,
) -> int:
    """
    Print indexed callable-object references for one logical name.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    name : str
        Exact logical owner or referenced target name to inspect.
    module : str | None
        Optional exact module filter for the selected side of the reference.
    incoming : bool
        Whether to show incoming references for a target instead of outgoing
        references for an owner.
    as_tree : bool, optional
        Whether to render a bounded traversal tree instead of a flat reference list.
    as_dot : bool, optional
        Whether to render the bounded tree as Graphviz DOT.
    max_depth : int, optional
        Maximum traversal depth used by the tree mode.
    max_nodes : int, optional
        Maximum number of rendered nodes used by the tree mode.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict owner files.
    as_json : bool, optional
        Whether to render structured JSON output.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Zero when at least one reference is found, otherwise one.
    """
    if max_depth < 0:
        print("--max-depth must be >= 0", file=sys.stderr)
        return 2
    if max_nodes < 1:
        print("--max-nodes must be >= 1", file=sys.stderr)
        return 2

    if as_tree:
        tree = build_ref_tree(
            TreeQueryRequest(
                root=root,
                name=name,
                module=module,
                incoming=incoming,
                prefix=prefix,
                max_depth=max_depth,
                max_nodes=max_nodes,
            )
        )
        if as_json:
            _emit_json(
                _query_payload(
                    "refs",
                    "ok" if tree is not None else "no_matches",
                    {
                        "name": name,
                        "module": module,
                        "incoming": incoming,
                        "tree": True,
                        "max_depth": max_depth,
                        "max_nodes": max_nodes,
                        "prefix": query_prefix,
                    },
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
            direction = "target" if incoming else "owner"
            if module is None:
                print(f"No callable references found for {direction}: {name}")
            else:
                print(f"No callable references found for {direction}: {module}.{name}")
            return 1

        if as_dot:
            for line in _render_relation_tree_dot(tree, graph_name="codira_refs"):
                print(line)
            return 0

        for line in _render_relation_tree_lines(
            tree,
            outgoing_marker="=> ",
            incoming_marker="<= ",
        ):
            print(line)
        if tree.truncated_by_depth or tree.truncated_by_nodes:
            truncation_bits: list[str] = []
            if tree.truncated_by_depth:
                truncation_bits.append(f"max_depth={max_depth}")
            if tree.truncated_by_nodes:
                truncation_bits.append(f"max_nodes={max_nodes}")
            print(f"truncated: {', '.join(truncation_bits)}")
        return 0

    rows = find_callable_refs(
        EdgeQueryRequest(
            root=root,
            name=name,
            module=module,
            incoming=incoming,
            prefix=prefix,
        )
    )

    if as_json:
        _emit_json(
            _query_payload(
                "refs",
                "ok" if rows else "no_matches",
                {
                    "name": name,
                    "module": module,
                    "incoming": incoming,
                    "prefix": query_prefix,
                },
                [
                    {
                        "owner_module": owner_module,
                        "owner_name": owner_name,
                        "target_module": target_module,
                        "target_name": target_name,
                        "resolved": bool(resolved),
                    }
                    for (
                        owner_module,
                        owner_name,
                        target_module,
                        target_name,
                        resolved,
                    ) in rows
                ],
            )
        )
        return 0 if rows else 1

    if not rows:
        direction = "target" if incoming else "owner"
        if module is None:
            print(f"No callable references found for {direction}: {name}")
        else:
            print(f"No callable references found for {direction}: {module}.{name}")
        return 1

    for owner_module, owner_name, target_module, target_name, resolved in rows:
        owner = f"{owner_module}.{owner_name}"
        if resolved:
            assert target_module is not None
            assert target_name is not None
            target = f"{target_module}.{target_name}"
        else:
            target = "<unresolved>"
        print(f"{owner} => {target}")

    return 0


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
        return None


def _build_index_metadata(root: Path) -> dict[str, str]:
    """
    Build the persisted freshness metadata for the current repository head.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose current Git metadata should be recorded.

    Returns
    -------
    dict[str, str]
        Metadata payload containing the schema version and current commit when
        available.
    """
    metadata = {"schema_version": str(SCHEMA_VERSION)}
    commit = _get_head_commit(root)
    if commit:
        metadata["commit"] = commit
    return metadata


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
    sqlite3.Error
        If the SQLite database cannot be queried safely.
    RuntimeError
        If the on-disk database is structurally invalid.
    ValueError
        If one of the backend validation checks raises a value error.
    """
    db_path = get_db_path(root)
    if not db_path.exists():
        return IndexRebuildRequest(
            message="[codira] Index not found — building it now...",
            reset_db=False,
            stderr=False,
        )

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("SELECT 1")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1"
        )
        if cursor.fetchone() is None:
            msg = "empty or invalid database schema"
            raise RuntimeError(msg)

        current_commit = _get_head_commit(root)
        metadata = _read_index_metadata(root)
        indexed_commit = metadata.get("commit")
        indexed_schema = metadata.get("schema_version")

        if indexed_schema != str(SCHEMA_VERSION):
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

        backend = active_index_backend()
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
        current_analyzers = _current_analyzer_inventory()
        if persisted_analyzers != current_analyzers:
            return IndexRebuildRequest(
                message="[codira] Index stale "
                "(analyzer plugin inventory changed) — rebuilding...",
                reset_db=True,
                stderr=True,
            )

        cursor = conn.execute("SELECT COUNT(DISTINCT file_id) FROM symbol_index")
        indexed_files = cursor.fetchone()[0]

        current_files = len(
            list(iter_project_files(root, analyzers=active_language_analyzers()))
        )

        if indexed_files != current_files:
            return IndexRebuildRequest(
                message="[codira] Index stale — rebuilding...",
                reset_db=True,
                stderr=True,
            )
        return None
    finally:
        conn.close()


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
    if request.reset_db:
        init_db(root)
    index_repo(root)
    _write_index_metadata(root, _build_index_metadata(root))
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
    try:
        request = _inspect_index_rebuild_request(root)
    except (OSError, sqlite3.Error, RuntimeError, ValueError):
        request = None

    try:
        with acquire_index_lock(root):
            if request is None:
                try:
                    request = _inspect_index_rebuild_request(root)
                except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
                    _fail_unreadable_index(error)

            if request is None:
                return

            try:
                refreshed_request = _inspect_index_rebuild_request(root)
            except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
                _fail_unreadable_index(error)

            if refreshed_request is None:
                return

            try:
                _run_locked_index_refresh(root, refreshed_request)
            except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
                print("ERROR: failed to build index automatically")
                print("Run manually: codira index")
                print(f"Details: {error}")
                raise SystemExit(1) from error
    except RuntimeError as error:
        _fail_unreadable_index(error)


def _run_plugins(*, as_json: bool = False) -> int:
    """
    Print built-in and entry-point plugin registrations.

    Parameters
    ----------
    as_json : bool, optional
        Whether to render structured JSON output.

    Returns
    -------
    int
        Zero after printing deterministic plugin diagnostics.
    """
    registrations = plugin_registrations()

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
        line = (
            f"{registration.family}: {registration.name} "
            f"[{registration.status}] "
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
    root = Path.cwd()
    raw_prefix = getattr(args, "prefix", None)
    prefix = _resolve_prefix_argument(parser, root, raw_prefix)

    try:
        if args.command in (None, "help"):
            return _run_help(parser)
        if args.command == "index":
            return _run_index(
                root,
                full=args.full,
                explain=args.explain,
                require_full_coverage=args.require_full_coverage,
                as_json=args.json,
            )
        if args.command == "cov":
            return _run_coverage(root, as_json=args.json)
        if args.command == "sym":
            _ensure_index(root)
            return _run_symbol(
                root,
                args.name,
                prefix=prefix,
                as_json=args.json,
                query_prefix=raw_prefix,
            )
        if args.command == "emb":
            _ensure_index(root)
            return _run_embeddings(
                root,
                args.query,
                limit=args.limit,
                prefix=prefix,
                as_json=args.json,
                query_prefix=raw_prefix,
            )
        if args.command == "calls":
            if args.dot and not args.tree:
                parser.error("--dot requires --tree for calls")
            if args.dot and args.json:
                parser.error("--dot cannot be combined with --json for calls")
            _ensure_index(root)
            return _run_calls(
                root,
                args.name,
                module=args.module,
                incoming=args.incoming,
                as_tree=args.tree,
                as_dot=args.dot,
                max_depth=args.max_depth,
                max_nodes=args.max_nodes,
                prefix=prefix,
                as_json=args.json,
                query_prefix=raw_prefix,
            )
        if args.command == "refs":
            if args.dot and not args.tree:
                parser.error("--dot requires --tree for refs")
            if args.dot and args.json:
                parser.error("--dot cannot be combined with --json for refs")
            _ensure_index(root)
            return _run_refs(
                root,
                args.name,
                module=args.module,
                incoming=args.incoming,
                as_tree=args.tree,
                as_dot=args.dot,
                max_depth=args.max_depth,
                max_nodes=args.max_nodes,
                prefix=prefix,
                as_json=args.json,
                query_prefix=raw_prefix,
            )
        if args.command == "audit":
            _ensure_index(root)
            return _run_audit_docstrings(
                root,
                prefix=prefix,
                as_json=args.json,
                query_prefix=raw_prefix,
            )
        if args.command == "plugins":
            return _run_plugins(as_json=args.json)
        if args.command in {"caps", "capabilities"}:
            return _run_capabilities(as_json=args.json, strict=args.strict)
        if args.command == "ctx":
            _ensure_index(root)

            result = context_for(
                root,
                args.query,
                prefix=prefix,
                as_json=args.json,
                as_prompt=args.prompt,
                explain=args.explain,
            )
            print(result)
            return 0
    except EmbeddingBackendError as exc:
        print(f"[codira] {exc}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(
            f"[codira] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    parser.print_help()
    return 0
