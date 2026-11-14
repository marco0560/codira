"""Behavioral tests for the legacy-signature vector write adapter.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from codira_vector_store_sqlite import SQLiteVectorStore

from codira.contracts import (
    EmbeddingEngineSpec,
    PendingEmbeddingRow,
    PreparedVectorRow,
    VectorSetIdentity,
    VectorSnapshotRequest,
    VectorStore,
    VectorStoreBulkWriter,
    VectorStoreError,
    VectorStorePurgeRequest,
)
from codira.semantic.embeddings import serialize_vector
from codira.vector_write_adapter import VectorStoreWriteAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


def _identity(
    store: SQLiteVectorStore, model_version: str = "adapter-test"
) -> VectorSetIdentity:
    """Build the vector-set identity used by adapter tests.

    Parameters
    ----------
    store : codira_vector_store_sqlite.SQLiteVectorStore
        SQLite vector store whose spec completes the identity.
    model_version : str, optional
        Model revision used to distinguish test identities.

    Returns
    -------
    codira.contracts.VectorSetIdentity
        Complete test vector-set identity.
    """
    return VectorSetIdentity(
        engine=EmbeddingEngineSpec(
            engine="adapter-test",
            engine_version="1",
            model="adapter-model",
            model_version=model_version,
            dimension=3,
        ),
        vector_store=store.spec({}),
    )


def _context(
    root: Path,
    config: Mapping[str, object] | None = None,
) -> tuple[
    SQLiteVectorStore, VectorSetIdentity, dict[str, object], VectorStoreWriteAdapter
]:
    """Create an initialized plugin session and its bound API adapter.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root for vector-store state.
    config : collections.abc.Mapping[str, object] or None, optional
        Configuration bound to the adapter.

    Returns
    -------
    tuple
        Original store, identity, copied config, and active adapter.
    """
    store = SQLiteVectorStore()
    bound_config = {} if config is None else dict(config)
    identity = _identity(store)
    session = store.begin_write_session(root, identity, bound_config)
    return (
        store,
        identity,
        bound_config,
        VectorStoreWriteAdapter(
            store,
            session,
            root=root,
            identity=identity,
            config=bound_config,
        ),
    )


def _prepared_row(
    stable_id: str, object_id: int, content_hash: str
) -> PreparedVectorRow:
    """Build one materialized vector row for an adapter operation.

    Parameters
    ----------
    stable_id : str
        Stable vector-binding identity.
    object_id : int
        Structural object ID used to identify pending rows.
    content_hash : str
        Content-addressed cache key.

    Returns
    -------
    codira.contracts.PreparedVectorRow
        Row carrying a serialized three-dimensional vector.
    """
    return PreparedVectorRow(
        row=PendingEmbeddingRow(
            object_type="symbol",
            object_id=object_id,
            stable_id=stable_id,
            text=f"text:{stable_id}",
        ),
        content_hash=content_hash,
        vector=serialize_vector([1.0, 0.0, 0.0]),
    )


def test_adapter_implements_legacy_store_api_without_bulk_writer_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route all index writes through the session and hide bulk capabilities.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the vector database.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to install a detectable bulk-writer method on the original.

    Returns
    -------
    None
        Session writes commit, while the adapter does not expose bulk writing.
    """
    store, identity, config, adapter = _context(tmp_path)
    monkeypatch.setattr(store, "store_vectors_for_full_index", lambda _request: None)
    row = _prepared_row("symbol:one", 1, "hash-one")
    try:
        assert isinstance(adapter, VectorStore)
        assert not isinstance(adapter, VectorStoreBulkWriter)
        assert not hasattr(adapter, "store_vectors_for_full_index")
        assert adapter.ensure_vector_set(tmp_path, identity, config) > 0
        assert (
            adapter.load_cached_vectors(tmp_path, identity, ["hash-one"], config) == {}
        )
        adapter.store_cached_vectors(
            tmp_path, identity, {"hash-one": row.vector or b""}, config
        )
        assert adapter.load_cached_vectors(
            tmp_path, identity, ["hash-one"], config
        ) == {"hash-one": row.vector}
        adapter.store_pending_vectors(tmp_path, identity, [row], config)
        adapter.store_vectors(tmp_path, identity, [row], config)
        adapter.delete_pending_vectors(tmp_path, identity, [row], config)
        adapter.store_pending_vectors(tmp_path, identity, [row], config)
        adapter.clear_pending_vectors(tmp_path, identity, config)
        adapter.commit()
    finally:
        adapter.close()

    snapshot = store.vector_snapshot(
        VectorSnapshotRequest(
            root=tmp_path,
            identity=identity,
            object_type="symbol",
            config=config,
        )
    )
    assert [(item.stable_id, item.content_hash) for item in snapshot.rows] == [
        ("symbol:one", "hash-one")
    ]


@pytest.mark.parametrize("mismatch", ["root", "identity", "config"])
def test_adapter_rejects_unbound_call_context(tmp_path: Path, mismatch: str) -> None:
    """Reject calls whose legacy context differs from the bound session.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the vector database.
    mismatch : str
        Context dimension to vary: root, vector identity, or config.

    Returns
    -------
    None
        Each mismatched context raises VectorStoreError before session use.
    """
    store, identity, config, adapter = _context(tmp_path, {"tenant": "one"})
    root = tmp_path / "other" if mismatch == "root" else tmp_path
    other_identity = (
        _identity(store, "different") if mismatch == "identity" else identity
    )
    other_config = {"tenant": "two"} if mismatch == "config" else config
    try:
        with pytest.raises(VectorStoreError, match="mismatch"):
            adapter.store_cached_vectors(
                root, other_identity, {"hash": b"vector"}, other_config
            )
    finally:
        adapter.abort()
        adapter.close()


def test_adapter_wraps_staged_write_failure_as_vector_store_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mark staged persistence errors so core code can propagate them fatally.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to inject a failure into the session writer.

    Returns
    -------
    None
        The adapter raises VectorStoreError and retains the plugin cause.
    """
    store = SQLiteVectorStore()
    identity = _identity(store)
    session = store.begin_write_session(tmp_path, identity, {})
    adapter = VectorStoreWriteAdapter(
        store,
        session,
        root=tmp_path,
        identity=identity,
        config={},
    )
    persist_vectors = session.store_vectors

    def fail_write(_rows: Sequence[PreparedVectorRow]) -> None:
        """Write to the staged transaction, then raise a simulated failure.

        Parameters
        ----------
        _rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Batch passed to the staged writer.

        Returns
        -------
        None
            This test double raises after staging the batch.

        Raises
        ------
        RuntimeError
            Simulated vector-store storage failure.
        """
        persist_vectors(_rows)
        msg = "injected sqlite vector write failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(session, "store_vectors", fail_write)
    try:
        with pytest.raises(VectorStoreError, match="vector write failed") as caught:
            adapter.store_vectors(
                tmp_path,
                identity,
                [_prepared_row("symbol:failed", 9, "hash-failed")],
                {},
            )
        assert isinstance(caught.value.__cause__, RuntimeError)
        adapter.abort()
    finally:
        adapter.close()

    snapshot = store.vector_snapshot(
        VectorSnapshotRequest(
            root=tmp_path,
            identity=identity,
            object_type="symbol",
            config={},
        )
    )
    assert snapshot.rows == ()


def test_adapter_proxies_safe_reads_only_after_session_finalization(
    tmp_path: Path,
) -> None:
    """Proxy safe original-store reads and reject bypass operations in-session.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.

    Returns
    -------
    None
        Snapshot reads work after commit; active-session snapshot and purge fail.
    """
    store, identity, config, adapter = _context(tmp_path)
    assert adapter.spec(config) == store.spec(config)
    assert adapter.configuration_json_schema() == store.configuration_json_schema()
    request = VectorSnapshotRequest(
        root=tmp_path,
        identity=identity,
        object_type="symbol",
        config=config,
    )
    try:
        with pytest.raises(VectorStoreError, match="session is active"):
            adapter.vector_snapshot(request)
        with pytest.raises(VectorStoreError, match="purge is unavailable"):
            adapter.purge_vector_sets(
                VectorStorePurgeRequest(
                    root=tmp_path,
                    identity=identity,
                    config=config,
                    stale=True,
                    all_sets=False,
                    dry_run=True,
                )
            )
        adapter.commit()
        assert adapter.vector_snapshot(request).rows == ()
    finally:
        adapter.close()
