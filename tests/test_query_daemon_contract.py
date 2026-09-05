"""Tests for the repository-local warm query-daemon contract declarations."""

from __future__ import annotations

import sys
from importlib import import_module
from threading import Event, Thread
from typing import TYPE_CHECKING

import pytest
from codira_backend_sqlite import SQLiteIndexBackend

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
    build_query_runtime,
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


def test_runtime_discards_superseded_concurrent_refresh(tmp_path: Path) -> None:
    """Keep concurrent refresh publication monotonic by generation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to construct the runtime identity.

    Returns
    -------
    None
        The test asserts a delayed older replacement is closed, not published.
    """
    first_started = Event()
    release_first = Event()
    closed: list[int] = []
    outcomes: dict[int, bool] = {}

    class Session:
        """Minimal warmed session with observable closure."""

        def __init__(self, generation: int) -> None:
            """Store the represented generation.

            Parameters
            ----------
            generation : int
                Generation represented by the test session.
            """
            self.generation = generation

        def close(self) -> None:
            """Record closure of this test session.

            Parameters
            ----------
            None

            Returns
            -------
            None
            """
            closed.append(self.generation)

    def factory(generation: int) -> Session:
        """Delay generation one until generation two has published.

        Parameters
        ----------
        generation : int
            Requested warm generation.

        Returns
        -------
        Session
            Constructed test session for the requested generation.
        """
        if generation == 1:
            first_started.set()
            assert release_first.wait(timeout=5)
        return Session(generation)

    runtime = QueryRuntime(
        QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "state"),
        factory,
    )
    first = Thread(target=lambda: outcomes.__setitem__(1, runtime.refresh(1)))
    second = Thread(target=lambda: outcomes.__setitem__(2, runtime.refresh(2)))
    first.start()
    assert first_started.wait(timeout=5)
    second.start()
    second.join(timeout=5)
    release_first.set()
    first.join(timeout=5)

    assert outcomes == {1: False, 2: True}
    assert runtime.generation == 2
    assert closed == [1]
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

    session = WarmQuerySession(Backend, tmp_path, 1)
    assert session.submit(lambda conn: conn is connection).result() is True
    assert session.submit(lambda conn: conn is connection).result() is True
    session.close()

    assert opened == [tmp_path]
    assert closed == [connection]


def test_warm_session_bounds_blocked_operation_and_close(tmp_path: Path) -> None:
    """Bound execution and teardown when a worker-owned operation blocks.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts a timed-out operation does not block a bounded close
        and that cleanup completes after the operation cooperates.
    """
    started = Event()
    release = Event()

    class Backend:
        """Minimal connection backend for a blocked-operation session test."""

        def open_connection(self, root: Path) -> object:
            """Return one opaque test connection.

            Parameters
            ----------
            root : pathlib.Path
                Repository root ignored by this deterministic fixture.

            Returns
            -------
            object
                Opaque worker-owned connection.
            """
            del root
            return object()

        def close_connection(self, connection: object) -> None:
            """Accept cleanup of the opaque test connection.

            Parameters
            ----------
            connection : object
                Worker-owned connection being released.

            Returns
            -------
            None
                The deterministic fixture has no external resources.
            """
            del connection

    session = WarmQuerySession(Backend, tmp_path, 1)
    try:

        def block(_connection: object) -> None:
            """Wait until the test releases the blocked worker operation.

            Parameters
            ----------
            _connection : object
                Opaque worker-owned connection unused by the fixture.

            Returns
            -------
            None
                The operation returns after the release event is set.
            """
            started.set()
            release.wait()

        with pytest.raises(TimeoutError):
            session.execute(block, timeout_seconds=0.01)
        assert started.is_set()
        assert session.close_with_timeout(timeout_seconds=0.01) is False
    finally:
        release.set()
        assert session.close_with_timeout(timeout_seconds=1.0) is True


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_warm_session_supports_first_party_structural_backends(
    tmp_path: Path,
    backend_name: str,
) -> None:
    """Open and close a real warm read session for each supported backend.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository state root.
    backend_name : str
        First-party backend selected for the warm-session lifecycle.

    Returns
    -------
    None
        The test asserts the session worker executes against both backends.
    """
    backend = (
        SQLiteIndexBackend()
        if backend_name == "sqlite"
        else import_module("codira_backend_duckdb").DuckDBIndexBackend()
    )
    backend.initialize(tmp_path)
    session = WarmQuerySession(lambda: backend, tmp_path, 1)
    assert session.submit(lambda _conn: "ready").result() == "ready"
    session.close()


def test_runtime_warms_semantic_dependencies_once_per_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Retain vector and embedding runtime dependencies across warm reads.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace semantic startup with deterministic counters.
    tmp_path : pathlib.Path
        Temporary repository root used for the backend connection.

    Returns
    -------
    None
        The test asserts model warmup occurs once for each replacement session.
    """
    SQLiteIndexBackend().initialize(tmp_path)
    identity = QueryDaemonIdentity.from_paths(tmp_path, tmp_path)
    vector_warmups: list[Path] = []
    embedding_warmups: list[Path] = []

    monkeypatch.setattr(
        "codira.vector_store.active_vector_store_context",
        lambda root: vector_warmups.append(root),
    )
    monkeypatch.setattr(
        "codira.semantic.embeddings.embeddings_enabled",
        lambda *, root: True,
    )
    monkeypatch.setattr(
        "codira.semantic.embeddings.embed_text",
        lambda _text, *, root: embedding_warmups.append(root),
    )

    runtime = build_query_runtime(identity)
    try:
        assert runtime.refresh(1) is True
        assert runtime.execute(lambda _connection: "first") == "first"
        assert runtime.refresh(1) is False
        assert runtime.execute(lambda _connection: "second") == "second"
        assert vector_warmups == [identity.repository_root]
        assert embedding_warmups == [identity.repository_root]

        assert runtime.refresh(2) is True
        assert vector_warmups == [identity.repository_root, identity.repository_root]
        assert embedding_warmups == [identity.repository_root, identity.repository_root]
    finally:
        runtime.close()


def test_failed_replacement_keeps_the_previous_warm_session_available(
    tmp_path: Path,
) -> None:
    """Keep the installed session usable when replacement warmup fails.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root passed to the connection backend.

    Returns
    -------
    None
        The test asserts failed replacement never publishes a partial session.
    """
    connection = object()
    closed: list[object] = []

    class Backend:
        """Minimal backend that keeps a reusable opaque connection.

        Parameters
        ----------
        None
        """

        def open_connection(self, root: Path) -> object:
            """Return the shared connection.

            Parameters
            ----------
            root : pathlib.Path
                Repository root passed by the warm session.

            Returns
            -------
            object
                Opaque reusable test connection.
            """
            del root
            return connection

        def close_connection(self, candidate: object) -> None:
            """Accept deterministic closure of the shared connection.

            Parameters
            ----------
            candidate : object
                Worker-owned connection being closed.

            Returns
            -------
            None
            """
            assert candidate is connection
            closed.append(candidate)

    def failing_warmup() -> None:
        """Raise the intentional replacement startup failure.

        Parameters
        ----------
        None

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            Always, to model an unavailable semantic dependency.
        """
        msg = "warmup failed"
        raise RuntimeError(msg)

    def session_factory(generation: int) -> WarmQuerySession:
        """Build a session whose second generation fails before publication.

        Parameters
        ----------
        generation : int
            Requested replacement generation.

        Returns
        -------
        codira.query_daemon.WarmQuerySession
            Fully warmed session for the requested generation.

        Raises
        ------
        RuntimeError
            When the replacement warmup intentionally fails.
        """
        return WarmQuerySession(
            Backend,
            tmp_path,
            generation,
            warmup=failing_warmup if generation == 2 else None,
        )

    runtime = QueryRuntime(
        QueryDaemonIdentity.from_paths(tmp_path, tmp_path), session_factory
    )
    try:
        assert runtime.refresh(1) is True
        with pytest.raises(RuntimeError, match="warmup failed"):
            runtime.refresh(2)
        assert runtime.execute(lambda candidate: candidate is connection) is True
        assert closed == [connection]
    finally:
        runtime.close()


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
