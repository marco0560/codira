"""Lifecycle and durable-observability tests for the foreground query daemon."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from threading import Event, Thread
from time import sleep
from typing import TYPE_CHECKING, cast

import pytest

from codira.config import load_effective_config
from codira.daemon.models import DaemonState, DaemonStatus
from codira.daemon.status_store import DaemonStatusStore
from codira.query_daemon import QueryDaemonIdentity, QueryDaemonState, QueryRuntime
from codira.query_daemon_lifecycle import (
    QueryDaemonProcessStatus,
    QueryDaemonStatusStore,
    run_foreground_query_daemon,
)

if TYPE_CHECKING:
    from pathlib import Path


class _Runtime:
    """Minimal warm runtime with controllable durable-generation behavior.

    Parameters
    ----------
    generation : int | None, optional
        Generation visible after a refresh.
    """

    def __init__(self, generation: int | None = None) -> None:
        """Initialize a closed-state and current-generation test runtime.

        Parameters
        ----------
        generation : int | None, optional
            Generation returned after refresh.

        Returns
        -------
        None
        """
        self.generation = generation
        self.closed = False

    def refresh_from_generation_store(self) -> bool:
        """Report that this test runtime already represents its generation.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            ``False`` because no replacement is installed by the test double.
        """
        return False

    def close(self) -> None:
        """Record deterministic lifecycle resource closure.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        self.closed = True


class _Server:
    """No-network IPC server double used by foreground lifecycle tests.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Fixed lifecycle identity.
    runtime : _Runtime
        Runtime retained for construction parity.
    """

    def __init__(self, identity: QueryDaemonIdentity, runtime: _Runtime) -> None:
        """Initialize start/close state for one fake server.

        Parameters
        ----------
        identity : codira.query_daemon.QueryDaemonIdentity
            Fixed lifecycle identity.
        runtime : _Runtime
            Runtime retained for construction parity.

        Returns
        -------
        None
        """
        self.identity = identity
        self.runtime = runtime
        self.started = False
        self.closed = False

    def start(self) -> None:
        """Record foreground IPC startup.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        self.started = True

    def close(self) -> None:
        """Record foreground IPC shutdown.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        self.closed = True


def _identity(tmp_path: Path) -> QueryDaemonIdentity:
    """Build one output-isolated query-daemon identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary test directory.

    Returns
    -------
    codira.query_daemon.QueryDaemonIdentity
        Fixed test repository/output identity.
    """
    return QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "output")


def _status(identity: QueryDaemonIdentity) -> QueryDaemonProcessStatus:
    """Build a complete durable status snapshot for round-trip assertions.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Fixed test identity.

    Returns
    -------
    QueryDaemonProcessStatus
        Ready status with all observable fields populated.
    """
    return QueryDaemonProcessStatus(
        state=QueryDaemonState.READY,
        identity=identity.value,
        pid=123,
        backend="sqlite",
        embedding_backend="onnx",
        current_generation=4,
        observed_generation=4,
        connection_warm=True,
        model_warm=True,
        queued_requests=2,
        active_requests=1,
        last_refresh_at=datetime(2026, 8, 8, tzinfo=UTC),
        updated_at=datetime(2026, 8, 8, tzinfo=UTC),
    )


def test_status_and_activity_round_trip_exclude_query_text(tmp_path: Path) -> None:
    """Persist every required query-daemon status field without request content.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary test directory.

    Returns
    -------
    None
        The test asserts durable status and activity remain privacy-safe.
    """
    store = QueryDaemonStatusStore(_identity(tmp_path))
    store.record(_status(store.identity), kind="ready")

    assert store.read() == _status(store.identity)
    activity = json.loads(store.activity_path.read_text("utf-8"))
    assert activity == {
        "error": None,
        "generation": 4,
        "kind": "ready",
        "recorded_at": activity["recorded_at"],
        "schema_version": 1,
        "state": "ready",
    }
    assert "query" not in store.activity_path.read_text("utf-8").lower()


def test_stale_owner_cleans_endpoint_but_live_owner_is_rejected(tmp_path: Path) -> None:
    """Clean stale ownership records while protecting a live same-identity PID.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary test directory.

    Returns
    -------
    None
        The test asserts stale endpoint cleanup and duplicate protection.
    """
    store = QueryDaemonStatusStore(_identity(tmp_path))
    store.owner_path.parent.mkdir(parents=True)
    store.owner_path.write_text(
        json.dumps(
            {"schema_version": 1, "identity": store.identity.value, "pid": 999999}
        ),
        encoding="utf-8",
    )
    endpoint_path = store.owner_path.parent / "query-daemon-endpoint.json"
    endpoint_path.write_text("{}", encoding="utf-8")

    store.claim_owner(123)
    assert not endpoint_path.exists()
    store.release_owner(123)

    store.claim_owner(os.getpid())
    with pytest.raises(RuntimeError, match="already running"):
        store.claim_owner(456)
    store.release_owner(os.getpid())


def test_foreground_degrades_without_index_then_stops_cleanly(tmp_path: Path) -> None:
    """Keep IPC alive but degraded when the durable generation is missing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary test directory.

    Returns
    -------
    None
        The test asserts degraded status, clean shutdown, and resource closure.
    """
    identity = _identity(tmp_path)
    root = identity.repository_root
    root.mkdir()
    config = load_effective_config(root=root)
    stop_event = Event()
    runtime = _Runtime()
    server: _Server | None = None

    def runtime_factory(_identity: QueryDaemonIdentity) -> QueryRuntime:
        """Return the prepared runtime test double.

        Parameters
        ----------
        _identity : codira.query_daemon.QueryDaemonIdentity
            Ignored fixed identity.

        Returns
        -------
        QueryRuntime
            Cast runtime test double.
        """
        return cast("QueryRuntime", runtime)

    def server_factory(
        selected_identity: QueryDaemonIdentity, selected_runtime: QueryRuntime
    ) -> _Server:
        """Build and retain a fake server for lifecycle assertions.

        Parameters
        ----------
        selected_identity : codira.query_daemon.QueryDaemonIdentity
            Fixed identity passed by the lifecycle.
        selected_runtime : QueryRuntime
            Runtime passed by the lifecycle.

        Returns
        -------
        _Server
            Started server test double.
        """
        nonlocal server
        server = _Server(selected_identity, cast("_Runtime", selected_runtime))
        return server

    thread = Thread(
        target=run_foreground_query_daemon,
        args=(identity, config),
        kwargs={
            "stop_event": stop_event,
            "runtime_factory": runtime_factory,
            "server_factory": cast("object", server_factory),
            "poll_interval_seconds": 0.01,
            "pid": 123,
        },
    )
    thread.start()
    store = QueryDaemonStatusStore(identity)
    for _ in range(100):
        if store.activity_path.exists() and "degraded" in store.activity_path.read_text(
            "utf-8"
        ):
            break
        sleep(0.01)
    stop_event.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    final_status = store.read()
    assert final_status is not None
    assert final_status.state is QueryDaemonState.STOPPED
    assert runtime.closed is True
    assert server is not None and server.started and server.closed
    assert not store.owner_path.exists()


def test_query_daemon_status_is_separate_from_indexing_daemon(tmp_path: Path) -> None:
    """Keep query-daemon observability in distinct durable filenames.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output directory.

    Returns
    -------
    None
        The test asserts the two daemon status files cannot overwrite each other.
    """
    root = tmp_path / "repo"
    root.mkdir()
    DaemonStatusStore(root).record(DaemonStatus(state=DaemonState.WATCHING))
    query_store = QueryDaemonStatusStore(QueryDaemonIdentity.from_paths(root, root))
    query_store.record(_status(query_store.identity), kind="ready")

    assert DaemonStatusStore(root).status_path.name == "daemon-status.json"
    assert query_store.status_path.name == "query-daemon-status.json"
    indexing_status = DaemonStatusStore(root).read()
    query_status = query_store.read()
    assert indexing_status is not None
    assert query_status is not None
    assert indexing_status.state is DaemonState.WATCHING
    assert query_status.state is QueryDaemonState.READY
