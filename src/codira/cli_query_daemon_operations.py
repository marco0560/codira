"""Daemon-owned handlers for eligible read-only CLI operations."""

from __future__ import annotations

import contextlib
import io
from typing import TYPE_CHECKING, cast

from codira.cli_render import _run_capabilities
from codira.cli_requests import EmbeddingCommandRequest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from codira.contracts import BackendQueryConnection


def build_query_daemon_cli_operations(
    root: Path,
    *,
    run_context: Callable[..., int],
    run_embeddings: Callable[[EmbeddingCommandRequest], int],
) -> dict[
    str, Callable[[dict[str, object], BackendQueryConnection], dict[str, object]]
]:
    """Build fixed-root daemon handlers for eligible read-only CLI commands.

    Parameters
    ----------
    root : pathlib.Path
        Startup-trusted repository root.
    run_context : collections.abc.Callable[..., int]
        CLI context renderer whose freshness check is owned by the daemon.
    run_embeddings : collections.abc.Callable[[EmbeddingCommandRequest], int]
        Existing CLI embedding renderer.

    Returns
    -------
    dict[str, object]
        IPC operation handlers that preserve CLI stdout and exit codes.
    """
    trusted_root = root.resolve()

    def required(arguments: dict[str, object], name: str) -> str:
        """Return one required string request value.

        Parameters
        ----------
        arguments : dict[str, object]
            IPC request arguments.
        name : str
            Required argument name.

        Returns
        -------
        str
            Validated string value.

        Raises
        ------
        TypeError
            If the request value is not a string.
        """
        value = arguments.get(name)
        if not isinstance(value, str):
            msg = f"CLI daemon argument must be a string: {name}."
            raise TypeError(msg)
        return value

    def optional_bool(arguments: dict[str, object], name: str) -> bool:
        """Return one optional boolean request value.

        Parameters
        ----------
        arguments : dict[str, object]
            IPC request arguments.
        name : str
            Optional argument name.

        Returns
        -------
        bool
            Validated value or ``False``.

        Raises
        ------
        TypeError
            If the request value is not boolean.
        """
        value = arguments.get(name, False)
        if not isinstance(value, bool):
            msg = f"CLI daemon argument must be boolean: {name}."
            raise TypeError(msg)
        return value

    def capture(operation: Callable[[], int]) -> dict[str, object]:
        """Capture one existing CLI renderer without changing its output.

        Parameters
        ----------
        operation : collections.abc.Callable[[], int]
            Read-only CLI implementation to execute in the warm worker.

        Returns
        -------
        dict[str, object]
            Captured stdout and original exit code.
        """
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = operation()
        return {"stdout": output.getvalue(), "exit_code": exit_code}

    def context_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute a daemon-owned context read.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free context CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        return capture(
            lambda: run_context(
                trusted_root,
                query=required(arguments, "query"),
                as_json=optional_bool(arguments, "as_json"),
                as_prompt=optional_bool(arguments, "as_prompt"),
                explain=optional_bool(arguments, "explain"),
                search_profile=cast("str | None", arguments.get("search_profile")),
            )
        )

    def embedding_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute a daemon-owned embedding-search read.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free embedding CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        limit = arguments.get("limit")
        if not isinstance(limit, int) or limit <= 0:
            msg = "CLI daemon embedding limit must be positive."
            raise TypeError(msg)
        return capture(
            lambda: run_embeddings(
                EmbeddingCommandRequest(
                    root=trusted_root,
                    query=required(arguments, "query"),
                    limit=limit,
                    prefix=None,
                    as_json=optional_bool(arguments, "as_json"),
                    query_prefix=cast("str | None", arguments.get("query_prefix")),
                    search_profile=cast("str | None", arguments.get("search_profile")),
                )
            )
        )

    def plugins_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute daemon-owned plugin diagnostics.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free plugin CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        from codira.cli_operations import _run_plugins

        return capture(
            lambda: _run_plugins(
                root=trusted_root, as_json=optional_bool(arguments, "as_json")
            )
        )

    def capabilities_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute daemon-owned capability diagnostics.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free capability CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        return capture(
            lambda: _run_capabilities(
                root=trusted_root,
                as_json=optional_bool(arguments, "as_json"),
                strict=optional_bool(arguments, "strict"),
            )
        )

    return {
        "cli.ctx": context_handler,
        "cli.emb": embedding_handler,
        "cli.plugins": plugins_handler,
        "cli.caps": capabilities_handler,
    }
