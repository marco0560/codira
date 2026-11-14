"""Contract, parity, and rollback coverage for DuckDB index streaming."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
import sqlite3
from pathlib import Path

import pytest

from codira.contracts import (
    BackendPersistFullIndexFile,
    BackendPersistFullIndexRequest,
    EmbeddingEngineSpec,
    EmbeddingIndexingPolicy,
    PreparedVectorRow,
    VectorSetIdentity,
    VectorSnapshotRequest,
)
from codira.index_stream_contracts import (
    BackendPersistFullIndexStreamRequest,
    FullIndexStreamingBulkBackend,
)
from codira.models import (
    AnalysisResult,
    CallSite,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
)
from codira.semantic.embeddings import EmbeddingBackendSpec

from codira_backend_duckdb import DuckDBIndexBackend, _duckdb_db_path
from codira_backend_duckdb import duckdb_support as duckdb_support_module
from codira_vector_store_sqlite import (
    SQLiteVectorStore,
    SQLiteVectorStoreWriteSession,
    get_vector_store_path,
)


def _file(root: Path, name: str) -> BackendPersistFullIndexFile:
    """Build one minimal analyzed file for backend contract tests.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to construct the source path.
    name : str
        Module name and source filename stem.

    Returns
    -------
    codira.contracts.BackendPersistFullIndexFile
        A file request with one module artifact.
    """
    path = root / "src" / f"{name}.py"
    return BackendPersistFullIndexFile(
        path=path,
        file_metadata=FileMetadataSnapshot(
            path=path,
            sha256=f"hash-{name}",
            mtime=1.0,
            size=0,
            analyzer_name="python",
            analyzer_version="test",
        ),
        analysis=AnalysisResult(
            source_path=path,
            module=ModuleArtifact(
                name=name,
                stable_id=f"python:module:{name}",
                docstring=None,
                has_docstring=0,
            ),
            classes=(),
            functions=(),
            declarations=(),
            imports=(),
        ),
    )


def _bulk_request(
    root: Path,
    files: tuple[BackendPersistFullIndexFile, ...],
) -> BackendPersistFullIndexRequest:
    """Build the legacy bulk request for parity comparisons.

    Parameters
    ----------
    root : pathlib.Path
        Repository root being indexed.
    files : tuple[codira.contracts.BackendPersistFullIndexFile, ...]
        Ordered analyzed files.

    Returns
    -------
    codira.contracts.BackendPersistFullIndexRequest
        A legacy request with embeddings excluded.
    """
    return BackendPersistFullIndexRequest(
        root=root,
        files=files,
        embedding_backend=EmbeddingBackendSpec("test", "1", 2),
        embedding_indexing=EmbeddingIndexingPolicy(frozenset()),
        defer_embeddings=False,
        vector_store=None,
        vector_set_identity=None,
        vector_store_config={},
        coverage_complete=True,
        analyzers=(),
    )


def _stream_request(
    root: Path,
    files: Iterator[BackendPersistFullIndexFile],
    coverage_complete: Callable[[], bool],
) -> BackendPersistFullIndexStreamRequest:
    """Build a streaming request with the same metadata as a bulk request.

    Parameters
    ----------
    root : pathlib.Path
        Repository root being indexed.
    files : collections.abc.Iterator[codira.contracts.BackendPersistFullIndexFile]
        Ordered file iterator.
    coverage_complete : collections.abc.Callable[[], bool]
        Callback evaluated once the iterator has been consumed.

    Returns
    -------
    codira.index_stream_contracts.BackendPersistFullIndexStreamRequest
        Streaming request for the backend.
    """
    return BackendPersistFullIndexStreamRequest(
        root=root,
        files=files,
        embedding_backend=EmbeddingBackendSpec("test", "1", 2),
        embedding_indexing=EmbeddingIndexingPolicy(frozenset()),
        defer_embeddings=False,
        vector_store=None,
        vector_set_identity=None,
        vector_store_config={},
        coverage_complete=coverage_complete,
        analyzers=(),
    )


def _embedding_file(
    root: Path,
    name: str,
    content: str | None = None,
) -> BackendPersistFullIndexFile:
    """Build an analyzed module whose docstring produces an embedding row.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to construct the source path.
    name : str
        Module name and default embedding text.
    content : str | None, optional
        Explicit shared text for cache-reuse cases.

    Returns
    -------
    codira.contracts.BackendPersistFullIndexFile
        File request with one eligible symbol embedding.
    """
    item = _file(root, name)
    analysis = replace(
        item.analysis,
        module=replace(
            item.analysis.module,
            docstring=(f"documentation for {name}" if content is None else content),
            has_docstring=1,
        ),
    )
    return replace(item, analysis=analysis)


def _relationship_file(root: Path, name: str) -> BackendPersistFullIndexFile:
    """Build repeated identical call records for relationship dedup coverage.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to construct the source path.
    name : str
        Module name used to distinguish relation owners.

    Returns
    -------
    codira.contracts.BackendPersistFullIndexFile
        File request with a duplicate callsite under one callable.
    """
    item = _file(root, name)
    duplicate_call = CallSite(
        kind="name", target="shared_target", lineno=2, col_offset=4
    )
    function = FunctionArtifact(
        name="caller",
        stable_id=f"python:function:{name}:caller",
        lineno=1,
        end_lineno=3,
        signature="def caller()",
        docstring=None,
        has_docstring=0,
        is_method=0,
        is_public=1,
        parameters=(),
        returns_value=0,
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=(duplicate_call, duplicate_call),
        callable_refs=(),
    )
    return replace(
        item,
        analysis=replace(item.analysis, functions=(function,)),
    )


def _vector_identity(store: SQLiteVectorStore) -> VectorSetIdentity:
    """Build a deterministic vector set matching the test embedding backend.

    Parameters
    ----------
    store : codira_vector_store_sqlite.SQLiteVectorStore
        Store whose plugin identity is included in the vector-set identity.

    Returns
    -------
    codira.contracts.VectorSetIdentity
        Identity for three-dimensional synthetic embeddings.
    """
    backend = EmbeddingBackendSpec("test", "1", 3)
    return VectorSetIdentity(
        engine=EmbeddingEngineSpec(
            engine=backend.name,
            engine_version=backend.version,
            model="test-model",
            model_version="1",
            dimension=backend.dim,
        ),
        vector_store=store.spec({}),
    )


def _vector_bindings(
    root: Path,
    store: SQLiteVectorStore,
    identity: VectorSetIdentity,
) -> tuple[tuple[str, str, str], ...]:
    """Read materialized vector identities from a vector-store snapshot.

    Parameters
    ----------
    root : pathlib.Path
        Repository root that owns the store.
    store : codira_vector_store_sqlite.SQLiteVectorStore
        Vector store to inspect.
    identity : codira.contracts.VectorSetIdentity
        Vector-set identity to read.

    Returns
    -------
    tuple[tuple[str, str, str], ...]
        Ordered object type, stable ID, and content hash bindings.
    """
    snapshot = store.vector_snapshot(
        VectorSnapshotRequest(root, identity, "symbol", {})
    )
    return tuple(
        (row.object_type, row.stable_id, row.content_hash) for row in snapshot.rows
    )


def _pending_vector_bindings(
    root: Path,
    store: SQLiteVectorStore,
    identity: VectorSetIdentity,
) -> tuple[tuple[str, int, str, str], ...]:
    """Read deferred vector IDs and identities for one vector set.

    Parameters
    ----------
    root : pathlib.Path
        Repository root that owns the store.
    store : codira_vector_store_sqlite.SQLiteVectorStore
        Vector store to inspect.
    identity : codira.contracts.VectorSetIdentity
        Vector-set identity to read.

    Returns
    -------
    tuple[tuple[str, int, str, str], ...]
        Ordered object type, object ID, stable ID, and content hash rows.
    """
    vector_set_id = store.ensure_vector_set(root, identity, {})
    with sqlite3.connect(get_vector_store_path(root)) as connection:
        rows = connection.execute(
            """SELECT object_type, object_id, stable_id, content_hash
            FROM pending_vectors WHERE vector_set_id = ? ORDER BY object_id""",
            (vector_set_id,),
        ).fetchall()
    return tuple(
        (str(object_type), int(object_id), str(stable_id), str(content_hash))
        for object_type, object_id, stable_id, content_hash in rows
    )


def _snapshot(root: Path) -> tuple[tuple[tuple[object, ...], ...], ...]:
    """Read stable DuckDB publication state for parity and rollback assertions.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the DuckDB index.

    Returns
    -------
    tuple[object, ...]
        Sorted rows from core index and runtime inventory tables.
    """
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(str(_duckdb_db_path(root)))
    try:
        return (
            tuple(
                connection.execute("SELECT hash FROM files ORDER BY hash").fetchall()
            ),
            tuple(
                connection.execute("SELECT name FROM modules ORDER BY name").fetchall()
            ),
            tuple(
                connection.execute(
                    "SELECT object_type, object_id, content_hash FROM embeddings "
                    "ORDER BY object_type, object_id"
                ).fetchall()
            ),
            tuple(
                connection.execute(
                    "SELECT object_type, object_id, stable_id, content_hash "
                    "FROM pending_embeddings ORDER BY object_type, object_id"
                ).fetchall()
            ),
            tuple(
                connection.execute(
                    "SELECT caller_file_id, caller_name, callee_name, resolved "
                    "FROM call_edges ORDER BY caller_file_id, caller_name, callee_name"
                ).fetchall()
            ),
            tuple(
                connection.execute(
                    "SELECT backend_name, backend_version, coverage_complete "
                    "FROM index_runtime ORDER BY singleton"
                ).fetchall()
            ),
            tuple(
                connection.execute(
                    "SELECT index_name FROM duckdb_indexes() ORDER BY index_name"
                ).fetchall()
            ),
        )
    finally:
        connection.close()


def test_duckdb_streaming_full_index_matches_legacy_and_checks_coverage_late(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Persist streamed rows with legacy parity and late coverage evaluation.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to force small row-family flush batches.
    tmp_path : pathlib.Path
        Isolated roots for both full-index persistence APIs.

    Returns
    -------
    None
        The test verifies persisted parity and callback ordering.
    """
    pytest.importorskip("duckdb")
    legacy_root = tmp_path / "legacy"
    stream_root = tmp_path / "stream"
    legacy_root.mkdir()
    stream_root.mkdir()
    legacy_files = (_file(legacy_root, "alpha"), _file(legacy_root, "beta"))
    stream_files = (_file(stream_root, "alpha"), _file(stream_root, "beta"))
    backend = DuckDBIndexBackend()
    assert isinstance(backend, FullIndexStreamingBulkBackend)
    monkeypatch.setattr(
        "codira_backend_duckdb._STRUCTURAL_ROW_FLUSH_THRESHOLD",
        1,
    )

    backend.persist_full_index(_bulk_request(legacy_root, legacy_files))
    consumed: list[str] = []
    callback_calls: list[bool] = []

    def ordered_files() -> Iterator[BackendPersistFullIndexFile]:
        for item in stream_files:
            consumed.append(item.file_metadata.path.stem)
            yield item

    def coverage_complete() -> bool:
        callback_calls.append(True)
        assert consumed == ["alpha", "beta"]
        return True

    backend.persist_full_index_stream(
        _stream_request(stream_root, ordered_files(), coverage_complete)
    )

    assert consumed == ["alpha", "beta"]
    assert callback_calls == [True]
    assert _snapshot(stream_root) == _snapshot(legacy_root)


def test_duckdb_streaming_full_index_rolls_back_when_late_coverage_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Restore published DuckDB state when the post-consumption callback fails.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to force an intermediate transactional batch flush.
    tmp_path : pathlib.Path
        Isolated repository root.

    Returns
    -------
    None
        The test verifies the prior database snapshot survives the failure.
    """
    pytest.importorskip("duckdb")
    root = tmp_path / "repo"
    root.mkdir()
    backend = DuckDBIndexBackend()
    backend.persist_full_index(_bulk_request(root, (_file(root, "before"),)))
    before = _snapshot(root)
    consumed: list[str] = []
    monkeypatch.setattr(
        "codira_backend_duckdb._STRUCTURAL_ROW_FLUSH_THRESHOLD",
        1,
    )

    def stream_files() -> Iterator[BackendPersistFullIndexFile]:
        item = _file(root, "after")
        consumed.append("after")
        yield item

    def fail_coverage() -> bool:
        assert consumed == ["after"]
        raise RuntimeError("coverage callback failed")

    with pytest.raises(RuntimeError, match="coverage callback failed"):
        backend.persist_full_index_stream(
            _stream_request(root, stream_files(), fail_coverage)
        )

    assert _snapshot(root) == before


@pytest.mark.parametrize("defer_embeddings", [False, True])
def test_duckdb_streaming_embedding_parity_preserves_external_ids_and_batches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    defer_embeddings: bool,
) -> None:
    """Match legacy materialized or deferred embeddings across tiny flushes.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture for deterministic embedding generation and batch capture.
    tmp_path : pathlib.Path
        Isolated roots for legacy and streaming full-index persistence.
    defer_embeddings : bool
        Whether to compare pending rows or materialized vectors.

    Returns
    -------
    None
        DuckDB rows, external bindings, and stable object IDs match the legacy
        bulk implementation across repeated fresh-index batches.
    """
    pytest.importorskip("duckdb")
    legacy_root = tmp_path / "legacy"
    stream_root = tmp_path / "stream"
    for root in (legacy_root, stream_root):
        codira_dir = root / ".codira"
        codira_dir.mkdir(parents=True)
        (codira_dir / "config.toml").write_text(
            '[embeddings]\nenabled = true\nvector_store = "sqlite"\n',
            encoding="utf-8",
        )
    legacy_store = SQLiteVectorStore()
    stream_store = SQLiteVectorStore()
    legacy_identity = _vector_identity(legacy_store)
    stream_identity = _vector_identity(stream_store)
    embedding_backend = EmbeddingBackendSpec("test", "1", 3)
    eligibility = EmbeddingIndexingPolicy(frozenset({"symbol"}))
    legacy_files = (
        _embedding_file(legacy_root, "alpha", "shared documentation"),
        _embedding_file(legacy_root, "beta", "shared documentation"),
        _embedding_file(legacy_root, "gamma"),
    )
    stream_files = (
        _embedding_file(stream_root, "alpha", "shared documentation"),
        _embedding_file(stream_root, "beta", "shared documentation"),
        _embedding_file(stream_root, "gamma"),
    )

    def embed_texts(texts: list[str], root: Path | None = None) -> list[list[float]]:
        """Return repeatable three-dimensional vectors for test payloads."""
        del root
        return [[1.0, float(index % 2), 0.0] for index, _text in enumerate(texts)]

    monkeypatch.setattr(duckdb_support_module, "embed_texts", embed_texts)
    monkeypatch.setattr(
        "codira_backend_duckdb._STRUCTURAL_ROW_FLUSH_THRESHOLD",
        1,
    )
    backend = DuckDBIndexBackend()
    legacy_result = backend.persist_full_index(
        BackendPersistFullIndexRequest(
            root=legacy_root,
            files=legacy_files,
            embedding_backend=embedding_backend,
            embedding_indexing=eligibility,
            defer_embeddings=defer_embeddings,
            vector_store=legacy_store,
            vector_set_identity=legacy_identity,
            vector_store_config={},
            coverage_complete=True,
            analyzers=(),
        )
    )
    if not defer_embeddings:
        backend.persist_full_index(
            BackendPersistFullIndexRequest(
                root=stream_root,
                files=stream_files,
                embedding_backend=embedding_backend,
                embedding_indexing=eligibility,
                defer_embeddings=False,
                vector_store=stream_store,
                vector_set_identity=stream_identity,
                vector_store_config={},
                coverage_complete=True,
                analyzers=(),
            )
        )

    batch_ids: list[tuple[int, ...]] = []
    if defer_embeddings:
        original_batch_write = SQLiteVectorStoreWriteSession.store_pending_vectors

        def capture_pending_batch(
            session: SQLiteVectorStoreWriteSession,
            rows: tuple[PreparedVectorRow, ...] | list[PreparedVectorRow],
        ) -> None:
            batch_ids.append(tuple(row.row.object_id for row in rows))
            original_batch_write(session, rows)

        monkeypatch.setattr(
            SQLiteVectorStoreWriteSession,
            "store_pending_vectors",
            capture_pending_batch,
        )
    else:
        original_batch_write = SQLiteVectorStoreWriteSession.store_vectors

        def capture_materialized_batch(
            session: SQLiteVectorStoreWriteSession,
            rows: tuple[PreparedVectorRow, ...] | list[PreparedVectorRow],
        ) -> None:
            batch_ids.append(tuple(row.row.object_id for row in rows))
            original_batch_write(session, rows)

        monkeypatch.setattr(
            SQLiteVectorStoreWriteSession,
            "store_vectors",
            capture_materialized_batch,
        )

    def stream_file_items() -> Iterator[BackendPersistFullIndexFile]:
        yield from stream_files

    # Keep the generator lazy and ordered; the callback is deliberately late.
    callback_seen: list[bool] = []

    def coverage_complete() -> bool:
        callback_seen.append(True)
        return True

    stream_request = BackendPersistFullIndexStreamRequest(
        root=stream_root,
        files=stream_file_items(),
        embedding_backend=embedding_backend,
        embedding_indexing=eligibility,
        defer_embeddings=defer_embeddings,
        vector_store=stream_store,
        vector_set_identity=stream_identity,
        vector_store_config={},
        coverage_complete=coverage_complete,
        analyzers=(),
    )
    stream_result = backend.persist_full_index_stream(stream_request)

    assert callback_seen == [True]
    assert len(batch_ids) == 3
    assert all(len(batch) == 1 for batch in batch_ids)
    assert sorted(object_id for batch in batch_ids for object_id in batch) == [1, 2, 3]
    if defer_embeddings:
        assert stream_result.embeddings_pending == 3
    else:
        assert legacy_result.embeddings_recomputed == 3
        assert stream_result.embeddings_reused == 3
    assert _snapshot(stream_root) == _snapshot(legacy_root)
    assert len(_snapshot(stream_root)[2]) == (0 if defer_embeddings else 3)
    assert len(_snapshot(stream_root)[3]) == (3 if defer_embeddings else 0)
    if defer_embeddings:
        assert _pending_vector_bindings(stream_root, stream_store, stream_identity) == (
            _pending_vector_bindings(legacy_root, legacy_store, legacy_identity)
        )
    else:
        assert _vector_bindings(stream_root, stream_store, stream_identity) == (
            _vector_bindings(legacy_root, legacy_store, legacy_identity)
        )


def test_duckdb_streaming_relationship_batches_preserve_duplicate_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep per-file deduplication and distinct owners across flush batches.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to force a flush after every input file.
    tmp_path : pathlib.Path
        Isolated roots for bulk and streaming comparisons.

    Returns
    -------
    None
        Each duplicate call is collapsed within its owner while identical
        callsites from separate files remain separate graph edges.
    """
    pytest.importorskip("duckdb")
    legacy_root = tmp_path / "legacy"
    stream_root = tmp_path / "stream"
    legacy_root.mkdir()
    stream_root.mkdir()
    legacy_files = tuple(
        _relationship_file(legacy_root, name) for name in ("alpha", "beta", "gamma")
    )
    stream_files = tuple(
        _relationship_file(stream_root, name) for name in ("alpha", "beta", "gamma")
    )
    monkeypatch.setattr(
        "codira_backend_duckdb._STRUCTURAL_ROW_FLUSH_THRESHOLD",
        1,
    )
    backend = DuckDBIndexBackend()
    backend.persist_full_index(_bulk_request(legacy_root, legacy_files))
    backend.persist_full_index_stream(
        _stream_request(
            stream_root,
            iter(stream_files),
            lambda: True,
        )
    )

    assert _snapshot(stream_root) == _snapshot(legacy_root)
    assert _snapshot(stream_root)[4] == (
        (1, "caller", None, 0),
        (2, "caller", None, 0),
        (3, "caller", None, 0),
    )


@pytest.mark.parametrize("defer_embeddings", [False, True])
def test_duckdb_streaming_late_failure_aborts_external_vector_batches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    defer_embeddings: bool,
) -> None:
    """Abort staged external vector writes when late coverage validation fails.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture for deterministic embeddings and small streamed batches.
    tmp_path : pathlib.Path
        Isolated root for DuckDB and SQLite vector state.
    defer_embeddings : bool
        Whether the staged external rows are materialized or pending.

    Returns
    -------
    None
        DuckDB and externally published vector snapshots remain unchanged.
    """
    pytest.importorskip("duckdb")
    root = tmp_path / "repo"
    (root / ".codira").mkdir(parents=True)
    (root / ".codira" / "config.toml").write_text(
        '[embeddings]\nenabled = true\nvector_store = "sqlite"\n',
        encoding="utf-8",
    )
    store = SQLiteVectorStore()
    identity = _vector_identity(store)
    embedding_backend = EmbeddingBackendSpec("test", "1", 3)
    eligibility = EmbeddingIndexingPolicy(frozenset({"symbol"}))

    def embed_texts(texts: list[str], root: Path | None = None) -> list[list[float]]:
        """Return deterministic vectors for the test modules."""
        del root
        return [[1.0, 0.0, 0.0] for _text in texts]

    monkeypatch.setattr(duckdb_support_module, "embed_texts", embed_texts)
    backend = DuckDBIndexBackend()
    backend.persist_full_index(
        BackendPersistFullIndexRequest(
            root=root,
            files=(_embedding_file(root, "baseline"),),
            embedding_backend=embedding_backend,
            embedding_indexing=eligibility,
            defer_embeddings=defer_embeddings,
            vector_store=store,
            vector_set_identity=identity,
            vector_store_config={},
            coverage_complete=True,
            analyzers=(),
        )
    )
    database_before = _snapshot(root)
    vectors_before = (
        _pending_vector_bindings(root, store, identity)
        if defer_embeddings
        else _vector_bindings(root, store, identity)
    )
    assert vectors_before
    monkeypatch.setattr(
        "codira_backend_duckdb._STRUCTURAL_ROW_FLUSH_THRESHOLD",
        1,
    )

    def fail_coverage() -> bool:
        raise RuntimeError("injected external rollback failure")

    with pytest.raises(RuntimeError, match="injected external rollback failure"):
        backend.persist_full_index_stream(
            BackendPersistFullIndexStreamRequest(
                root=root,
                files=iter((_embedding_file(root, "replacement"),)),
                embedding_backend=embedding_backend,
                embedding_indexing=eligibility,
                defer_embeddings=defer_embeddings,
                vector_store=store,
                vector_set_identity=identity,
                vector_store_config={},
                coverage_complete=fail_coverage,
                analyzers=(),
            )
        )

    assert _snapshot(root) == database_before
    vectors_after = (
        _pending_vector_bindings(root, store, identity)
        if defer_embeddings
        else _vector_bindings(root, store, identity)
    )
    assert vectors_after == vectors_before
