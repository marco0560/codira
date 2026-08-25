"""Tests for opportunistic fixed-root CLI warm routing."""

from __future__ import annotations

import contextlib
import io
from typing import TYPE_CHECKING

from codira.cli import (
    EmbeddingCommandRequest,
    _run_capabilities,
    _run_context_without_freshness_check,
    _run_embeddings,
    _run_plugins,
    build_query_daemon_cli_operations,
)
from codira.indexer import index_repo
from codira.query_daemon import QueryDaemonIdentity, QueryRuntime, WarmQuerySession
from codira.query_daemon_cli import route_cli_read
from codira.query_daemon_ipc import QueryDaemonIpcPaths, QueryDaemonIpcServer
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


def _indexed_repository(root: Path) -> None:
    """Create a minimal indexed repository for warm CLI routing tests.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root populated in place.

    Returns
    -------
    None
        The repository has an initialized persistent index.
    """
    (root / "sample.py").write_text(
        "def answer() -> int:\n    return 42\n", encoding="utf-8"
    )
    active_index_backend().initialize(root)
    index_repo(root)


def _captured(operation: Callable[[], int]) -> tuple[int, str]:
    """Capture an existing direct CLI renderer for parity assertions.

    Parameters
    ----------
    operation : collections.abc.Callable[[], int]
        Direct CLI implementation to execute.

    Returns
    -------
    tuple[int, str]
        Original exit code and emitted standard output.
    """
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = operation()
    return exit_code, output.getvalue()


def test_cli_reads_route_warmly_with_direct_output_parity(tmp_path: Path) -> None:
    """Route each initial eligible CLI read through a real warm daemon.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided repository root.

    Returns
    -------
    None
        The test asserts warm stdout, status, and generation parity.
    """
    _indexed_repository(tmp_path)
    identity = QueryDaemonIdentity.from_paths(tmp_path, tmp_path)
    runtime = QueryRuntime(
        identity,
        lambda generation: WarmQuerySession(
            lambda: active_index_backend(root=tmp_path), tmp_path, generation
        ),
    )
    runtime.refresh_from_generation_store()
    daemon = QueryDaemonIpcServer(
        identity, runtime, build_query_daemon_cli_operations(tmp_path)
    )
    daemon.start()
    try:
        calls: dict[str, tuple[Mapping[str, object], Callable[[], int]]] = {
            "cli.ctx": (
                {
                    "query": "answer",
                    "as_json": True,
                    "as_prompt": False,
                    "explain": False,
                    "search_profile": "default",
                },
                lambda: _run_context_without_freshness_check(
                    tmp_path,
                    query="answer",
                    as_json=True,
                    as_prompt=False,
                    explain=False,
                    search_profile="default",
                ),
            ),
            "cli.plugins": (
                {"as_json": True},
                lambda: _run_plugins(root=tmp_path, as_json=True),
            ),
            "cli.emb": (
                {
                    "query": "answer",
                    "limit": 3,
                    "as_json": True,
                    "query_prefix": None,
                },
                lambda: _run_embeddings(
                    EmbeddingCommandRequest(
                        root=tmp_path,
                        query="answer",
                        limit=3,
                        prefix=None,
                        as_json=True,
                        query_prefix=None,
                    )
                ),
            ),
            "cli.caps": (
                {"as_json": True, "strict": False},
                lambda: _run_capabilities(root=tmp_path, as_json=True, strict=False),
            ),
        }
        for operation, (arguments, direct) in calls.items():
            expected_exit, expected_stdout = _captured(direct)
            routed = route_cli_read(tmp_path, operation, arguments, enabled=True)
            assert routed.mode == "warm", operation
            assert routed.exit_code == expected_exit, operation
            assert routed.stdout == expected_stdout, operation
            assert routed.generation == 1, operation
    finally:
        daemon.close()
        runtime.close()


def test_cli_read_routing_preserves_direct_and_fallback_modes(tmp_path: Path) -> None:
    """Keep no-daemon and incompatible-endpoint reads direct and non-blocking.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided repository root.

    Returns
    -------
    None
        The test asserts missing and malformed endpoints never route warm.
    """
    direct = route_cli_read(tmp_path, "cli.plugins", {"as_json": True}, enabled=True)
    assert direct.mode == "direct"
    paths = QueryDaemonIpcPaths(QueryDaemonIdentity.from_paths(tmp_path, tmp_path))
    paths.state_dir.mkdir(parents=True)
    paths.endpoint_path.write_text("{}", encoding="utf-8")

    fallback = route_cli_read(tmp_path, "cli.plugins", {"as_json": True}, enabled=True)

    assert fallback.mode == "fallback"
    assert fallback.stdout is None
    assert fallback.failure == "QueryDaemonProtocolError"
