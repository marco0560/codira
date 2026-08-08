"""Tests for the repository-local warm query-daemon contract declarations."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from codira.cli import main
from codira.index_generation import IndexGenerationStore, transition_record
from codira.query_daemon import (
    QueryDaemonAlreadyRunningError,
    QueryDaemonIdentity,
    QueryDaemonInstanceRegistry,
    QueryDaemonState,
    QueryDaemonStatus,
    QueryRuntime,
    WarmQuerySession,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_query_daemon_identity_isolates_repository_and_output_roots(
    tmp_path: Path,
) -> None:
    """Keep service identities isolated by both canonical runtime paths.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to create distinct repository and output paths.

    Returns
    -------
    None
        The test asserts no two repository/output combinations share identity.
    """
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_output = tmp_path / "first-output"
    second_output = tmp_path / "second-output"

    first = QueryDaemonIdentity.from_paths(first_root, first_output)

    assert (
        first.value != QueryDaemonIdentity.from_paths(second_root, first_output).value
    )
    assert (
        first.value != QueryDaemonIdentity.from_paths(first_root, second_output).value
    )
    assert first.repository_root == first_root.resolve()
    assert first.output_root == first_output.resolve()


def test_query_daemon_registry_rejects_duplicate_foreground_identity(
    tmp_path: Path,
) -> None:
    """Reject a duplicate foreground claim for one service identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to create the claimed identity.

    Returns
    -------
    None
        The test asserts release permits a later replacement claim.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "state")
    registry = QueryDaemonInstanceRegistry()

    registry.claim(identity)
    with pytest.raises(QueryDaemonAlreadyRunningError, match=identity.value):
        registry.claim(identity)
    registry.release(identity)
    registry.claim(identity)


def test_query_daemon_status_defaults_to_no_warmed_generation(tmp_path: Path) -> None:
    """Declare a starting query daemon without runtime-owned state.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to construct the service identity.

    Returns
    -------
    None
        The test asserts deterministic lifecycle defaults.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "state")

    status = QueryDaemonStatus(identity=identity, state=QueryDaemonState.STARTING)

    assert status.generation is None
    assert status.last_error is None


def test_runtime_swaps_only_new_generations_and_closes_previous(tmp_path: Path) -> None:
    """Replace a warm session only after a newer generation is available.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to construct the service identity.

    Returns
    -------
    None
        The test asserts replacement is atomic from the runtime perspective.
    """
    closed: list[int] = []

    class Session:
        """Minimal warmed session test double.

        Parameters
        ----------
        generation : int
            Generation represented by the session.
        """

        def __init__(self, generation: int) -> None:
            """Store the represented generation.

            Parameters
            ----------
            generation : int
                Generation represented by this test session.
            """
            self.generation = generation

        def close(self) -> None:
            """Record deterministic session closure.

            Parameters
            ----------
            None

            Returns
            -------
            None
            """
            closed.append(self.generation)

    runtime = QueryRuntime(
        QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "state"),
        Session,
    )

    assert runtime.refresh(1) is True
    assert runtime.refresh(1) is False
    assert runtime.refresh(2) is True
    runtime.close()

    assert closed == [1, 2]


def test_runtime_refreshes_only_ready_generation_record(tmp_path: Path) -> None:
    """Ignore incomplete handoffs and install a ready generation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository and output roots.

    Returns
    -------
    None
        The test asserts durable generation state controls replacement.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "out")
    store = IndexGenerationStore(
        identity.repository_root, output_root=identity.output_root
    )

    class Session:
        """Minimal generation-only warm session.

        Parameters
        ----------
        generation : int
            Represented index generation.
        """

        def __init__(self, generation: int) -> None:
            """Store one generation.

            Parameters
            ----------
            generation : int
                Represented index generation.
            """
            self.generation = generation

        def close(self) -> None:
            """Close this test session.

            Parameters
            ----------
            None

            Returns
            -------
            None
            """

    runtime = QueryRuntime(identity, Session)
    store.write(
        transition_record(generation=1, state="updating", last_successful_generation=0)
    )
    assert runtime.refresh_from_generation_store() is False
    store.write(
        transition_record(generation=1, state="ready", last_successful_generation=1)
    )
    assert runtime.refresh_from_generation_store() is True
    runtime.close()


def test_warm_session_reuses_one_connection_and_closes_it(tmp_path: Path) -> None:
    """Serialize operations through one worker-owned backend connection.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root passed to the backend.

    Returns
    -------
    None
        The test asserts connection reuse and deterministic closure.
    """
    opened: list[object] = []
    closed: list[object] = []
    connection = object()

    class Backend:
        """Minimal connection-owning backend test double.

        Parameters
        ----------
        None
        """

        def open_connection(self, root: Path) -> object:
            """Return one reusable connection.

            Parameters
            ----------
            root : pathlib.Path
                Repository root supplied by the warm session.

            Returns
            -------
            object
                Shared test connection.
            """
            opened.append(root)
            return connection

        def close_connection(self, candidate: object) -> None:
            """Record the closed shared connection.

            Parameters
            ----------
            candidate : object
                Connection supplied by the warm-session worker.

            Returns
            -------
            None
            """
            closed.append(candidate)

    session = WarmQuerySession(Backend(), tmp_path, 1)
    assert session.submit(lambda conn: conn is connection).result() is True
    assert session.submit(lambda conn: conn is connection).result() is True
    session.close()

    assert opened == [tmp_path]
    assert closed == [connection]


def test_query_daemon_help_and_disabled_run_behavior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Expose all reserved commands while retaining disabled-by-default safety.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to select the temporary repository and CLI arguments.
    tmp_path : pathlib.Path
        Temporary repository root.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts help is complete and ``run`` cannot start by default.
    """
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["codira", "query-daemon", "--help"])

    with pytest.raises(SystemExit, match="0"):
        main()

    output = capsys.readouterr().out
    for action in ("run", "install", "uninstall", "start", "stop", "status"):
        assert f"codira query-daemon {action}" in output

    monkeypatch.setattr(sys, "argv", ["codira", "query-daemon", "run"])

    assert main() == 2
    assert "query_daemon.enabled = true" in capsys.readouterr().err
