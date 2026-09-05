"""Foreground lifecycle and durable observability for the query daemon.

Responsibilities
----------------
- Own one repository/output-scoped foreground query-daemon process.
- Persist status, ownership, and privacy-safe activity records atomically.
- Refresh the warm runtime from durable index generations without indexing.

Design principles
-----------------
The lifecycle process never accepts repository paths after construction and
never mutates the index.  A missing, corrupt, or updating generation degrades
warm service only; direct-core callers remain available.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

from codira.index_generation import IndexGenerationStore
from codira.mcp.proxy import build_mcp_operations
from codira.query_daemon import (
    DEFAULT_QUERY_EXECUTION_TIMEOUT_SECONDS,
    QueryDaemonAlreadyRunningError,
    QueryDaemonIdentity,
    QueryDaemonInstanceRegistry,
    QueryDaemonState,
    QueryRuntime,
    build_query_runtime,
)
from codira.query_daemon_ipc import QueryDaemonIpcPaths, QueryDaemonIpcServer

if TYPE_CHECKING:
    from codira.config import CodiraConfig

Clock = Callable[[], datetime]
RuntimeFactory = Callable[[QueryDaemonIdentity], QueryRuntime]
ServerFactory = Callable[[QueryDaemonIdentity, QueryRuntime], QueryDaemonIpcServer]

_STATUS_FILENAME = "query-daemon-status.json"
_ACTIVITY_FILENAME = "query-daemon-activity.jsonl"
_OWNER_FILENAME = "query-daemon-owner.json"


def _build_ipc_server(
    identity: QueryDaemonIdentity, runtime: QueryRuntime
) -> QueryDaemonIpcServer:
    """Build the IPC server with the fixed MCP read-only operation set.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Fixed repository/output identity.
    runtime : codira.query_daemon.QueryRuntime
        Warm runtime that owns the read connection.

    Returns
    -------
    codira.query_daemon_ipc.QueryDaemonIpcServer
        Authenticated server exposing only approved fixed-root MCP operations.
    """
    from codira.cli import build_query_daemon_cli_operations

    return QueryDaemonIpcServer(
        identity,
        runtime,
        {
            **build_mcp_operations(identity.repository_root),
            **build_query_daemon_cli_operations(identity.repository_root),
        },
    )


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp.

    Parameters
    ----------
    None

    Returns
    -------
    datetime
        Current UTC time.
    """
    return datetime.now(UTC)


def _timestamp(value: datetime | None) -> str | None:
    """Serialize an optional UTC timestamp.

    Parameters
    ----------
    value : datetime.datetime | None
        Timestamp to serialize.

    Returns
    -------
    str | None
        ISO-8601 value or ``None``.
    """
    return None if value is None else value.isoformat()


def _parse_timestamp(value: object) -> datetime | None:
    """Decode one nullable timezone-aware timestamp.

    Parameters
    ----------
    value : object
        JSON timestamp value.

    Returns
    -------
    datetime | None
        Parsed timestamp or ``None``.

    Raises
    ------
    ValueError
        If the timestamp is not a timezone-aware ISO-8601 string.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        msg = "query-daemon timestamp must be a string or null"
        raise TypeError(msg)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        msg = "query-daemon timestamp must include a timezone"
        raise ValueError(msg)
    return parsed


@dataclass(frozen=True)
class QueryDaemonProcessStatus:
    """Persisted lifecycle and warm-resource snapshot for one query daemon.

    Parameters
    ----------
    state : codira.query_daemon.QueryDaemonState
        Current foreground lifecycle state.
    identity : str
        Opaque fixed repository/output identity.
    pid : int | None
        Owning process identifier while running.
    backend : str
        Configured structural backend name.
    embedding_backend : str
        Configured embedding backend name.
    current_generation : int | None
        Generation represented by the warm connection.
    observed_generation : int | None
        Latest durable generation observed by the coordinator.
    connection_warm : bool
        Whether a backend read connection is currently warm.
    model_warm : bool
        Whether the warm runtime has initialized semantic dependencies.
    queued_requests : int
        Number of accepted IPC clients waiting for a handler.
    active_requests : int
        Number of currently executing IPC handlers.
    last_refresh_at : datetime.datetime | None
        Time of the latest successful session replacement.
    fallback_available : bool
        Always true: clients may execute direct-core queries.
    last_error : str | None
        Most recent lifecycle or refresh diagnostic.
    updated_at : datetime.datetime
        Timestamp of this durable snapshot.
    """

    state: QueryDaemonState
    identity: str
    pid: int | None
    backend: str
    embedding_backend: str
    current_generation: int | None = None
    observed_generation: int | None = None
    connection_warm: bool = False
    model_warm: bool = False
    queued_requests: int = 0
    active_requests: int = 0
    last_refresh_at: datetime | None = None
    fallback_available: bool = True
    last_error: str | None = None
    updated_at: datetime | None = None


class QueryDaemonStatusStore:
    """Persist query-daemon status, ownership, and privacy-safe activity.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Fixed repository/output identity that owns all durable records.
    clock : collections.abc.Callable[[], datetime.datetime], optional
        UTC clock used for deterministic status and activity timestamps.
    """

    def __init__(
        self, identity: QueryDaemonIdentity, *, clock: Clock = _utc_now
    ) -> None:
        """Initialize a store below the effective output directory.

        Parameters
        ----------
        identity : codira.query_daemon.QueryDaemonIdentity
            Fixed repository/output identity.
        clock : collections.abc.Callable[[], datetime.datetime], optional
            UTC clock used for durable records.

        Returns
        -------
        None
        """
        self.identity = identity
        self._clock = clock
        self._state_dir = identity.output_root / ".codira"

    @property
    def status_path(self) -> Path:
        """Return the query-daemon status path.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            ``query-daemon-status.json`` below the output state directory.
        """
        return self._state_dir / _STATUS_FILENAME

    @property
    def activity_path(self) -> Path:
        """Return the append-only query-daemon activity path.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            ``query-daemon-activity.jsonl`` below the output state directory.
        """
        return self._state_dir / _ACTIVITY_FILENAME

    @property
    def owner_path(self) -> Path:
        """Return the foreground PID ownership record path.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            ``query-daemon-owner.json`` below the output state directory.
        """
        return self._state_dir / _OWNER_FILENAME

    def record(self, status: QueryDaemonProcessStatus, *, kind: str) -> None:
        """Atomically replace status and append a credential-free activity row.

        Parameters
        ----------
        status : QueryDaemonProcessStatus
            Current process snapshot to persist.
        kind : str
            Lifecycle event kind; it never includes query text or paths.

        Returns
        -------
        None
        """
        payload = _status_payload(status)
        self._write_json(self.status_path, payload)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        activity = {
            "schema_version": 1,
            "recorded_at": self._clock().isoformat(),
            "kind": kind,
            "state": status.state.value,
            "generation": status.current_generation,
            "error": status.last_error,
        }
        with self.activity_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(activity, sort_keys=True))
            output.write("\n")

    def read(self) -> QueryDaemonProcessStatus | None:
        """Read the durable query-daemon status when it exists.

        Parameters
        ----------
        None

        Returns
        -------
        QueryDaemonProcessStatus | None
            Latest status, or ``None`` before the daemon first records one.

        Raises
        ------
        ValueError
            If the durable record is corrupt or incompatible.
        """
        if not self.status_path.exists():
            return None
        try:
            return _status_from_payload(json.loads(self.status_path.read_text("utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            msg = "unable to read query-daemon status record"
            raise ValueError(msg) from error

    def claim_owner(self, pid: int) -> None:
        """Claim durable foreground ownership after stale-record cleanup.

        Parameters
        ----------
        pid : int
            Process identifier of the foreground query daemon.

        Returns
        -------
        None

        Raises
        ------
        QueryDaemonAlreadyRunningError
            If a live process already owns this exact identity.
        ValueError
            If ownership data belongs to another identity.
        """
        owner = self._read_owner()
        if owner is not None:
            owner_identity, owner_pid = owner
            if owner_identity != self.identity.value:
                msg = "query-daemon ownership identity does not match"
                raise ValueError(msg)
            if _pid_alive(owner_pid):
                raise QueryDaemonAlreadyRunningError(self.identity)
            self.cleanup_stale_endpoint()
        self._write_json(
            self.owner_path,
            {"schema_version": 1, "identity": self.identity.value, "pid": pid},
        )

    def release_owner(self, pid: int) -> None:
        """Remove this process's ownership record without touching another PID.

        Parameters
        ----------
        pid : int
            Releasing process identifier.

        Returns
        -------
        None
        """
        owner = self._read_owner()
        if owner == (self.identity.value, pid):
            self.owner_path.unlink(missing_ok=True)

    def cleanup_stale_endpoint(self) -> None:
        """Remove stale endpoint metadata and this identity's socket only.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        paths = QueryDaemonIpcPaths(self.identity)
        paths.endpoint_path.unlink(missing_ok=True)
        socket_path = paths.unix_socket_path
        try:
            socket_mode = socket_path.lstat().st_mode
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(socket_mode):
            socket_path.unlink()

    def _read_owner(self) -> tuple[str, int] | None:
        """Read and validate the optional durable ownership record.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[str, int] | None
            Identity/PID pair, or ``None`` when no owner record exists.

        Raises
        ------
        ValueError
            If an existing record is corrupt.
        """
        if not self.owner_path.exists():
            return None
        try:
            payload = json.loads(self.owner_path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            msg = "unable to read query-daemon ownership record"
            raise ValueError(msg) from error
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("identity"), str)
            or not isinstance(payload.get("pid"), int)
            or payload["pid"] <= 0
        ):
            msg = "invalid query-daemon ownership record"
            raise ValueError(msg)
        return payload["identity"], payload["pid"]

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        """Atomically write one JSON record below the state directory.

        Parameters
        ----------
        path : pathlib.Path
            Target durable record path.
        payload : dict[str, object]
            JSON-compatible record payload.

        Returns
        -------
        None
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
        Path(output.name).replace(path)


def _pid_alive(pid: int) -> bool:
    """Return whether an operating-system process identifier still exists.

    Parameters
    ----------
    pid : int
        Candidate process identifier.

    Returns
    -------
    bool
        ``True`` when the PID is alive or cannot be inspected due to access.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _status_payload(status: QueryDaemonProcessStatus) -> dict[str, object]:
    """Serialize one typed process status into the version-one JSON contract.

    Parameters
    ----------
    status : QueryDaemonProcessStatus
        Status snapshot to serialize.

    Returns
    -------
    dict[str, object]
        Durable JSON-compatible payload.
    """
    return {
        **asdict(status),
        "schema_version": 1,
        "state": status.state.value,
        "last_refresh_at": _timestamp(status.last_refresh_at),
        "updated_at": _timestamp(status.updated_at),
    }


def _status_from_payload(payload: object) -> QueryDaemonProcessStatus:
    """Validate and decode one persisted query-daemon status payload.

    Parameters
    ----------
    payload : object
        Decoded JSON value.

    Returns
    -------
    QueryDaemonProcessStatus
        Typed process status.

    Raises
    ------
    ValueError
        If the payload is incompatible with the version-one contract.
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        msg = "unsupported query-daemon status record"
        raise ValueError(msg)
    try:
        state = QueryDaemonState(payload["state"])
    except (KeyError, TypeError, ValueError) as error:
        msg = "invalid query-daemon status state"
        raise ValueError(msg) from error
    required_strings = ("identity", "backend", "embedding_backend")
    if any(not isinstance(payload.get(name), str) for name in required_strings):
        msg = "invalid query-daemon status strings"
        raise ValueError(msg)
    nullable_ints = ("pid", "current_generation", "observed_generation")
    if any(
        value is not None and (not isinstance(value, int) or value < 0)
        for name in nullable_ints
        if (value := payload.get(name)) is not None
    ):
        msg = "invalid query-daemon status generation"
        raise ValueError(msg)
    count_names = ("queued_requests", "active_requests")
    if any(
        not isinstance(payload.get(name), int) or payload[name] < 0
        for name in count_names
    ):
        msg = "invalid query-daemon activity counts"
        raise ValueError(msg)
    if any(
        not isinstance(payload.get(name), bool)
        for name in ("connection_warm", "model_warm", "fallback_available")
    ):
        msg = "invalid query-daemon warm status"
        raise ValueError(msg)
    error_value = payload.get("last_error")
    if error_value is not None and not isinstance(error_value, str):
        msg = "invalid query-daemon error"
        raise ValueError(msg)
    updated = _parse_timestamp(payload.get("updated_at"))
    if updated is None:
        msg = "query-daemon status requires updated_at"
        raise ValueError(msg)
    return QueryDaemonProcessStatus(
        state=state,
        identity=payload["identity"],
        pid=payload.get("pid"),
        backend=payload["backend"],
        embedding_backend=payload["embedding_backend"],
        current_generation=payload.get("current_generation"),
        observed_generation=payload.get("observed_generation"),
        connection_warm=payload["connection_warm"],
        model_warm=payload["model_warm"],
        queued_requests=payload["queued_requests"],
        active_requests=payload["active_requests"],
        last_refresh_at=_parse_timestamp(payload.get("last_refresh_at")),
        fallback_available=payload["fallback_available"],
        last_error=error_value,
        updated_at=updated,
    )


def run_foreground_query_daemon(  # noqa: PLR0913
    identity: QueryDaemonIdentity,
    config: CodiraConfig,
    *,
    stop_event: Event | None = None,
    runtime_factory: RuntimeFactory = build_query_runtime,
    server_factory: ServerFactory = _build_ipc_server,
    registry: QueryDaemonInstanceRegistry | None = None,
    status_store: QueryDaemonStatusStore | None = None,
    poll_interval_seconds: float = 0.25,
    pid: int | None = None,
    clock: Clock = _utc_now,
) -> QueryDaemonProcessStatus:
    """Run one fixed-root foreground query daemon until a stop event is set.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Fixed repository and output-directory identity.
    config : codira.config.CodiraConfig
        Effective configuration used only for reported backend identities.
    stop_event : threading.Event | None, optional
        Signal-aware stop event. ``None`` runs until ``KeyboardInterrupt``.
    runtime_factory : collections.abc.Callable, optional
        Warm-runtime constructor used by deterministic lifecycle tests.
    server_factory : collections.abc.Callable, optional
        IPC-server constructor used by deterministic lifecycle tests.
    registry : QueryDaemonInstanceRegistry | None, optional
        In-process duplicate-instance guard.
    status_store : QueryDaemonStatusStore | None, optional
        Durable lifecycle store. ``None`` creates the standard store.
    poll_interval_seconds : float, optional
        Bounded generation-observation interval.
    pid : int | None, optional
        Process identifier override for deterministic tests.
    clock : collections.abc.Callable[[], datetime.datetime], optional
        UTC clock used for status timestamps.

    Returns
    -------
    QueryDaemonProcessStatus
        Final stopped status after resource closure.

    Raises
    ------
    ValueError
        If the poll interval is not positive.
    QueryDaemonAlreadyRunningError
        If another live process owns the same identity.
    """
    if poll_interval_seconds <= 0:
        msg = "query-daemon poll interval must be positive"
        raise ValueError(msg)
    active_stop = stop_event or Event()
    active_registry = registry or QueryDaemonInstanceRegistry()
    store = status_store or QueryDaemonStatusStore(identity, clock=clock)
    process_id = os.getpid() if pid is None else pid
    runtime: QueryRuntime | None = None
    server: QueryDaemonIpcServer | None = None
    last_refresh: datetime | None = None
    active_registry.claim(identity)
    store.claim_owner(process_id)

    def snapshot(
        state: QueryDaemonState,
        *,
        observed: int | None = None,
        error: str | None = None,
    ) -> QueryDaemonProcessStatus:
        """Build one privacy-safe lifecycle snapshot from current resources.

        Parameters
        ----------
        state : codira.query_daemon.QueryDaemonState
            Lifecycle state to persist.
        observed : int | None, optional
            Latest durable generation observed.
        error : str | None, optional
            Stable lifecycle diagnostic.

        Returns
        -------
        QueryDaemonProcessStatus
            Current durable snapshot.
        """
        generation = None if runtime is None else runtime.generation
        return QueryDaemonProcessStatus(
            state=state,
            identity=identity.value,
            pid=process_id,
            backend=config.backend.name,
            embedding_backend=config.embeddings.engine,
            current_generation=generation,
            observed_generation=observed,
            connection_warm=generation is not None,
            model_warm=generation is not None,
            last_refresh_at=last_refresh,
            fallback_available=True,
            last_error=error,
            updated_at=clock(),
        )

    status = snapshot(QueryDaemonState.STARTING)
    store.record(status, kind="starting")
    try:
        runtime = runtime_factory(identity)
        status = snapshot(QueryDaemonState.WARMING)
        store.record(status, kind="warming")
        server = server_factory(identity, runtime)
        server.start()
        previous_state: QueryDaemonState | None = None
        while not active_stop.is_set():
            observed: int | None = None
            error: str | None = None
            state = QueryDaemonState.DEGRADED
            refreshed = False
            try:
                record = IndexGenerationStore(
                    identity.repository_root, output_root=identity.output_root
                ).read()
                if record is None:
                    error = "No durable index generation is available."
                elif record.state != "ready":
                    observed = record.generation
                    error = "Index generation is updating."
                else:
                    observed = record.generation
                    if runtime.generation != record.generation:
                        store.record(
                            snapshot(QueryDaemonState.REFRESHING, observed=observed),
                            kind="refreshing",
                        )
                    refreshed = runtime.refresh_from_generation_store()
                    if runtime.generation != record.generation:
                        error = (
                            "Warm runtime does not match the ready index generation."
                        )
                    else:
                        state = QueryDaemonState.READY
                        if refreshed:
                            last_refresh = clock()
            except Exception as exception:  # noqa: BLE001
                error = f"{type(exception).__name__}: {exception}"
            status = snapshot(state, observed=observed, error=error)
            if state != previous_state or error is not None or refreshed:
                kind = (
                    "recovered"
                    if state is QueryDaemonState.READY
                    and previous_state is QueryDaemonState.DEGRADED
                    else "generation_refreshed"
                    if refreshed
                    else state.value
                )
                store.record(status, kind=kind)
            previous_state = state
            active_stop.wait(poll_interval_seconds)
    except KeyboardInterrupt:
        pass
    except Exception as exception:  # noqa: BLE001
        status = snapshot(
            QueryDaemonState.DEGRADED, error=f"{type(exception).__name__}: {exception}"
        )
        store.record(status, kind="startup_failed")
        raise
    finally:
        if server is not None:
            server.close()
        if runtime is not None:
            runtime.close_with_timeout(
                timeout_seconds=DEFAULT_QUERY_EXECUTION_TIMEOUT_SECONDS
            )
        final = snapshot(QueryDaemonState.STOPPED)
        store.record(final, kind="shutdown")
        store.release_owner(process_id)
        active_registry.release(identity)
    return final


def install_query_daemon_signal_handlers(stop_event: Event) -> Callable[[], None]:
    """Install temporary SIGINT/SIGTERM handlers that request graceful shutdown.

    Parameters
    ----------
    stop_event : threading.Event
        Foreground stop signal set by supported terminal signals.

    Returns
    -------
    collections.abc.Callable[[], None]
        Callback restoring the previous signal handlers.
    """
    signals = (signal.SIGINT, signal.SIGTERM)
    previous = {item: signal.getsignal(item) for item in signals}

    def request_stop(_signum: int, _frame: object) -> None:
        """Set the foreground stop event without raising from a signal handler.

        Parameters
        ----------
        _signum : int
            Delivered signal number.
        _frame : object
            Interpreter frame supplied by the signal runtime.

        Returns
        -------
        None
        """
        stop_event.set()

    for item in signals:
        signal.signal(item, request_stop)

    def restore() -> None:
        """Restore the signal handlers active before foreground startup.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        for item, handler in previous.items():
            signal.signal(item, handler)

    return restore
