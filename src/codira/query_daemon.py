"""Contract declarations for Codira's repository-local warm query daemon.

The runtime, transport, and service adapters are intentionally deferred. This
module fixes the identity and lifecycle vocabulary shared by those slices.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import Future
from dataclasses import dataclass
from enum import StrEnum
from queue import Queue
from threading import Lock, Thread
from typing import TYPE_CHECKING, Protocol, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from codira.contracts import BackendQueryConnection

Result = TypeVar("Result")


class _RuntimeSession(Protocol):
    """Minimal warmed-session surface owned by the runtime.

    Parameters
    ----------
    None
    """

    generation: int

    def close(self) -> None:
        """Close owned resources.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        ...


class _ConnectionBackend(Protocol):
    """Backend subset required to own one warm read connection.

    Parameters
    ----------
    None
    """

    def open_connection(self, root: Path) -> object:
        """Open one repository connection.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        object
            Backend-owned connection.
        """
        ...

    def close_connection(self, connection: object) -> None:
        """Close one backend connection.

        Parameters
        ----------
        connection : object
            Backend-owned connection.

        Returns
        -------
        None
        """
        ...


class QueryDaemonState(StrEnum):
    """Observable lifecycle states for one query daemon.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    STOPPED = "stopped"
    STARTING = "starting"
    WARMING = "warming"
    READY = "ready"
    REFRESHING = "refreshing"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class QueryDaemonIdentity:
    """Identify one fixed repository and effective Codira output directory.

    Parameters
    ----------
    repository_root : pathlib.Path
        Resolved repository root whose indexed data may be read.
    output_root : pathlib.Path
        Resolved effective output directory containing ``.codira`` state.

    Notes
    -----
    The identity intentionally excludes mutable configuration and process IDs.
    A query daemon must never accept a repository path from a request.
    """

    repository_root: Path
    output_root: Path

    @classmethod
    def from_paths(
        cls, repository_root: Path, output_root: Path
    ) -> QueryDaemonIdentity:
        """Construct an identity from canonical runtime paths.

        Parameters
        ----------
        repository_root : pathlib.Path
            Repository root selected at process startup.
        output_root : pathlib.Path
            Effective output directory selected at process startup.

        Returns
        -------
        QueryDaemonIdentity
            Identity with both paths resolved without requiring their existence.
        """
        return cls(repository_root.resolve(), output_root.resolve())

    @property
    def value(self) -> str:
        """Return a stable opaque identity suitable for local descriptors.

        Parameters
        ----------
        None

        Returns
        -------
        str
            SHA-256 digest of the canonical repository/output path pair.
        """
        material = f"{self.repository_root}\0{self.output_root}".encode()
        return hashlib.sha256(material, usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class QueryDaemonStatus:
    """Report query-daemon lifecycle state without exposing request data.

    Parameters
    ----------
    identity : QueryDaemonIdentity
        Fixed repository/output identity owned by the process.
    state : QueryDaemonState
        Current lifecycle state.
    generation : int | None
        Last successfully warmed index generation, when available.
    last_error : str | None
        Stable diagnostic from the most recent failed warmup or refresh.
    """

    identity: QueryDaemonIdentity
    state: QueryDaemonState
    generation: int | None = None
    last_error: str | None = None


class QueryDaemonAlreadyRunningError(RuntimeError):
    """Report an attempted duplicate foreground query-daemon identity.

    Parameters
    ----------
    identity : QueryDaemonIdentity
        Identity already claimed by another foreground instance.
    """

    def __init__(self, identity: QueryDaemonIdentity) -> None:
        """Initialize a stable duplicate-instance diagnostic.

        Parameters
        ----------
        identity : QueryDaemonIdentity
            Identity already claimed by another foreground instance.

        Returns
        -------
        None
        """
        super().__init__(f"Query daemon already running for identity {identity.value}.")


class QueryDaemonInstanceRegistry:
    """Serialize foreground ownership claims within one process.

    Parameters
    ----------
    None

    Notes
    -----
    Later lifecycle slices replace this in-process guard with durable PID and
    endpoint ownership records while preserving its duplicate-identity rule.
    """

    def __init__(self) -> None:
        """Initialize an empty, thread-safe identity registry.

        Returns
        -------
        None
        """
        self._identities: set[str] = set()
        self._lock = Lock()

    def claim(self, identity: QueryDaemonIdentity) -> None:
        """Claim a foreground identity or reject an existing claim.

        Parameters
        ----------
        identity : QueryDaemonIdentity
            Repository/output identity to reserve.

        Returns
        -------
        None

        Raises
        ------
        QueryDaemonAlreadyRunningError
            If the identity is already claimed.
        """
        with self._lock:
            if identity.value in self._identities:
                raise QueryDaemonAlreadyRunningError(identity)
            self._identities.add(identity.value)

    def release(self, identity: QueryDaemonIdentity) -> None:
        """Release a previously claimed foreground identity.

        Parameters
        ----------
        identity : QueryDaemonIdentity
            Repository/output identity to release.

        Returns
        -------
        None
        """
        with self._lock:
            self._identities.discard(identity.value)


class WarmQuerySession:
    """Own one backend read connection on one dedicated worker thread.

    Parameters
    ----------
    backend : codira.contracts.IndexBackend
        Active backend used to open the read connection.
    root : pathlib.Path
        Fixed repository root.
    generation : int
        Ready index generation represented by the connection.
    """

    def __init__(
        self, backend: _ConnectionBackend, root: Path, generation: int
    ) -> None:
        """Open a read connection and start its owning worker.

        Parameters
        ----------
        backend : codira.contracts.IndexBackend
            Backend that owns connection construction and closure.
        root : pathlib.Path
            Fixed repository root.
        generation : int
            Ready generation served by the session.
        """
        self.generation = generation
        self._backend: _ConnectionBackend = backend
        self._root = root
        self._queue: Queue[
            tuple[Callable[[BackendQueryConnection], object], Future[object]] | None
        ] = Queue()
        self._ready = Future[None]()
        self._worker = Thread(target=self._run, daemon=True)
        self._worker.start()
        self._ready.result()

    def _run(self) -> None:
        """Own the connection and execute queued work serially.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        try:
            connection = self._backend.open_connection(self._root)
        except Exception as error:  # noqa: BLE001
            self._ready.set_exception(error)
            return
        self._ready.set_result(None)
        try:
            while (item := self._queue.get()) is not None:
                operation, future = item
                try:
                    future.set_result(
                        operation(cast("BackendQueryConnection", connection))
                    )
                except Exception as error:  # noqa: BLE001
                    future.set_exception(error)
        finally:
            self._backend.close_connection(connection)

    def submit(
        self, operation: Callable[[BackendQueryConnection], Result]
    ) -> Future[Result]:
        """Queue one read operation for serial connection-owned execution.

        Parameters
        ----------
        operation : collections.abc.Callable
            Read operation receiving the worker-owned connection.

        Returns
        -------
        concurrent.futures.Future[Result]
            Future completed by the dedicated worker.
        """
        future: Future[Result] = Future()
        self._queue.put(
            (
                cast("Callable[[BackendQueryConnection], object]", operation),
                cast("Future[object]", future),
            )
        )
        return future

    def close(self) -> None:
        """Close the session after all queued operations complete.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        self._queue.put(None)
        self._worker.join()


class QueryRuntime:
    """Atomically manage warm sessions for one fixed daemon identity.

    Parameters
    ----------
    identity : QueryDaemonIdentity
        Fixed repository/output identity.
    session_factory : collections.abc.Callable
        Factory creating a fully warmed replacement session.
    """

    def __init__(
        self,
        identity: QueryDaemonIdentity,
        session_factory: Callable[[int], _RuntimeSession],
    ) -> None:
        """Initialize an empty runtime.

        Parameters
        ----------
        identity : QueryDaemonIdentity
            Fixed repository/output identity.
        session_factory : collections.abc.Callable
            Replacement-session factory.
        """
        self.identity = identity
        self._session_factory = session_factory
        self._session: _RuntimeSession | None = None
        self._lock = Lock()

    def refresh(self, generation: int) -> bool:
        """Replace the session when a newer ready generation is observed.

        Parameters
        ----------
        generation : int
            Ready index generation to warm.

        Returns
        -------
        bool
            ``True`` when a replacement was installed.
        """
        with self._lock:
            if self._session is not None and self._session.generation >= generation:
                return False
        replacement = self._session_factory(generation)
        with self._lock:
            previous, self._session = self._session, replacement
        if previous is not None:
            previous.close()
        return True

    def refresh_from_generation_store(self) -> bool:
        """Refresh only when the durable handoff reports a ready generation.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            ``True`` when a newer ready generation installed a session.
        """
        from codira.index_generation import IndexGenerationStore

        record = IndexGenerationStore(
            self.identity.repository_root,
            output_root=self.identity.output_root,
        ).read()
        if record is None or record.state != "ready":
            return False
        return self.refresh(record.generation)

    def submit(
        self, operation: Callable[[BackendQueryConnection], Result]
    ) -> Future[Result]:
        """Submit one query to the currently ready warm session.

        Parameters
        ----------
        operation : collections.abc.Callable
            Connection-owning read operation.

        Returns
        -------
        concurrent.futures.Future[Result]
            Future completed by the active warm-session worker.

        Raises
        ------
        RuntimeError
            If no ready session has been installed.
        """
        with self._lock:
            session = self._session
        if session is None or not isinstance(session, WarmQuerySession):
            msg = "No ready warm query session."
            raise RuntimeError(msg)
        return session.submit(operation)

    def close(self) -> None:
        """Close the active warm session deterministically.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        with self._lock:
            session, self._session = self._session, None
        if session is not None:
            session.close()


def build_query_runtime(identity: QueryDaemonIdentity) -> QueryRuntime:
    """Build a repository-fixed runtime using the configured index backend.

    Parameters
    ----------
    identity : QueryDaemonIdentity
        Fixed repository/output identity.

    Returns
    -------
    QueryRuntime
        Runtime whose sessions reuse the configured backend.
    """
    from codira.registry import active_index_backend

    backend = active_index_backend(root=identity.repository_root)
    return QueryRuntime(
        identity,
        lambda generation: WarmQuerySession(
            backend,
            identity.repository_root,
            generation,
        ),
    )
