"""Transactional write-session tests for the DuckDB vector store."""

from __future__ import annotations

import builtins
import importlib.util
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import duckdb
import pytest

from codira.contracts import (
    EmbeddingEngineSpec,
    PendingEmbeddingRow,
    PreparedVectorRow,
    VectorSetIdentity,
)
from codira.semantic.embeddings import serialize_vector
from codira.vector_write_session import (
    VectorStoreWriteSession,
    VectorStoreWriteSessionFactory,
)
from codira_vector_store_duckdb import DuckDBVectorStore, get_vector_store_path
import codira_vector_store_duckdb as duckdb_vector_store_module


def _identity(
    store: DuckDBVectorStore, model_version: str = "session-test"
) -> VectorSetIdentity:
    """Build a deterministic vector-set identity for session tests.

    Parameters
    ----------
    store : codira_vector_store_duckdb.DuckDBVectorStore
        Store used to create the vector-store identity.
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
    """Build a prepared vector row.

    Parameters
    ----------
    stable_id : str
        Stable vector-binding identity.
    object_id : int
        Object identifier for pending-row operations.
    content_hash : str
        Content-addressed cache key.
    vector : bytes or None, optional
        Serialized vector, or ``None`` for pending-only input.

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


class _FailingConnection:
    """Inject selected transaction failures while retaining a real connection.

    Parameters
    ----------
    connection : duckdb.DuckDBPyConnection
        Connection to delegate non-failing operations to.
    failures : collections.abc.Mapping[str, BaseException]
        SQL statements that should raise their mapped exception.

    Returns
    -------
    None
    """

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        failures: Mapping[str, BaseException],
    ) -> None:
        """Store the connection and injected transaction failures.

        Parameters
        ----------
        connection : duckdb.DuckDBPyConnection
            Connection to delegate non-failing operations to.
        failures : collections.abc.Mapping[str, BaseException]
            SQL statements that should raise their mapped exception.

        Returns
        -------
        None
        """
        self._connection = connection
        self._failures = failures
        self.closed = False

    def execute(self, statement: str, parameters: object | None = None) -> object:
        """Raise an injected failure or execute against the real connection.

        Parameters
        ----------
        statement : str
            SQL statement to execute.
        parameters : object or None, optional
            Bound parameters forwarded to DuckDB.

        Returns
        -------
        object
            DuckDB query result.

        Raises
        ------
        BaseException
            The mapped failure when the statement is configured to fail.
        """
        failure = self._failures.get(statement)
        if failure is not None:
            raise failure
        if parameters is None:
            return self._connection.execute(statement)
        return self._connection.execute(statement, parameters)

    def close(self) -> None:
        """Close the real connection and record the cleanup attempt.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        self.closed = True
        self._connection.close()


def test_session_protocol_is_additive_and_transactional(tmp_path: Path) -> None:
    """Expose the optional session factory without changing the base API.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the DuckDB database.

    Returns
    -------
    None
        Store and session satisfy their runtime-checkable protocols.
    """
    store = DuckDBVectorStore()
    assert isinstance(store, VectorStoreWriteSessionFactory)
    session = store.begin_write_session(tmp_path, _identity(store), {})
    assert isinstance(session, VectorStoreWriteSession)
    session.abort()
    session.close()


def test_plugin_import_does_not_require_optional_core_session_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep plugin import compatible with core versions lacking the protocol.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture that blocks imports of the optional session protocol module.

    Returns
    -------
    None
        The plugin source loads without importing that module.
    """
    source = Path(duckdb_vector_store_module.__file__)
    spec = importlib.util.spec_from_file_location(
        "codira_vector_store_duckdb_compat_probe", source
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
        """Reject only imports of the optional session module."""
        if name == "codira.vector_write_session":
            raise ModuleNotFoundError(name=name)
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_optional_session_import)
    spec.loader.exec_module(module)
    assert module.DuckDBVectorStore


def test_session_reads_staged_writes_and_commit_publishes_them(tmp_path: Path) -> None:
    """Keep staged rows isolated while allowing read-your-writes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.

    Returns
    -------
    None
        Own reads see staged changes, and other connections see them after commit.
    """
    store = DuckDBVectorStore()
    identity = _identity(store)
    row = _row("symbol:one", 1, "hash-one", serialize_vector([1.0, 0.0, 0.0]))
    session = store.begin_write_session(tmp_path, identity, {})
    try:
        session.store_cached_vectors({"hash-one": row.vector or b""})
        session.store_pending_vectors([row])
        session.store_vectors([row])
        assert session.load_cached_vectors(["hash-one", "missing"]) == {
            "hash-one": row.vector
        }
        with duckdb.connect(str(get_vector_store_path(tmp_path))) as conn:
            assert conn.execute("SELECT COUNT(*) FROM vector_cache").fetchone() == (0,)
            assert conn.execute("SELECT COUNT(*) FROM vectors").fetchone() == (0,)
            assert conn.execute("SELECT COUNT(*) FROM pending_vectors").fetchone() == (
                0,
            )
        session.commit()
    finally:
        session.close()

    assert store.load_cached_vectors(tmp_path, identity, ["hash-one"], {}) == {
        "hash-one": row.vector
    }
    with duckdb.connect(str(get_vector_store_path(tmp_path)), read_only=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM vectors").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM pending_vectors").fetchone() == (1,)


def test_session_abort_rolls_back_writes_and_new_vector_set(tmp_path: Path) -> None:
    """Discard staged cache, binding, pending rows, and identity creation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.

    Returns
    -------
    None
        Abort leaves no data or vector-set metadata from the session.
    """
    store = DuckDBVectorStore()
    identity = _identity(store, "aborted-session")
    vector = serialize_vector([1.0, 0.0, 0.0])
    session = store.begin_write_session(tmp_path, identity, {})
    session.store_cached_vectors({"aborted": vector})
    session.store_vectors([_row("aborted", 1, "aborted", vector)])
    session.store_pending_vectors([_row("aborted", 1, "aborted")])
    session.abort()
    session.close()

    with duckdb.connect(str(get_vector_store_path(tmp_path)), read_only=True) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM vector_sets WHERE model_version = ?",
            ("aborted-session",),
        ).fetchone() == (0,)
        for table in ("vector_cache", "vectors", "pending_vectors"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)


def test_failed_write_does_not_persist_and_session_can_abort(tmp_path: Path) -> None:
    """Reject an invalid vector before persistence and roll back its session.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for vector-store state.

    Returns
    -------
    None
        A failed vector conversion leaves no partial committed cache row.
    """
    store = DuckDBVectorStore()
    identity = _identity(store)
    session = store.begin_write_session(tmp_path, identity, {})
    with pytest.raises(struct.error):
        session.store_cached_vectors({"bad-dimension": serialize_vector([1.0, 0.0])})
    session.abort()
    session.close()

    with duckdb.connect(str(get_vector_store_path(tmp_path)), read_only=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM vector_cache").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM vector_sets").fetchone() == (0,)


def test_close_aborts_unfinished_session_and_finalized_session_rejects_reads(
    tmp_path: Path,
) -> None:
    """Make close abort pending work and reject calls after commit.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for DuckDB state.

    Returns
    -------
    None
        Close rolls back, and committed sessions reject subsequent operations.
    """
    store = DuckDBVectorStore()
    identity = _identity(store)
    vector = serialize_vector([1.0, 0.0, 0.0])
    unfinished = store.begin_write_session(tmp_path, identity, {})
    unfinished.store_cached_vectors({"close-abort": vector})
    unfinished.close()
    assert store.load_cached_vectors(tmp_path, identity, ["close-abort"], {}) == {}

    committed = store.begin_write_session(tmp_path, identity, {})
    committed.commit()
    with pytest.raises(RuntimeError, match="not active"):
        committed.load_cached_vectors(["close-abort"])
    committed.close()


def test_commit_failure_preserves_original_error_when_rollback_fails(
    tmp_path: Path,
) -> None:
    """Keep the commit error when cleanup rollback also fails.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for DuckDB state.

    Returns
    -------
    None
        Commit reports its original error and leaves the session finalized.
    """
    store = DuckDBVectorStore()
    session = store.begin_write_session(tmp_path, _identity(store), {})
    commit_error = RuntimeError("commit failed")
    rollback_error = RuntimeError("rollback failed")
    connection = _FailingConnection(
        session._conn,
        {"COMMIT": commit_error, "ROLLBACK": rollback_error},
    )
    session._conn = cast("duckdb.DuckDBPyConnection", connection)

    with pytest.raises(RuntimeError) as exc_info:
        session.commit()

    assert exc_info.value is commit_error
    assert session._active is False
    session.close()
    assert connection.closed


def test_close_still_closes_connection_when_abort_rollback_fails(
    tmp_path: Path,
) -> None:
    """Close the connection even when abort rollback raises.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for DuckDB state.

    Returns
    -------
    None
        Close propagates the rollback error after closing its connection.
    """
    store = DuckDBVectorStore()
    session = store.begin_write_session(tmp_path, _identity(store), {})
    rollback_error = RuntimeError("rollback failed")
    connection = _FailingConnection(session._conn, {"ROLLBACK": rollback_error})
    session._conn = cast("duckdb.DuckDBPyConnection", connection)

    with pytest.raises(RuntimeError) as exc_info:
        session.close()

    assert exc_info.value is rollback_error
    assert connection.closed
    assert session._active is False
    assert session._closed is True
