"""Shared deterministic rendering helpers for the Codira CLI."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING, cast

from codira.capabilities import build_capability_contract
from codira.query_daemon_cli import emit_execution_mode
from codira.version import package_version

if TYPE_CHECKING:
    import argparse
    from pathlib import Path
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
    from codira.cli_queries import _route_eligible_cli_read

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
