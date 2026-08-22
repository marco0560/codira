"""Run Codira's local read-only MCP server over standard input and output."""

from __future__ import annotations

import argparse
import hashlib
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.shared.message import SessionMessage
from pydantic import ValidationError

from codira.config import override_repo_config_path
from codira.mcp.proxy import QueryDaemonMCPProxy
from codira.storage import override_storage_root
from codira.workspace_registry import WorkspaceRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream


@dataclass(frozen=True)
class MCPStartupBinding:
    """Bind one MCP process to immutable startup-resolved runtime paths.

    Parameters
    ----------
    root : pathlib.Path
        Canonical repository root fixed for the process lifetime.
    output_root : pathlib.Path
        Canonical Codira state root fixed for the process lifetime.
    config_file : pathlib.Path | None
        Optional effective repository configuration file fixed at startup.
    workspace_name : str | None
        Registered workspace identity, when startup selected one.
    descriptor_fingerprint : str | None
        SHA-256 fingerprint of the descriptor read at startup.
    """

    root: Path
    output_root: Path
    config_file: Path | None = None
    workspace_name: str | None = None
    descriptor_fingerprint: str | None = None

    def provenance(self) -> Mapping[str, object]:
        """Return safe immutable startup provenance for response envelopes.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Empty for direct-root startup, otherwise workspace identity and
            descriptor fingerprint without exposing filesystem paths.
        """
        if self.workspace_name is None or self.descriptor_fingerprint is None:
            return {}
        return {
            "workspace": self.workspace_name,
            "workspace_descriptor_sha256": self.descriptor_fingerprint,
        }


def resolve_startup_binding(
    *,
    root: Path | None = None,
    workspace: str | None = None,
    registry: WorkspaceRegistry | None = None,
) -> MCPStartupBinding:
    """Resolve one mutually exclusive direct-root or workspace MCP binding.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Direct repository root. ``None`` selects the current directory when no
        workspace is requested.
    workspace : str | None, optional
        Registered workspace identity selected before server construction.
    registry : codira.workspace_registry.WorkspaceRegistry | None, optional
        Injected registry used by deterministic callers and tests.

    Returns
    -------
    MCPStartupBinding
        Fully resolved fixed process binding.

    Raises
    ------
    ValueError
        If direct-root and workspace routing are combined or invalid.
    """
    if root is not None and workspace is not None:
        msg = "MCP --workspace cannot be combined with --root."
        raise ValueError(msg)
    if workspace is None:
        selected_root = (root or Path.cwd()).expanduser().resolve(strict=False)
        if not selected_root.is_dir():
            msg = f"MCP repository root is not a directory: {selected_root}"
            raise ValueError(msg)
        return MCPStartupBinding(root=selected_root, output_root=selected_root)
    selected_registry = registry or WorkspaceRegistry.default()
    resolved = selected_registry.validate(workspace)
    try:
        fingerprint = hashlib.sha256(resolved.descriptor_path.read_bytes()).hexdigest()
    except OSError as exc:
        msg = f"Cannot fingerprint workspace descriptor: {exc}"
        raise ValueError(msg) from exc
    return MCPStartupBinding(
        root=resolved.repository_root,
        output_root=resolved.state_root,
        config_file=resolved.config_file,
        workspace_name=resolved.name,
        descriptor_fingerprint=fingerprint,
    )


@asynccontextmanager
async def _stdio_transport() -> AsyncIterator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ]
]:
    """Bridge MCP JSON-RPC messages over reliable standard input and output.

    Yields
    ------
    tuple
        Receive and send streams accepted by the MCP low-level server.

    Notes
    -----
    The SDK's ``stdio_server`` bridge can block before consuming input under
    the managed Python 3.13 runtime. Reading lines in a worker thread keeps
    the protocol contract while avoiding that transport defect.
    """
    read_sender: MemoryObjectSendStream[SessionMessage | Exception]
    read_receiver: MemoryObjectReceiveStream[SessionMessage | Exception]
    write_sender: MemoryObjectSendStream[SessionMessage]
    write_receiver: MemoryObjectReceiveStream[SessionMessage]
    read_sender, read_receiver = anyio.create_memory_object_stream(0)
    write_sender, write_receiver = anyio.create_memory_object_stream(0)

    async def _read_stdin() -> None:
        """Read newline-delimited client messages into the MCP receive stream.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The coroutine finishes after standard input closes.
        """
        try:
            async with read_sender:
                while line := await anyio.to_thread.run_sync(sys.stdin.buffer.readline):
                    try:
                        message = types.JSONRPCMessage.model_validate_json(line)
                    except ValidationError as error:  # pragma: no cover - SDK parity
                        await read_sender.send(error)
                    else:
                        await read_sender.send(SessionMessage(message))
        except anyio.ClosedResourceError:  # pragma: no cover - shutdown race
            await anyio.lowlevel.checkpoint()

    async def _write_stdout() -> None:
        """Write MCP server messages as newline-delimited JSON-RPC output.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The coroutine finishes after the MCP send stream closes.
        """
        try:
            async with write_receiver:
                async for session_message in write_receiver:
                    payload = session_message.message.model_dump_json(
                        by_alias=True,
                        exclude_none=True,
                    )
                    await anyio.to_thread.run_sync(sys.stdout.write, payload + "\n")
                    await anyio.to_thread.run_sync(sys.stdout.flush)
        except anyio.ClosedResourceError:  # pragma: no cover - shutdown race
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(_read_stdin)
        task_group.start_soon(_write_stdout)
        yield read_receiver, write_sender


async def _run_stdio_server(server: FastMCP) -> None:
    """Serve one FastMCP instance through Codira's reliable stdio transport.

    Parameters
    ----------
    server : mcp.server.fastmcp.FastMCP
        Fully registered MCP server bound to its trusted repository root.

    Returns
    -------
    None
        The coroutine returns after the client closes the stdio session.
    """
    async with _stdio_transport() as (read_stream, write_stream):
        await server._mcp_server.run(  # noqa: SLF001 - required SDK transport boundary
            read_stream,
            write_stream,
            server._mcp_server.create_initialization_options(),
        )


def create_server(
    root: Path,
    *,
    startup_provenance: Mapping[str, object] | None = None,
) -> FastMCP:
    """Create the local MCP server bound to one startup-trusted repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root selected before the stdio server starts.
    startup_provenance : collections.abc.Mapping[str, object] | None, optional
        Safe immutable startup metadata for response provenance.

    Returns
    -------
    mcp.server.fastmcp.FastMCP
        Server exposing the implemented read-only Codira tools.
    """
    adapter = QueryDaemonMCPProxy(root, startup_provenance=startup_provenance)
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

    @server.tool(name="arch")
    def arch(
        cursor: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """Return a bounded architecture model for the trusted repository.

        Parameters
        ----------
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of module inventory entries to return.
        output_budget : int, optional
            Maximum serialized character count for the model payload.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing an architecture model.
        """
        return adapter.arch(
            cursor=cursor,
            limit=limit,
            output_budget=output_budget,
        )

    @server.tool(name="emb")
    def emb(
        query: str,
        prefix: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """Search stored symbol embeddings without maintenance operations.

        Parameters
        ----------
        query : str
            Natural-language text to score against indexed symbols.
        prefix : str | None, optional
            Repository-relative path prefix restricting candidate files.
        limit : int, optional
            Maximum number of ranked embedding matches to return.
        output_budget : int, optional
            Maximum serialized character count for the result payload.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing embedding matches.
        """
        return adapter.emb(
            query,
            prefix=prefix,
            limit=limit,
            output_budget=output_budget,
        )

    @server.tool(name="docs")
    def docs(
        query: str,
        prefix: str | None = None,
        limit: int = 100,
        output_budget: int = 4_000,
    ) -> dict[str, object]:
        """Search stored documentation embeddings without mutating the index.

        Parameters
        ----------
        query : str
            Natural-language text to score against indexed documentation.
        prefix : str | None, optional
            Repository-relative path prefix restricting candidate documents.
        limit : int, optional
            Maximum number of ranked documentation matches to return.
        output_budget : int, optional
            Maximum serialized character count for the result payload.

        Returns
        -------
        dict[str, object]
            Versioned response envelope containing documentation matches.
        """
        return adapter.docs(
            query,
            prefix=prefix,
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
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--root",
        type=Path,
        help="trusted repository root fixed for this server process",
    )
    selector.add_argument(
        "--workspace",
        help="registered workspace fixed for this server process",
    )
    args = parser.parse_args(argv)
    try:
        binding = resolve_startup_binding(root=args.root, workspace=args.workspace)
    except ValueError as exc:
        parser.error(str(exc))
    with (
        override_storage_root(binding.root, binding.output_root),
        override_repo_config_path(binding.config_file),
    ):
        anyio.run(
            _run_stdio_server,
            create_server(
                binding.root,
                startup_provenance=binding.provenance(),
            ),
        )
    return 0
