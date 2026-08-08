"""Contract declarations for Codira's repository-local warm query daemon.

The runtime, transport, and service adapters are intentionally deferred. This
module fixes the identity and lifecycle vocabulary shared by those slices.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


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
