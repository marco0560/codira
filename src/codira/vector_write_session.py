"""Optional transactional write-session capability for vector stores.

This module is intentionally separate from :mod:`codira.contracts`: existing
vector-store plugins do not need to implement transactional sessions. A
session commits only its vector store; it does not provide atomicity with a
separate structural backend or across process crashes between store commits.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from codira.contracts import PreparedVectorRow, VectorSetIdentity


@runtime_checkable
class VectorStoreWriteSession(Protocol):
    """Isolated, explicitly finalized writes for one vector set.

    Implementations must make reads observe writes made by this session and
    must not expose those writes to other connections before ``commit``.
    Methods accept bounded batches; implementations must not retain batches in
    memory after applying them to their transaction.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    def ensure_vector_set(self) -> int:
        """Return the identifier bound to this session.

        Parameters
        ----------
        None

        Returns
        -------
        int
            Store-local identifier for the session's vector set.
        """
        ...

    def load_cached_vectors(self, content_hashes: Sequence[str]) -> dict[str, bytes]:
        """Load cached payloads, including payloads staged by this session.

        Parameters
        ----------
        content_hashes : collections.abc.Sequence[str]
            Content hashes to look up.

        Returns
        -------
        dict[str, bytes]
            Matching serialized vectors keyed by content hash.
        """
        ...

    def store_cached_vectors(self, vectors: Mapping[str, bytes]) -> None:
        """Store one bounded batch of content-addressed vector payloads.

        Parameters
        ----------
        vectors : collections.abc.Mapping[str, bytes]
            Serialized vectors keyed by content hash.

        Returns
        -------
        None
            Payloads are staged in the session transaction.
        """
        ...

    def store_vectors(self, rows: Sequence[PreparedVectorRow]) -> None:
        """Store materialized bindings from one bounded batch.

        Parameters
        ----------
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Materialized vector rows to persist.

        Returns
        -------
        None
            Payloads and bindings are staged in the session transaction.
        """
        ...

    def store_pending_vectors(self, rows: Sequence[PreparedVectorRow]) -> None:
        """Store deferred vector rows from one bounded batch.

        Parameters
        ----------
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Deferred rows to store.

        Returns
        -------
        None
            Pending rows are staged in the session transaction.
        """
        ...

    def delete_pending_vectors(self, rows: Sequence[PreparedVectorRow]) -> None:
        """Delete pending rows matching object type and object ID.

        Parameters
        ----------
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Materialized rows identifying pending objects to remove.

        Returns
        -------
        None
            Matching pending rows are staged for deletion.
        """
        ...

    def clear_pending_vectors(self) -> None:
        """Clear pending rows for this vector set.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Pending-row deletions are staged in the session transaction.
        """
        ...

    def commit(self) -> None:
        """Atomically expose all session writes to other connections.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The vector-store transaction is committed.

        Raises
        ------
        Exception
            If the vector-store transaction cannot be committed.
        """
        ...

    def abort(self) -> None:
        """Discard all session writes that have not been committed.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Uncommitted vector-store writes are rolled back.
        """
        ...

    def close(self) -> None:
        """Release the owned connection, aborting an unfinished session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The session-owned connection is closed.
        """
        ...


@runtime_checkable
class VectorStoreWriteSessionFactory(Protocol):
    """Optional capability implemented by vector stores that support sessions.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    def begin_write_session(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> VectorStoreWriteSession:
        """Open an isolated write session for one vector-set identity.

        Parameters
        ----------
        root : pathlib.Path
            Repository root owning the vector-store database.
        identity : codira.contracts.VectorSetIdentity
            Vector-set identity for the session.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration.

        Returns
        -------
        codira.vector_write_session.VectorStoreWriteSession
            Active write session for the requested vector set.
        """
        ...
