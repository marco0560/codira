"""Startup-bound read-only MCP tools for a declared repository family.

Parameters
----------
None

Returns
-------
None
    Family tools with explicit member filters and strict request schemas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira.family_runtime import FamilyRuntime

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from codira.family import FamilyDefinition


def create_family_server(family: FamilyDefinition) -> FastMCP:
    """Bind a read-only MCP server to startup-resolved family membership.

    Parameters
    ----------
    family : FamilyDefinition
        Validated manifest and pinned workspace routing.

    Returns
    -------
    FastMCP
        Server exposing family discovery, symbols, references, and evidence.
    """
    from codira.mcp.server import ContractMCP

    runtime = FamilyRuntime(family)
    server = ContractMCP(
        "Codira family",
        instructions="Read-only local repository family fixed at startup. Discover members with capabilities; requests may filter declared workspace names but never supply repository paths.",
        json_response=True,
    )

    @server.tool()
    def capabilities() -> dict[str, object]:
        """Discover family membership, ranking, and exact tool request schemas.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Startup family identity and implemented read-only capability contract.
        """
        return {
            "contract_version": "1.0.0",
            "family": family.name,
            "family_descriptor_sha256": family.descriptor_sha256,
            "members": [
                {"repository": item.member.workspace, "role": item.member.role}
                for item in family.members
            ],
            "repository_model": {
                "selection": "startup_trusted_family",
                "path_inputs": False,
            },
            "read_only": True,
            "ranking": "reciprocal_rank_k60",
            "references": "explicit_manifest_links_only",
            "tools": [
                {"name": tool.name, "request_schema": tool.parameters}
                for tool in server._tool_manager.list_tools()
            ],
        }

    @server.tool()
    def index_status() -> dict[str, object]:
        """Inspect index readiness for every declared member.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Per-member state with unavailable and stale-index reasons.
        """
        return runtime.status()

    @server.tool()
    def context_for_task(
        query: str,
        repositories: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 10,
        allow_partial: bool = False,
    ) -> dict[str, object]:
        """Retrieve complete context across declared family repositories.

        Parameters
        ----------
        query : str
            Task description.
        repositories : list[str] | None, optional
            Declared workspace names to select; omitted selects all members.
        cursor : str | None, optional
            Exact returned continuation for this query and member generation vector.
        limit : int, optional
            Global whole-item page size, one to one hundred.
        allow_partial : bool, optional
            Explicitly permit labeled partial results.

        Returns
        -------
        dict[str, object]
            Repository-qualified context with deterministic global ranking.
        """
        return runtime.query(
            "context",
            query,
            repositories=tuple(repositories or ()),
            cursor=cursor,
            limit=limit,
            allow_partial=allow_partial,
        )

    @server.tool()
    def symbol(
        name: str,
        repositories: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 10,
        allow_partial: bool = False,
    ) -> dict[str, object]:
        """Look up an exact symbol name across declared family repositories.

        Parameters
        ----------
        name : str
            Exact persisted symbol name.
        repositories : list[str] | None, optional
            Declared member names; omitted selects all members.
        cursor : str | None, optional
            Exact returned family continuation.
        limit : int, optional
            Global page size from one to one hundred.
        allow_partial : bool, optional
            Explicitly permit labeled partial results.

        Returns
        -------
        dict[str, object]
            Exact matches retaining independent repository identities.
        """
        return runtime.query(
            "symbol",
            name,
            repositories=tuple(repositories or ()),
            cursor=cursor,
            limit=limit,
            allow_partial=allow_partial,
        )

    @server.tool()
    def references(  # noqa: PLR0913 - MCP parameters are separate schema fields
        name: str,
        direction: str = "outgoing",
        repositories: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 10,
        allow_partial: bool = False,
    ) -> dict[str, object]:
        """Traverse only explicitly declared and validated cross-repository links.

        Parameters
        ----------
        name : str
            Exact name on the queried side of declared links.
        direction : str, optional
            Incoming or outgoing traversal.
        repositories : list[str] | None, optional
            Member filter for the queried side; both endpoints are validated.
        cursor : str | None, optional
            Exact returned family continuation.
        limit : int, optional
            Global whole-edge page size from one to one hundred.
        allow_partial : bool, optional
            Explicitly permit results with excluded links or members.

        Returns
        -------
        dict[str, object]
            Directed references with manifest provenance and qualified endpoints.
        """
        return runtime.query(
            "references",
            name,
            direction=direction,
            repositories=tuple(repositories or ()),
            cursor=cursor,
            limit=limit,
            allow_partial=allow_partial,
        )

    @server.tool()
    def symbol_evidence(identity: str, limit: int = 10) -> dict[str, object]:
        """Expand a family identity within its startup-trusted member.

        Parameters
        ----------
        identity : str
            Family-qualified symbol identity returned by discovery.
        limit : int, optional
            Maximum complete static relation evidence items.

        Returns
        -------
        dict[str, object]
            Whole definition with source hash and repository origin.
        """
        return runtime.evidence(identity, limit=limit)

    for tool in server._tool_manager.list_tools():
        tool.parameters["additionalProperties"] = False
        properties = tool.parameters.get("properties", {})
        if "limit" in properties:
            properties["limit"].update({"minimum": 1, "maximum": 100})
        if "repositories" in properties:
            properties["repositories"] = {
                "anyOf": [
                    {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [item.member.workspace for item in family.members],
                        },
                        "uniqueItems": True,
                    },
                    {"type": "null"},
                ],
                "default": None,
            }
        if "direction" in properties:
            properties["direction"]["enum"] = ["incoming", "outgoing"]
        if "cursor" in properties:
            properties["cursor"]["description"] = (
                "Omit for the first page; otherwise copy page.next_cursor exactly. Any manifest, configuration, or member index change invalidates continuation."
            )
    return server
