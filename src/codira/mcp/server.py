"""Run Codira's local read-only MCP server over standard input and output."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from codira.mcp.proxy import QueryDaemonMCPProxy

if TYPE_CHECKING:
    from collections.abc import Sequence


def create_server(root: Path) -> FastMCP:
    """Create the local MCP server bound to one startup-trusted repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root selected before the stdio server starts.

    Returns
    -------
    mcp.server.fastmcp.FastMCP
        Server exposing the implemented read-only Codira tools.
    """
    adapter = QueryDaemonMCPProxy(root)
    server = FastMCP(
        "Codira",
        instructions=(
            "Local read-only repository intelligence. "
            "The repository root is fixed when this server starts."
        ),
        json_response=True,
    )

    @server.tool(name="capabilities")
    def capabilities() -> dict[str, object]:
        """Discover the MCP and Codira capability contracts.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Versioned capability contract envelope.
        """
        return adapter.capabilities()

    @server.tool(name="symbol")
    def symbol(
        name: str,
        cursor: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """Look up one exact symbol name in the trusted repository.

        Parameters
        ----------
        name : str
            Exact symbol name to retrieve.
        limit : int, optional
            Maximum number of matches to return.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing symbol matches.
        """
        return adapter.symbol(
            name, cursor=cursor, limit=limit, output_budget=output_budget
        )

    @server.tool(name="index_status")
    def index_status() -> dict[str, object]:
        """Inspect persisted index identity and analyzer-coverage status.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing index status.
        """
        return adapter.index_status()

    @server.tool(name="symbols")
    def symbols(
        cursor: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """List graph-enriched indexed symbols from the trusted repository.

        Parameters
        ----------
        limit : int, optional
            Maximum number of symbols to return.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing symbol inventory rows.
        """
        return adapter.symbols(cursor=cursor, limit=limit, output_budget=output_budget)

    @server.tool(name="references")
    def references(
        name: str,
        direction: str = "outgoing",
        cursor: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """Traverse callable references for one exact logical name.

        Parameters
        ----------
        name : str
            Exact callable name to inspect.
        direction : str, optional
            ``"incoming"`` or ``"outgoing"`` traversal direction.
        limit : int, optional
            Maximum number of reference edges to return.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing reference edges.
        """
        return adapter.references(
            name,
            direction=direction,
            cursor=cursor,
            limit=limit,
            output_budget=output_budget,
        )

    @server.tool(name="callers")
    def callers(
        name: str,
        cursor: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """List static callers for one exact logical callable name.

        Parameters
        ----------
        name : str
            Exact callee name to inspect.
        limit : int, optional
            Maximum number of incoming call edges to return.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing caller edges.
        """
        return adapter.callers(
            name, cursor=cursor, limit=limit, output_budget=output_budget
        )

    @server.tool(name="callees")
    def callees(
        name: str,
        cursor: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """List static callees for one exact logical callable name.

        Parameters
        ----------
        name : str
            Exact caller name to inspect.
        limit : int, optional
            Maximum number of outgoing call edges to return.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing callee edges.
        """
        return adapter.callees(
            name, cursor=cursor, limit=limit, output_budget=output_budget
        )

    @server.tool(name="documentation_findings")
    def documentation_findings(
        cursor: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """List documentation-audit findings from the trusted repository.

        Parameters
        ----------
        limit : int, optional
            Maximum number of findings to return.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing audit findings.
        """
        return adapter.documentation_findings(
            cursor=cursor,
            limit=limit,
            output_budget=output_budget,
        )

    @server.tool(name="context_for_task")
    def context_for_task(query: str, output_budget: int = 4_000) -> dict[str, object]:
        """Build deterministic repository context for one task description.

        Parameters
        ----------
        query : str
            Natural-language task description for context retrieval.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing structured task context.
        """
        return adapter.context_for_task(query, output_budget=output_budget)

    @server.tool(name="impact_analysis")
    def impact_analysis(
        name: str,
        cursor: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """Inspect static dependencies that can be affected by one symbol.

        Parameters
        ----------
        name : str
            Exact symbol name to inspect.
        limit : int, optional
            Maximum number of rows per impact category.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing structural impact rows.
        """
        return adapter.impact_analysis(
            name,
            cursor=cursor,
            limit=limit,
            output_budget=output_budget,
        )

    @server.tool(name="repository_map")
    def repository_map(
        cursor: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """Return a compact deterministic map of the trusted repository.

        Parameters
        ----------
        limit : int, optional
            Maximum number of module summaries to return.
        output_budget : int, optional
            Maximum serialized character count for the map result.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing module summaries, source
            provenance, and truncation metadata.
        """
        return adapter.repository_map(
            cursor=cursor,
            limit=limit,
            output_budget=output_budget,
        )

    return server


def main(argv: Sequence[str] | None = None) -> int:
    """Start the local Codira MCP server with its trusted root fixed at startup.

    Parameters
    ----------
    argv : collections.abc.Sequence[str] | None, optional
        Command-line arguments excluding the executable name. ``None`` reads
        them from the process environment.

    Returns
    -------
    int
        Zero after the stdio server terminates normally.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="trusted repository root fixed for this server process",
    )
    args = parser.parse_args(argv)
    create_server(args.root).run(transport="stdio")
    return 0
