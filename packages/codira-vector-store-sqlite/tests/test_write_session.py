"""Transactional write-session tests for the SQLite vector store.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import builtins
import importlib.util
import sqlite3
from pathlib import Path

import pytest

from codira.contracts import (
    EmbeddingEngineSpec,
    PendingEmbeddingRow,
    PreparedVectorRow,
    VectorSetIdentity,
    VectorSnapshotRequest,
)
from codira.semantic.embeddings import serialize_vector
from codira.vector_write_session import (
    VectorStoreWriteSession,
    VectorStoreWriteSessionFactory,
)
from codira_vector_store_sqlite import SQLiteVectorStore, get_vector_store_path
import codira_vector_store_sqlite as sqlite_vector_store_module


def _identity(
    store: SQLiteVectorStore, model_version: str = "session-test"
) -> VectorSetIdentity:
    """Build a small deterministic vector-set identity.

    Parameters
    ----------
    store : codira_vector_store_sqlite.SQLiteVectorStore
        Store used to create the vector-store portion of the identity.
    model_version : str, optional
        Model revision for the vector-set identity.

    Returns
    -------
    codira.contracts.VectorSetIdentity
        Complete test identity.
    """
    return VectorSetIdentity(
        engine=EmbeddingEngineSpec(
            engine="session-test",
            engine_version="1",
            model="session-model",
            model_version=model_version,
            dimension=3,
        ),
        vector_store=store.spec({}),
    )


def _row(
    stable_id: str,
    object_id: int,
    content_hash: str,
    vector: bytes | None = None,
) -> PreparedVectorRow:
    """Build a prepared row for materialized or pending writes.

    Parameters
    ----------
    stable_id : str
        Stable identity for the vector binding.
    object_id : int
        Structural object identifier used by pending-row operations.
    content_hash : str
        Content-addressed vector cache key.
    vector : bytes or None, optional
        Serialized vector payload, or ``None`` for pending-only input.

    Returns
    -------
    codira.contracts.PreparedVectorRow
        Prepared test row.
    """
    return PreparedVectorRow(
        row=PendingEmbeddingRow(
            object_type="symbol",
            object_id=object_id,
            stable_id=stable_id,
            text=f"text for {stable_id}",
        ),
        content_hash=content_hash,
        vector=vector,
    )


def _pending_rows(root: Path, identity: VectorSetIdentity) -> list[tuple[object, ...]]:
    """Read committed pending rows for one vector-set identity.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the vector database.
    identity : codira.contracts.VectorSetIdentity
        Vector set whose pending rows are selected.

    Returns
    -------
    list[tuple[object, ...]]
        Pending rows in stable-ID order.
    """
    store = SQLiteVectorStore()
    vector_set_id = store.ensure_vector_set(root, identity, {})
    with sqlite3.connect(get_vector_store_path(root)) as connection:
        return list(
            connection.execute(
                """SELECT object_type, object_id, stable_id, content_hash, text
                FROM pending_vectors WHERE vector_set_id = ? ORDER BY stable_id""",
                (vector_set_id,),
            ).fetchall()
        )


def test_session_factory_and_protocol_are_additive(tmp_path: Path) -> None:
    """Expose the optional capability without changing the base vector API.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the vector database.

    Returns
    -------
    None
        The factory and session satisfy their independent protocols.
    """
    store = SQLiteVectorStore()
    assert isinstance(store, VectorStoreWriteSessionFactory)
    session = store.begin_write_session(tmp_path, _identity(store), {})
    assert isinstance(session, VectorStoreWriteSession)
    session.abort()
    session.close()


def test_plugin_import_does_not_require_optional_core_session_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Import the plugin while the new optional core module is unavailable.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to simulate an older core distribution.

    Returns
    -------
    None
        The SQLite plugin module loads without importing the optional protocol.
    """
    source = Path(sqlite_vector_store_module.__file__)
    spec = importlib.util.spec_from_file_location(
        "codira_vector_store_sqlite_compat_probe", source
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_import = builtins.__import__

    def reject_optional_session_import(
        name: str,
        globals_: dict[str, object] | None = None,
        locals_: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        """Reject only imports of the optional core session module.

        Parameters
        ----------
        name : str
            Import name requested by the plugin.
        globals_ : dict[str, object] or None, optional
            Import caller globals forwarded to Python.
        locals_ : dict[str, object] or None, optional
            Import caller locals forwarded to Python.
        fromlist : tuple[str, ...], optional
            Requested imported symbols forwarded to Python.
        level : int, optional
            Relative import level forwarded to Python.

        Returns
        -------
        object
            Imported module returned by Python's original import function.

        Raises
        ------
        ModuleNotFoundError
            If the optional session module is requested.
        """
        if name == "codira.vector_write_session":
            raise ModuleNotFoundError(name=name)
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_optional_session_import)
    spec.loader.exec_module(module)
    assert module.SQLiteVectorStore


def test_session_reads_its_cache_writes_and_hides_them_until_commit(
    tmp_path: Path,
) -> None:
    """Keep staged cache payloads private while supporting cache reuse in-session.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the vector database.

    Returns
    -------
    None
        Own reads see staged cache entries while another connection sees none.
    """
    store = SQLiteVectorStore()
    identity = _identity(store)
    vector = serialize_vector([1.0, 0.0, 0.0])
    vector_set_id = store.ensure_vector_set(tmp_path, identity, {})
    table_name = sqlite_vector_store_module._payload_table_name(vector_set_id)
    session = store.begin_write_session(tmp_path, identity, {})
    try:
        session.store_cached_vectors({"staged": vector})
        assert session.load_cached_vectors(["staged", "missing"]) == {"staged": vector}

        reader = sqlite_vector_store_module._connect(get_vector_store_path(tmp_path))
        try:
            visible = reader.execute(
                f"""SELECT payloads.content_hash
                FROM vector_payloads payloads
                JOIN {table_name} payload_index ON payload_index.rowid = payloads.id
                WHERE payloads.vector_set_id = ?""",
                (vector_set_id,),
            ).fetchall()
        finally:
            reader.close()
        assert visible == []
        session.commit()
    finally:
        session.close()

    assert store.load_cached_vectors(tmp_path, identity, ["staged"], {}) == {
        "staged": vector
    }


def test_session_batches_cache_lookup_and_reuses_existing_cache(tmp_path: Path) -> None:
    """Reuse committed cache rows through the session's bounded lookup path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for cache rows.

    Returns
    -------
    None
        Lookup across multiple SQL batches returns the existing cache entries.
    """
    store = SQLiteVectorStore()
    identity = _identity(store)
    vectors = {
        f"cache-{index}": serialize_vector([float(index % 3 == 0), 1.0, 0.0])
        for index in range(925)
    }
    store.store_cached_vectors(tmp_path, identity, vectors, {})

    session = store.begin_write_session(tmp_path, identity, {})
    try:
        assert session.load_cached_vectors([*vectors, "absent"]) == vectors
        session.abort()
    finally:
        session.close()


def test_session_commits_materialized_and_pending_operations(tmp_path: Path) -> None:
    """Commit cache, binding, and pending mutations together.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.

    Returns
    -------
    None
        Commit publishes writes and preserves pending deletion semantics.
    """
    store = SQLiteVectorStore()
    identity = _identity(store)
    rows = [
        _row(
            "symbol:one",
            1,
            "hash-one",
            serialize_vector([1.0, 0.0, 0.0]),
        ),
        _row("symbol:two", 2, "hash-two"),
    ]
    session = store.begin_write_session(tmp_path, identity, {})
    try:
        session.store_cached_vectors({"hash-one": rows[0].vector or b""})
        session.store_pending_vectors(rows)
        session.store_vectors(rows)
        session.delete_pending_vectors(rows[:1])
        session.commit()
    finally:
        session.close()

    assert [row[2] for row in _pending_rows(tmp_path, identity)] == ["symbol:two"]
    snapshot = store.vector_snapshot(
        VectorSnapshotRequest(
            root=tmp_path,
            identity=identity,
            object_type="symbol",
            config={},
        )
    )
    assert [(row.stable_id, row.content_hash) for row in snapshot.rows] == [
        ("symbol:one", "hash-one")
    ]

    clear_session = store.begin_write_session(tmp_path, identity, {})
    try:
        clear_session.clear_pending_vectors()
        clear_session.commit()
    finally:
        clear_session.close()
    assert _pending_rows(tmp_path, identity) == []


@pytest.mark.parametrize("operation", ["cache", "binding", "pending", "clear"])
def test_abort_rolls_back_every_write_operation(tmp_path: Path, operation: str) -> None:
    """Rollback each staged operation without changing committed vector state.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.
    operation : str
        Session operation whose writes are aborted.

    Returns
    -------
    None
        Previously committed cache, bindings, and pending rows remain unchanged.
    """
    store = SQLiteVectorStore()
    identity = _identity(store)
    baseline = _row(
        "baseline",
        1,
        "baseline-hash",
        serialize_vector([1.0, 0.0, 0.0]),
    )
    store.store_vectors(tmp_path, identity, [baseline], {})
    store.store_pending_vectors(tmp_path, identity, [_row("old-pending", 7, "old")], {})
    before_pending = _pending_rows(tmp_path, identity)

    session = store.begin_write_session(tmp_path, identity, {})
    try:
        if operation == "cache":
            session.store_cached_vectors({"aborted-cache": baseline.vector or b""})
        elif operation == "binding":
            session.store_vectors(
                [
                    _row(
                        "baseline",
                        1,
                        "replacement-hash",
                        serialize_vector([0.0, 1.0, 0.0]),
                    )
                ]
            )
        elif operation == "pending":
            session.store_pending_vectors([_row("new-pending", 8, "new")])
        else:
            session.clear_pending_vectors()
        session.abort()
    finally:
        session.close()

    assert _pending_rows(tmp_path, identity) == before_pending
    snapshot = store.vector_snapshot(
        VectorSnapshotRequest(
            root=tmp_path,
            identity=identity,
            object_type="symbol",
            config={},
        )
    )
    assert [(row.stable_id, row.content_hash) for row in snapshot.rows] == [
        ("baseline", "baseline-hash")
    ]
    assert store.load_cached_vectors(tmp_path, identity, ["aborted-cache"], {}) == {}


def test_session_close_aborts_and_finalized_sessions_reject_mutations(
    tmp_path: Path,
) -> None:
    """Make close safe by default and enforce one explicit finalization.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.

    Returns
    -------
    None
        Close aborts unfinished writes and finalized sessions reject mutations.
    """
    store = SQLiteVectorStore()
    identity = _identity(store)
    vector = serialize_vector([1.0, 0.0, 0.0])
    session = store.begin_write_session(tmp_path, identity, {})
    session.store_cached_vectors({"close-abort": vector})
    session.close()
    assert store.load_cached_vectors(tmp_path, identity, ["close-abort"], {}) == {}

    committed = store.begin_write_session(tmp_path, identity, {})
    committed.commit()
    with pytest.raises(RuntimeError, match="not active"):
        committed.clear_pending_vectors()
    committed.close()


def test_new_vector_set_creation_is_rolled_back_with_session(tmp_path: Path) -> None:
    """Keep identity and sqlite-vec DDL inside the isolated write transaction.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.

    Returns
    -------
    None
        Aborting removes a newly created vector set and virtual table.
    """
    store = SQLiteVectorStore()
    identity = _identity(store, model_version="aborted-new-set")
    session = store.begin_write_session(tmp_path, identity, {})
    session.store_cached_vectors({"new-set-hash": serialize_vector([1.0, 0.0, 0.0])})
    session.abort()
    session.close()

    with sqlite3.connect(get_vector_store_path(tmp_path)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM vector_sets WHERE model_version = ?",
            ("aborted-new-set",),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE ?",
            ("vector_payload_index_%",),
        ).fetchone() == (0,)


def test_session_operations_are_not_available_after_abort(tmp_path: Path) -> None:
    """Reject reads and writes once a session has been aborted.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.

    Returns
    -------
    None
        Session operations raise after abort.
    """
    store = SQLiteVectorStore()
    session = store.begin_write_session(tmp_path, _identity(store), {})
    session.abort()
    with pytest.raises(RuntimeError, match="not active"):
        session.load_cached_vectors(["nope"])
    session.close()
