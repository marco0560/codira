"""Proxy approved MCP requests through the optional warm query daemon.

The proxy is intentionally repository-fixed.  It never accepts a root from an
MCP request and treats every IPC failure as a reason to execute the existing
direct adapter exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, cast

from codira.mcp.adapter import MCPAdapter
from codira.query_daemon import QueryDaemonIdentity
from codira.query_daemon_ipc import QueryDaemonIpcClient, QueryDaemonIpcError
from codira.storage import get_storage_root

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from codira.contracts import BackendQueryConnection


_APPROVED_OPERATIONS = frozenset(
    {
        "capabilities",
        "index_status",
        "symbol",
        "symbols",
        "references",
        "callers",
        "callees",
        "documentation_findings",
        "context_for_task",
        "impact_analysis",
        "repository_map",
    }
)
_Result = TypeVar("_Result")


@dataclass(frozen=True)
class _ConnectionExecutor:
    """Adapt one daemon-owned connection to the MCP adapter query protocol.

    Parameters
    ----------
    connection : codira.contracts.BackendQueryConnection
        Read connection owned by the warm daemon session.
    """

    connection: BackendQueryConnection

    def execute(
        self, operation: Callable[[BackendQueryConnection], _Result]
    ) -> _Result:
        """Execute one adapter read against the daemon-owned connection.

        Parameters
        ----------
        operation : collections.abc.Callable
            Adapter structural read operation.

        Returns
        -------
        _Result
            Result returned by the operation.
        """
        return operation(self.connection)


def build_mcp_operations(root: Path) -> dict[str, Callable[..., dict[str, object]]]:
    """Build explicit fixed-root daemon handlers for all approved MCP tools.

    Parameters
    ----------
    root : pathlib.Path
        Startup-trusted repository root.

    Returns
    -------
    dict[str, collections.abc.Callable]
        Operation handlers suitable for ``QueryDaemonIpcServer``.
    """
    trusted_root = root.resolve()

    def operation(
        name: str,
    ) -> Callable[[dict[str, object], BackendQueryConnection], dict[str, object]]:
        """Bind one validated adapter method to an IPC operation name.

        Parameters
        ----------
        name : str
            Approved MCP adapter method name.

        Returns
        -------
        collections.abc.Callable
            Fixed-root IPC handler.
        """

        def handler(
            arguments: dict[str, object], connection: BackendQueryConnection
        ) -> dict[str, object]:
            """Execute one approved MCP method through a warm connection.

            Parameters
            ----------
            arguments : dict[str, object]
                Path-free MCP tool arguments.
            connection : codira.contracts.BackendQueryConnection
                Daemon-owned warm read connection.

            Returns
            -------
            dict[str, object]
                Existing MCP response envelope.
            """
            adapter = MCPAdapter(
                trusted_root, query_executor=_ConnectionExecutor(connection)
            )
            method = cast("Callable[..., dict[str, object]]", getattr(adapter, name))
            return method(**arguments)

        return handler

    return {name: operation(name) for name in _APPROVED_OPERATIONS}


@dataclass(frozen=True)
class QueryDaemonMCPProxy:
    """Execute MCP tools warmly when compatible, otherwise directly.

    Parameters
    ----------
    root : pathlib.Path
        Startup-trusted repository root.
    direct : codira.mcp.adapter.MCPAdapter | None, optional
        Direct adapter retained for deterministic fallback tests.
    client : codira.query_daemon_ipc.QueryDaemonIpcClient | None, optional
        Repository-identity-bound IPC client retained for tests.
    startup_provenance : collections.abc.Mapping[str, object] | None, optional
        Safe fixed startup identity preserved in every response envelope.
    """

    root: Path
    direct: MCPAdapter | None = None
    client: QueryDaemonIpcClient | None = None
    startup_provenance: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        """Resolve the root and construct only repository-local dependencies.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        root = self.root.resolve()
        object.__setattr__(self, "root", root)
        if self.direct is None:
            object.__setattr__(
                self,
                "direct",
                MCPAdapter(root, startup_provenance=self.startup_provenance),
            )
        if self.client is None:
            identity = QueryDaemonIdentity.from_paths(root, get_storage_root(root))
            object.__setattr__(self, "client", QueryDaemonIpcClient(identity))

    def __getattr__(self, name: str) -> Callable[..., dict[str, object]]:
        """Expose only contract-approved adapter methods to the stdio server.

        Parameters
        ----------
        name : str
            Requested adapter method name.

        Returns
        -------
        collections.abc.Callable
            Warm-or-direct tool implementation.

        Raises
        ------
        AttributeError
            If the requested method is not part of the MCP contract.
        """
        if name not in _APPROVED_OPERATIONS:
            raise AttributeError(name)

        def invoke(*args: object, **kwargs: object) -> dict[str, object]:
            """Route one tool call with a single direct fallback attempt.

            Parameters
            ----------
            args : tuple[object, ...]
                Positional MCP adapter arguments.
            kwargs : dict[str, object]
                Keyword MCP adapter arguments.

            Returns
            -------
            dict[str, object]
                Contract envelope annotated with execution provenance.
            """
            arguments = self._arguments(name, args, kwargs)
            try:
                response = cast("QueryDaemonIpcClient", self.client).request(
                    name, arguments
                )
                result = cast("dict[str, object]", response["result"])
                return self._with_provenance(
                    result,
                    mode="warm",
                    generation=cast("int", response["generation"]),
                )
            except QueryDaemonIpcError as error:
                direct_method = cast(
                    "Callable[..., dict[str, object]]", getattr(self.direct, name)
                )
                result = direct_method(*args, **kwargs)
                direct_provenance = cast("dict[str, object]", result["provenance"])
                return self._with_provenance(
                    result,
                    mode=(
                        "fallback"
                        if cast(
                            "QueryDaemonIpcClient", self.client
                        ).paths.endpoint_path.exists()
                        else "direct"
                    ),
                    generation=cast("int | None", direct_provenance["generation"]),
                    fallback_reason=(
                        type(error).__name__
                        if cast(
                            "QueryDaemonIpcClient", self.client
                        ).paths.endpoint_path.exists()
                        else None
                    ),
                )

        return invoke

    @staticmethod
    def _arguments(
        name: str, args: tuple[object, ...], kwargs: Mapping[str, object]
    ) -> dict[str, object]:
        """Convert the adapter's small positional surface to IPC arguments.

        Parameters
        ----------
        name : str
            Approved MCP tool name.
        args : tuple[object, ...]
            Positional method arguments.
        kwargs : collections.abc.Mapping[str, object]
            Keyword method arguments.

        Returns
        -------
        dict[str, object]
            JSON-compatible path-free request arguments.
        """
        resolved = dict(kwargs)
        if args:
            key = "query" if name == "context_for_task" else "name"
            if len(args) != 1 or key in resolved or not isinstance(args[0], str):
                msg = f"Invalid positional arguments for MCP tool: {name}."
                raise ValueError(msg)
            resolved[key] = args[0]
        return resolved

    def _with_provenance(
        self,
        envelope: dict[str, object],
        *,
        mode: str,
        generation: int | None,
        fallback_reason: str | None = None,
    ) -> dict[str, object]:
        """Copy an envelope with credential-free execution provenance.

        Parameters
        ----------
        envelope : dict[str, object]
            Existing direct MCP response envelope.
        mode : str
            ``warm``, ``direct``, or ``fallback`` execution state.
        generation : int | None
            Warm generation when one served the request.
        fallback_reason : str | None, optional
            Exception class only; no endpoint or credential details.

        Returns
        -------
        dict[str, object]
            Updated response envelope.
        """
        response = dict(envelope)
        previous = cast("dict[str, object]", response["provenance"])
        provenance = dict(previous)
        provenance.update(
            {
                "source": "codira-query-daemon" if mode == "warm" else "codira-core",
                "execution_mode": mode,
                "generation": generation,
            }
        )
        if fallback_reason is not None:
            provenance["fallback_reason"] = fallback_reason
        if self.startup_provenance is not None:
            provenance.update(self.startup_provenance)
        response["provenance"] = provenance
        return response
