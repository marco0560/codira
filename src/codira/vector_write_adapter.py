"""Adapt a bound vector-store write session to the legacy store method shape.

The adapter is compatible with ``VectorStore`` for the supported operations,
but deliberately does not forward optional bulk-writer attributes.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from typing import TYPE_CHECKING, TypeVar

from codira.contracts import (
    PreparedVectorRow,
    VectorSetIdentity,
    VectorSnapshot,
    VectorSnapshotRequest,
    VectorStore,
    VectorStoreError,
    VectorStorePurgeRequest,
    VectorStorePurgeResult,
    VectorStoreResetRequest,
    VectorStoreResetResult,
    VectorStoreSpec,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from codira.vector_write_session import VectorStoreWriteSession

_Result = TypeVar("_Result")


class VectorStoreWriteAdapter:
    """Present a bound write session through the existing vector-store API.

    Session-backed writes use only the bound transaction. Schema and snapshot
    operations proxy to the original store when doing so cannot escape an
    active transaction. Purge and reset are rejected because they are not
    session-scoped operations. No ``__getattr__`` forwarding is provided, so
    optional bulk-writer capabilities cannot leak through this adapter.

    Parameters
    ----------
    store : codira.contracts.VectorStore
        Original plugin used for safe non-session operations.
    session : codira.vector_write_session.VectorStoreWriteSession
        Active write session bound to the supplied context.
    root : pathlib.Path
        Repository root bound to every adapted operation.
    identity : codira.contracts.VectorSetIdentity
        Vector-set identity bound to every adapted operation.
    config : collections.abc.Mapping[str, object]
        Store configuration bound to every adapted operation.

    Returns
    -------
    None
        The adapter owns no additional storage connection.

    """

    def __init__(
        self,
        store: VectorStore,
        session: VectorStoreWriteSession,
        *,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> None:
        """Bind a plugin, active session, and immutable call context.

        Parameters
        ----------
        store : codira.contracts.VectorStore
            Original store used for safe proxy operations.
        session : codira.vector_write_session.VectorStoreWriteSession
            Active transaction receiving all adapted writes.
        root : pathlib.Path
            Repository root used to bind calls.
        identity : codira.contracts.VectorSetIdentity
            Vector-set identity used to bind calls.
        config : collections.abc.Mapping[str, object]
            Store configuration copied and bound to calls.

        Returns
        -------
        None
            Adapter fields are initialized.

        Raises
        ------
        codira.contracts.VectorStoreError
            If the supplied session does not implement the session protocol.
        """
        self._store = store
        self._session = session
        self._root = root.resolve()
        self._identity = identity
        self._config = deepcopy(dict(config))
        self.name = str(store.name)
        self.version = str(store.version)
        self._active = True
        self._closed = False

    def _validate_config(self, config: Mapping[str, object]) -> None:
        """Require each call to use the adapter's bound configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Configuration supplied by the legacy method caller.

        Returns
        -------
        None
            Returns when the configuration matches the bound value.

        Raises
        ------
        codira.contracts.VectorStoreError
            If the supplied configuration differs from the bound value.
        """
        if dict(config) != self._config:
            msg = "vector-store adapter configuration mismatch"
            raise VectorStoreError(msg)

    def _validate_context(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> None:
        """Validate root, vector identity, and config for one adapted call.

        Parameters
        ----------
        root : pathlib.Path
            Repository root supplied to the legacy method.
        identity : codira.contracts.VectorSetIdentity
            Vector identity supplied to the legacy method.
        config : collections.abc.Mapping[str, object]
            Store configuration supplied to the legacy method.

        Returns
        -------
        None
            Returns when all supplied context matches the bound session.

        Raises
        ------
        codira.contracts.VectorStoreError
            If any supplied context differs from the bound session.
        """
        if root.resolve() != self._root:
            msg = "vector-store adapter repository root mismatch"
            raise VectorStoreError(msg)
        if identity != self._identity:
            msg = "vector-store adapter identity mismatch"
            raise VectorStoreError(msg)
        self._validate_config(config)

    def _require_inactive(self, operation: str) -> None:
        """Prevent non-session writes while the adapter transaction is active.

        Parameters
        ----------
        operation : str
            Store operation that requires the session to be finalized.

        Returns
        -------
        None
            Returns after commit or abort.

        Raises
        ------
        codira.contracts.VectorStoreError
            If the operation would run outside the active session.
        """
        if self._active:
            msg = f"{operation} is unavailable while the staged write session is active"
            raise VectorStoreError(msg)

    @staticmethod
    def _wrap_failure(operation: str, action: Callable[[], _Result]) -> _Result:
        """Run a store operation and normalize plugin failures.

        Parameters
        ----------
        operation : str
            Short operation label included in the error message.
        action : collections.abc.Callable[[], _Result]
            Store or session operation to invoke.

        Returns
        -------
        _Result
            Result returned by the wrapped operation.

        Raises
        ------
        codira.contracts.VectorStoreError
            If the operation raises another exception; an existing vector-store
            error is propagated unchanged.
        """
        try:
            return action()
        except VectorStoreError:
            raise
        except Exception as exc:
            msg = f"vector-store {operation} failed"
            raise VectorStoreError(msg) from exc

    def configuration_json_schema(self) -> Mapping[str, object]:
        """Return the original plugin's configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Plugin configuration schema.

        Raises
        ------
        codira.contracts.VectorStoreError
            If the original plugin cannot provide its schema.
        """
        method = getattr(self._store, "configuration_json_schema", None)
        if not callable(method):
            msg = "vector store does not expose a configuration schema"
            raise VectorStoreError(msg)
        return self._wrap_failure("configuration schema", method)

    def spec(self, config: Mapping[str, object]) -> VectorStoreSpec:
        """Return the original plugin's vector-store spec for bound config.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Configuration that must match the adapter binding.

        Returns
        -------
        codira.contracts.VectorStoreSpec
            Vector-store persistence identity.

        Raises
        ------
        codira.contracts.VectorStoreError
            If config validation or the original plugin operation fails.
        """
        self._validate_config(config)
        return self._wrap_failure("spec", lambda: self._store.spec(config))

    def initialize(self, root: Path, config: Mapping[str, object]) -> None:
        """Initialize through the original store only after session finalization.

        Parameters
        ----------
        root : pathlib.Path
            Repository root that must match the bound root.
        config : collections.abc.Mapping[str, object]
            Configuration that must match the bound config.

        Returns
        -------
        None
            Original store initialization is complete.

        Raises
        ------
        codira.contracts.VectorStoreError
            If context differs, the session is active, or initialization fails.
        """
        if root.resolve() != self._root:
            msg = "vector-store adapter repository root mismatch"
            raise VectorStoreError(msg)
        self._validate_config(config)
        self._require_inactive("initialize")
        self._wrap_failure("initialize", lambda: self._store.initialize(root, config))

    def ensure_vector_set(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> int:
        """Return the vector-set ID through the bound session connection.

        Parameters
        ----------
        root : pathlib.Path
            Repository root that must match the session binding.
        identity : codira.contracts.VectorSetIdentity
            Identity that must match the session binding.
        config : collections.abc.Mapping[str, object]
            Configuration that must match the session binding.

        Returns
        -------
        int
            Store-local identifier read from the session.

        Raises
        ------
        codira.contracts.VectorStoreError
            If context validation or the session operation fails.
        """
        self._validate_context(root, identity, config)
        return self._wrap_failure("ensure vector set", self._session.ensure_vector_set)

    def load_cached_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        content_hashes: Sequence[str],
        config: Mapping[str, object],
    ) -> dict[str, bytes]:
        """Load cached vectors through the bound session.

        Parameters
        ----------
        root : pathlib.Path
            Repository root that must match the session binding.
        identity : codira.contracts.VectorSetIdentity
            Identity that must match the session binding.
        content_hashes : collections.abc.Sequence[str]
            Cache keys to look up.
        config : collections.abc.Mapping[str, object]
            Configuration that must match the session binding.

        Returns
        -------
        dict[str, bytes]
            Matching serialized vectors keyed by content hash.

        Raises
        ------
        codira.contracts.VectorStoreError
            If context validation or the session operation fails.
        """
        self._validate_context(root, identity, config)
        return self._wrap_failure(
            "cache lookup", lambda: self._session.load_cached_vectors(content_hashes)
        )

    def store_cached_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        vectors: Mapping[str, bytes],
        config: Mapping[str, object],
    ) -> None:
        """Stage cache rows through the bound session.

        Parameters
        ----------
        root : pathlib.Path
            Repository root that must match the session binding.
        identity : codira.contracts.VectorSetIdentity
            Identity that must match the session binding.
        vectors : collections.abc.Mapping[str, bytes]
            Bounded cache batch keyed by content hash.
        config : collections.abc.Mapping[str, object]
            Configuration that must match the session binding.

        Returns
        -------
        None
            Cache rows are staged in the vector-store transaction.

        Raises
        ------
        codira.contracts.VectorStoreError
            If context validation or the session operation fails.
        """
        self._validate_context(root, identity, config)
        self._wrap_failure(
            "cache write", lambda: self._session.store_cached_vectors(vectors)
        )

    def store_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: Mapping[str, object],
    ) -> None:
        """Stage deferred rows through the bound session.

        Parameters
        ----------
        root : pathlib.Path
            Repository root that must match the session binding.
        identity : codira.contracts.VectorSetIdentity
            Identity that must match the session binding.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Bounded pending-row batch.
        config : collections.abc.Mapping[str, object]
            Configuration that must match the session binding.

        Returns
        -------
        None
            Pending rows are staged in the vector-store transaction.

        Raises
        ------
        codira.contracts.VectorStoreError
            If context validation or the session operation fails.
        """
        self._validate_context(root, identity, config)
        self._wrap_failure(
            "pending-vector write", lambda: self._session.store_pending_vectors(rows)
        )

    def delete_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: Mapping[str, object],
    ) -> None:
        """Stage pending-row deletions through the bound session.

        Parameters
        ----------
        root : pathlib.Path
            Repository root that must match the session binding.
        identity : codira.contracts.VectorSetIdentity
            Identity that must match the session binding.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Bounded batch identifying pending objects to delete.
        config : collections.abc.Mapping[str, object]
            Configuration that must match the session binding.

        Returns
        -------
        None
            Matching pending rows are staged for deletion.

        Raises
        ------
        codira.contracts.VectorStoreError
            If context validation or the session operation fails.
        """
        self._validate_context(root, identity, config)
        self._wrap_failure(
            "pending-vector deletion",
            lambda: self._session.delete_pending_vectors(rows),
        )

    def clear_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> None:
        """Stage clearing pending rows through the bound session.

        Parameters
        ----------
        root : pathlib.Path
            Repository root that must match the session binding.
        identity : codira.contracts.VectorSetIdentity
            Identity that must match the session binding.
        config : collections.abc.Mapping[str, object]
            Configuration that must match the session binding.

        Returns
        -------
        None
            Pending-row clearing is staged in the transaction.

        Raises
        ------
        codira.contracts.VectorStoreError
            If context validation or the session operation fails.
        """
        self._validate_context(root, identity, config)
        self._wrap_failure(
            "pending-vector clearing", self._session.clear_pending_vectors
        )

    def store_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: Mapping[str, object],
    ) -> None:
        """Stage materialized bindings through the bound session.

        Parameters
        ----------
        root : pathlib.Path
            Repository root that must match the session binding.
        identity : codira.contracts.VectorSetIdentity
            Identity that must match the session binding.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Bounded batch of materialized vector rows.
        config : collections.abc.Mapping[str, object]
            Configuration that must match the session binding.

        Returns
        -------
        None
            Payloads and bindings are staged in the transaction.

        Raises
        ------
        codira.contracts.VectorStoreError
            If context validation or the session operation fails.
        """
        self._validate_context(root, identity, config)
        self._wrap_failure("vector write", lambda: self._session.store_vectors(rows))

    def vector_snapshot(self, request: VectorSnapshotRequest) -> VectorSnapshot:
        """Read a snapshot through the original store after session finalization.

        Parameters
        ----------
        request : codira.contracts.VectorSnapshotRequest
            Snapshot request that must match the adapter binding.

        Returns
        -------
        codira.contracts.VectorSnapshot
            Ordered authoritative vector rows.

        Raises
        ------
        codira.contracts.VectorStoreError
            If request context mismatches, the session remains active, or the
            original store snapshot operation fails.
        """
        self._validate_context(request.root, request.identity, request.config)
        self._require_inactive("vector snapshot")
        return self._wrap_failure(
            "vector snapshot", lambda: self._store.vector_snapshot(request)
        )

    def purge_vector_sets(
        self,
        request: VectorStorePurgeRequest,
    ) -> VectorStorePurgeResult:
        """Reject purges that would bypass this staged session.

        Parameters
        ----------
        request : codira.contracts.VectorStorePurgeRequest
            Purge request presented through the adapter.

        Returns
        -------
        codira.contracts.VectorStorePurgeResult
            This operation always raises while using the write adapter.

        Raises
        ------
        codira.contracts.VectorStoreError
            Purging is not a session-scoped operation.
        """
        self._validate_context(request.root, request.identity, request.config)
        msg = "purge is unavailable through a staged write adapter"
        raise VectorStoreError(msg)

    def reset_persistent_state(
        self,
        request: VectorStoreResetRequest,
    ) -> VectorStoreResetResult:
        """Reject persistent-state reset through a bound write adapter.

        Parameters
        ----------
        request : codira.contracts.VectorStoreResetRequest
            Reset request presented through the adapter.

        Returns
        -------
        codira.contracts.VectorStoreResetResult
            This operation always raises while using the write adapter.

        Raises
        ------
        codira.contracts.VectorStoreError
            Reset would bypass the bound session and destroy store state.
        """
        if request.root.resolve() != self._root:
            msg = "vector-store adapter repository root mismatch"
            raise VectorStoreError(msg)
        self._validate_config(request.config)
        msg = "reset is unavailable through a staged write adapter"
        raise VectorStoreError(msg)

    def reset_runtime_caches(self) -> None:
        """Reset process-local caches through the original plugin.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Original plugin runtime caches are cleared.

        Raises
        ------
        codira.contracts.VectorStoreError
            If the original plugin cache reset fails.
        """
        self._wrap_failure("runtime-cache reset", self._store.reset_runtime_caches)

    def commit(self) -> None:
        """Commit the bound vector-store transaction.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Staged writes are committed in the vector store.

        Raises
        ------
        codira.contracts.VectorStoreError
            If session commit fails; a secondary abort is attempted.
        """
        if not self._active:
            msg = "vector-store adapter session is not active"
            raise VectorStoreError(msg)
        try:
            self._wrap_failure("session commit", self._session.commit)
        except VectorStoreError:
            with suppress(Exception):
                self._session.abort()
            self._active = False
            raise
        self._active = False

    def abort(self) -> None:
        """Abort the bound vector-store transaction.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Staged writes are discarded.

        Raises
        ------
        codira.contracts.VectorStoreError
            If session abort fails.
        """
        if not self._active:
            return
        try:
            self._wrap_failure("session abort", self._session.abort)
        finally:
            self._active = False

    def close(self) -> None:
        """Close the bound session and its owned resources.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The session is closed; its own close behavior aborts unfinished work.

        Raises
        ------
        codira.contracts.VectorStoreError
            If session close fails.
        """
        if self._closed:
            return
        try:
            self._wrap_failure("session close", self._session.close)
        finally:
            self._active = False
            self._closed = True
