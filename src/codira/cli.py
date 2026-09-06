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

import contextlib
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from codira.config import (
    ConfigError,
    effective_config_cache,
    ensure_user_config,
    load_effective_config,
    override_repo_config_path,
)
from codira.contracts import (
    BackendError,
)
from codira.path_resolution import (
    ResolvedRuntimePaths,
    resolve_runtime_paths,
)
from codira.plugin_config import analyzer_inventory_discovery_json
from codira.registry import (
    active_language_analyzers,
    active_plugin_instance_cache,
    configured_index_backend_name,
    plugin_registrations,
)
from codira.semantic.embeddings import (
    EmbeddingBackendError,
)
from codira.storage import (
    override_storage_root,
)
from codira.version import installed_distribution_version, package_version

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable
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


# Compatibility facade: command-family implementations live in focused modules.
from codira.cli_index import (  # noqa: E402
    _ensure_index,
    _read_index_metadata,
    _render_coverage_issues,
    _resolve_prefix_argument,
    _run_coverage,
    _run_index,
    _write_index_metadata,
)
from codira.cli_operations import (  # noqa: E402
    _run_calibrate_command,
    _run_config_command,
    _run_daemon_command,
    _run_plugins,
    _run_plugins_command,
    _run_query_daemon_command,
    _run_setup,
    _run_workspace_command,
    _service_specification,
)
from codira.cli_parser import _print_embedding_purge_help, build_parser  # noqa: E402
from codira.cli_queries import (  # noqa: E402
    _run_architecture_report_command,
    _run_audit_command,
    _run_audit_docstrings,
    _run_context_command,
    _run_context_without_freshness_check,
    _run_docs_command,
    _run_embedding_reset_command,
    _run_embeddings,
    _run_embeddings_command,
    _run_relation_subcommand,
    _run_symbol,
    _run_symbol_command,
    _run_symbol_inventory_command,
    build_query_daemon_cli_operations,
)
from codira.cli_render import (  # noqa: E402
    _run_capabilities,
    _run_capabilities_command,
    _run_help,
)
from codira.cli_requests import (  # noqa: E402
    DocumentationCommandRequest,
    EmbeddingCommandRequest,
    IndexCommandRequest,
    IndexPayloadRequest,
    IndexRebuildRequest,
    RelationCommandRequest,
    RelationCommandSpec,
    RelationSubcommandRequest,
    SymbolInventoryCommandRequest,
)

__all__ = (
    "DocumentationCommandRequest",
    "EmbeddingCommandRequest",
    "IndexCommandRequest",
    "IndexPayloadRequest",
    "IndexRebuildRequest",
    "RelationCommandRequest",
    "RelationCommandSpec",
    "RelationSubcommandRequest",
    "SymbolInventoryCommandRequest",
    "_ensure_index",
    "_read_index_metadata",
    "_render_coverage_issues",
    "_run_audit_docstrings",
    "_run_capabilities",
    "_run_context_without_freshness_check",
    "_run_embedding_reset_command",
    "_run_embeddings",
    "_run_plugins",
    "_run_symbol",
    "_write_index_metadata",
    "build_parser",
    "build_query_daemon_cli_operations",
    "main",
)


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
