"""Route eligible read-only CLI commands through a repository-local daemon."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from codira.query_daemon import QueryDaemonIdentity
from codira.query_daemon_ipc import QueryDaemonIpcClient, QueryDaemonIpcError
from codira.storage import get_storage_root

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


@dataclass(frozen=True)
class CliRouteResult:
    """Describe one optional warm CLI routing attempt.

    Parameters
    ----------
    mode : {"warm", "direct", "fallback"}
        Execution path selected for the command.
    stdout : str | None
        Captured warm command output when routing succeeded.
    exit_code : int | None
        Warm command exit code when routing succeeded.
    generation : int | None
        Served daemon generation when routing succeeded.
    failure : str | None
        Credential-free IPC error class for a fallback.
    """

    mode: str
    stdout: str | None = None
    exit_code: int | None = None
    generation: int | None = None
    failure: str | None = None


def route_cli_read(
    root: Path,
    operation: str,
    arguments: Mapping[str, object],
    *,
    enabled: bool,
) -> CliRouteResult:
    """Attempt one enabled fixed-root CLI read through the warm daemon.

    Parameters
    ----------
    root : pathlib.Path
        Resolved command repository root.
    operation : str
        Explicit daemon CLI operation name.
    arguments : collections.abc.Mapping[str, object]
        Path-free CLI option values.
    enabled : bool
        Whether effective query-daemon routing is enabled.

    Returns
    -------
    CliRouteResult
        Warm output on success, otherwise direct or fallback routing state.
    """
    if not enabled:
        return CliRouteResult(mode="direct")
    identity = QueryDaemonIdentity.from_paths(root, get_storage_root(root))
    client = QueryDaemonIpcClient(identity)
    try:
        response = client.request(operation, arguments)
        result = cast("dict[str, object]", response["result"])
        stdout = result.get("stdout")
        exit_code = result.get("exit_code")
        if not isinstance(stdout, str) or not isinstance(exit_code, int):
            return CliRouteResult(
                mode="fallback",
                failure="QueryDaemonProtocolError",
            )
        return CliRouteResult(
            mode="warm",
            stdout=stdout,
            exit_code=exit_code,
            generation=cast("int", response["generation"]),
        )
    except QueryDaemonIpcError as error:
        endpoint_exists = client.paths.endpoint_path.exists()
        return CliRouteResult(
            mode="fallback" if endpoint_exists else "direct",
            failure=type(error).__name__ if endpoint_exists else None,
        )


def emit_execution_mode(result: CliRouteResult, *, requested: bool) -> None:
    """Write opt-in credential-free routing diagnostics to standard error.

    Parameters
    ----------
    result : CliRouteResult
        Routing state selected for the command.
    requested : bool
        Whether the user requested diagnostic output.

    Returns
    -------
    None
        No output unless diagnostics were requested.
    """
    if not requested:
        return
    import sys

    details = f"[codira] execution={result.mode}"
    if result.generation is not None:
        details += f" generation={result.generation}"
    if result.failure is not None:
        details += f" fallback={result.failure}"
    print(details, file=sys.stderr)
