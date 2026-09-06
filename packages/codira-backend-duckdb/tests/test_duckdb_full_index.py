"""Package-local tests for the first-party DuckDB backend distribution."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING


import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codira.contracts import (
    BackendPersistAnalysisRequest,
    EmbeddingEngineSpec,
    PendingEmbeddingRow,
    VectorSetIdentity,
)
from codira.models import (
    AnalysisResult,
    FileMetadataSnapshot,
    ModuleArtifact,
)
from codira.indexer import index_repo
from codira.index_generation import IndexGenerationStore
from codira.semantic.embeddings import EmbeddingBackendSpec, serialize_vector
from codira.storage import override_storage_root
import codira_backend_duckdb as duckdb_backend_module
from codira_backend_duckdb import (
    DuckDBIndexBackend,
    _duckdb_db_path,
    _duckdb_schema_ddl,
)
from codira_backend_duckdb.duckdb_support import _resolve_cached_prepared_embedding_rows
from codira_backend_duckdb.duckdb_support import _store_pending_embedding_rows
from codira_backend_duckdb.profiling import (
    DuckDBProfileRecorder,
)
from codira_backend_duckdb import duckdb_support as duckdb_support_module
from codira_vector_store_sqlite import SQLiteVectorStore

if TYPE_CHECKING:
    from codira_backend_duckdb.duckdb_support import _DuckDBPersistenceConnection


_UNRESOLVED_CALL_RECORDS = (
    ("name", "", "PyLong_FromLong", 1, 4),
    ("name", "", "PyUnicode_AsUTF8AndSize", 2, 4),
    ("name", "", "system", 3, 4),
)


def test_duckdb_backend_full_prepare_clears_populated_database_in_session(
    tmp_path: Path,
) -> None:
    """
    Clear indexed DuckDB rows while preserving semantic cache rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts a full rebuild clears indexed tables, preserves the
        embedding vector cache, and recreates deferred schema indexes.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = _duckdb_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw = duckdb.connect(str(db_path))
    try:
        for statement in _duckdb_schema_ddl():
            raw.execute(statement)
        raw.execute(
            """
            INSERT INTO files(
                id,
                path,
                hash,
                mtime,
                size,
                analyzer_name,
                analyzer_version
            ) VALUES (1, ?, 'seed-hash', 1.0, 1, 'python', '1.0')
            """,
            (str(tmp_path / "pkg" / "sample.py"),),
        )
        raw.execute(
            """
            INSERT INTO modules(id, file_id, name, docstring, has_docstring)
            VALUES (1, 1, 'pkg.sample', NULL, 0)
            """
        )
        raw.execute(
            """
            INSERT INTO classes(
                id,
                module_id,
                name,
                lineno,
                end_lineno,
                docstring,
                has_docstring
            ) VALUES (1, 1, 'SampleClass', 1, 2, NULL, 0)
            """
        )
        raw.execute(
            """
            INSERT INTO functions(
                id,
                module_id,
                class_id,
                name,
                lineno,
                end_lineno,
                signature,
                docstring,
                has_docstring,
                is_method,
                is_public
            ) VALUES (1, 1, 1, 'method', 1, 1, NULL, NULL, 0, 1, 1)
            """
        )
        raw.commit()
    finally:
        raw.close()

    backend = DuckDBIndexBackend()
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=(), deleted_paths=())
        session.commit()
    finally:
        session.close()

    reopened = duckdb.connect(str(db_path))
    try:
        assert reopened.execute("SELECT COUNT(*) FROM files").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM modules").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM classes").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM functions").fetchone() == (0,)
        assert reopened.execute(
            """
                SELECT COUNT(*)
                FROM duckdb_tables()
                WHERE table_name = 'embedding_vector_cache'
                """
        ).fetchone() == (0,)
        assert reopened.execute(
            """
                SELECT COUNT(*)
                FROM duckdb_indexes()
                WHERE index_name = 'idx_embeddings_object_backend_version'
                """
        ).fetchone() == (1,)
    finally:
        reopened.close()


def test_duckdb_full_prepare_rolls_back_table_recreation(tmp_path: Path) -> None:
    """
    Roll back transactional DuckDB full-rebuild table recreation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts aborting after full prepare restores indexed rows and
        schema indexes.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = _duckdb_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw = duckdb.connect(str(db_path))
    try:
        for statement in _duckdb_schema_ddl():
            raw.execute(statement)
        raw.execute(
            """
            INSERT INTO files(
                id,
                path,
                hash,
                mtime,
                size,
                analyzer_name,
                analyzer_version
            ) VALUES (1, ?, 'seed-hash', 1.0, 1, 'python', '1.0')
            """,
            (str(tmp_path / "pkg" / "sample.py"),),
        )
        raw.execute(
            """
            INSERT INTO symbol_index(
                id,
                name,
                stable_id,
                type,
                module_name,
                file_id,
                lineno
            ) VALUES (
                1,
                'sample',
                'python:module:pkg.sample',
                'module',
                'pkg.sample',
                1,
                1
            )
            """
        )
        raw.commit()
    finally:
        raw.close()

    backend = DuckDBIndexBackend()
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=(), deleted_paths=())
        session.abort()
    finally:
        session.close()

    reopened = duckdb.connect(str(db_path))
    try:
        assert reopened.execute("SELECT COUNT(*) FROM symbol_index").fetchone() == (1,)
        assert reopened.execute(
            """
            SELECT COUNT(*)
            FROM duckdb_indexes()
            WHERE index_name = 'idx_symbol_stable_id'
            """
        ).fetchone() == (1,)
    finally:
        reopened.close()


def test_duckdb_list_symbols_in_module_orders_bounded_results(
    tmp_path: Path,
) -> None:
    """Order bounded module-symbol results independently of insertion order.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts the first twenty symbols use their logical total
        order even when rows were inserted in reverse order.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = _duckdb_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(db_path))
    try:
        for statement in _duckdb_schema_ddl():
            connection.execute(statement)
        file_path = tmp_path / "pkg" / "module.py"
        connection.execute(
            """
            INSERT INTO files(id, path, hash, mtime, size, analyzer_name, analyzer_version)
            VALUES (1, ?, 'hash', 1.0, 1, 'python', '1')
            """,
            (str(file_path),),
        )
        for index in range(25, 0, -1):
            name = f"symbol_{index:02d}"
            connection.execute(
                """
                INSERT INTO symbol_index(
                    id, name, stable_id, type, module_name, file_id, lineno
                ) VALUES (?, ?, ?, 'function', 'pkg.module', 1, ?)
                """,
                (index, name, f"python:function:pkg.module:{name}", index),
            )
        connection.commit()
    finally:
        connection.close()

    rows = DuckDBIndexBackend().list_symbols_in_module(tmp_path, "pkg.module")

    assert [row[2] for row in rows] == [f"symbol_{index:02d}" for index in range(1, 21)]


def test_duckdb_warm_full_reindex_reuses_output_dir_without_duplicate_symbols(
    tmp_path: Path,
) -> None:
    """
    Rebuild an existing DuckDB full index without duplicate symbol failures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace containing a source root and isolated output root.

    Returns
    -------
    None
        The test asserts a second full rebuild into the same DuckDB output
        directory succeeds.
    """
    pytest.importorskip("duckdb")
    source_root = tmp_path / "repo"
    output_root = tmp_path / "out"
    source_root.mkdir()
    (source_root / "sample.py").write_text(
        "def demo() -> int:\n    return 1\n",
        encoding="utf-8",
    )

    with override_storage_root(source_root, output_root):
        first_report = index_repo(source_root, full=True)
        second_report = index_repo(source_root, full=True)

    assert first_report.failed == 0
    assert second_report.failed == 0
    assert second_report.indexed == 1


def test_duckdb_full_index_uses_bulk_profile_path(tmp_path: Path) -> None:
    """
    Route configured DuckDB full indexing through the bulk persistence path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The emitted profile contains full-index bulk spans and omits the legacy
        per-file persistence span.
    """
    pytest.importorskip("duckdb")
    source_root = tmp_path / "repo"
    output_root = tmp_path / "out"
    source_root.mkdir()
    config_path = source_root / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            (
                "[backend]",
                'name = "duckdb"',
                "",
                "[embeddings]",
                "enabled = false",
                "",
                "[plugins.backend-duckdb]",
                "profiling_enabled = true",
                "",
            )
        ),
        encoding="utf-8",
    )
    (source_root / "sample.py").write_text(
        "def demo() -> int:\n    return 1\n",
        encoding="utf-8",
    )

    with override_storage_root(source_root, output_root):
        report = index_repo(source_root, full=True)

    profile_path = output_root / ".codira" / "duckdb-profile.json"
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    span_names = {str(span["name"]) for span in payload["spans"]}

    assert report.failed == 0
    assert report.indexed == 1
    assert "bulk_full_index.plan_rows" in span_names
    assert "bulk_full_index.load_structural_tables" in span_names
    assert "persist.store_analysis" not in span_names


def test_duckdb_bulk_full_index_schema_failure_rolls_back_before_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Roll back a DuckDB full rebuild when schema-index creation fails.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to make DuckDB schema-index creation fail.
    tmp_path : pathlib.Path
        Temporary workspace containing a source root and isolated output root.

    Returns
    -------
    None
        A failed full rebuild retains the previously published rows and complete
        schema-index set; a later ordinary index can then publish the change.
    """
    duckdb = pytest.importorskip("duckdb")
    source_root = tmp_path / "repo"
    output_root = tmp_path / "out"
    source_root.mkdir()
    config_path = source_root / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            (
                "[backend]",
                'name = "duckdb"',
                "",
                "[embeddings]",
                "enabled = false",
                "",
            )
        ),
        encoding="utf-8",
    )
    source_path = source_root / "sample.py"
    source_path.write_text(
        "def first() -> int:\n    return 1\n",
        encoding="utf-8",
    )

    with override_storage_root(source_root, output_root):
        initial_report = index_repo(source_root, full=True)
        database_path = _duckdb_db_path(source_root)
        initial_connection = duckdb.connect(str(database_path))
        try:
            initial_indexes = initial_connection.execute(
                "SELECT index_name FROM duckdb_indexes() ORDER BY index_name"
            ).fetchall()
            initial_functions = initial_connection.execute(
                "SELECT name FROM functions ORDER BY name"
            ).fetchall()
        finally:
            initial_connection.close()

        source_path.write_text(
            "def second() -> int:\n    return 2\n",
            encoding="utf-8",
        )
        error_message = "injected schema-index creation failure"

        def fail_schema_index_creation(_connection: object) -> None:
            """Raise the controlled late full-index failure."""
            raise RuntimeError(error_message)

        monkeypatch.setattr(
            duckdb_backend_module,
            "_create_duckdb_schema_indexes",
            fail_schema_index_creation,
        )
        failed_report = index_repo(source_root, full=True)

        failed_connection = duckdb.connect(str(database_path))
        try:
            failed_indexes = failed_connection.execute(
                "SELECT index_name FROM duckdb_indexes() ORDER BY index_name"
            ).fetchall()
            failed_functions = failed_connection.execute(
                "SELECT name FROM functions ORDER BY name"
            ).fetchall()
        finally:
            failed_connection.close()

        monkeypatch.undo()
        recovery_report = index_repo(source_root)
        recovered_connection = duckdb.connect(str(database_path))
        try:
            recovered_indexes = recovered_connection.execute(
                "SELECT index_name FROM duckdb_indexes() ORDER BY index_name"
            ).fetchall()
            recovered_functions = recovered_connection.execute(
                "SELECT name FROM functions ORDER BY name"
            ).fetchall()
        finally:
            recovered_connection.close()

    assert initial_report.failed == 0
    assert initial_indexes
    assert initial_functions == [("first",)]
    assert failed_report.failed == 1
    assert failed_report.failures[0].reason == error_message
    assert failed_indexes == initial_indexes
    assert failed_functions == initial_functions
    assert recovery_report.failed == 0
    assert recovery_report.indexed == 1
    assert recovered_indexes == initial_indexes
    assert recovered_functions == [("second",)]


def test_duckdb_full_index_reuses_cached_embeddings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Reuse cached vectors during DuckDB full-index embedding flushes.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace embedding generation with a counting fake.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The second full index must reuse the embedding vector cache instead of
        invoking the embedder again.
    """
    pytest.importorskip("duckdb")
    source_root = tmp_path / "repo"
    output_root = tmp_path / "out"
    source_root.mkdir()
    config_path = source_root / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            (
                "[backend]",
                'name = "duckdb"',
                "",
                "[embeddings]",
                "enabled = true",
                "",
            )
        ),
        encoding="utf-8",
    )
    (source_root / "sample.py").write_text(
        "def demo() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    embed_calls: list[list[str]] = []

    def fake_embed_texts(
        texts: list[str],
        root: Path | None = None,
    ) -> list[list[float]]:
        """
        Count embedding calls and return deterministic vectors.

        Parameters
        ----------
        texts : list[str]
            Text payloads requested by the embedding flush.
        root : pathlib.Path | None, optional
            Repository root supplied by the caller.

        Returns
        -------
        list[list[float]]
            One deterministic 384-dimensional vector per text.
        """
        del root
        embed_calls.append(list(texts))
        return [[1.0] * 384 for _text in texts]

    monkeypatch.setattr(duckdb_support_module, "embed_texts", fake_embed_texts)

    with override_storage_root(source_root, output_root):
        first_report = index_repo(source_root, full=True)
        first_call_count = len(embed_calls)
        second_report = index_repo(source_root, full=True)

    assert first_report.failed == 0
    assert second_report.failed == 0
    assert first_call_count > 0
    assert len(embed_calls) == first_call_count
    assert second_report.embeddings_reused > 0
    assert second_report.embeddings_recomputed == 0


def test_duckdb_full_index_vector_failure_is_not_published_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Keep a failed post-commit DuckDB full index unavailable to readers.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to make the bulk vector-store write fail after DuckDB
        commits structural rows.
    tmp_path : pathlib.Path
        Temporary workspace containing isolated source and output roots.

    Returns
    -------
    None
        The test asserts the durable generation is failed rather than ready
        while retaining the preceding successful generation identifier.
    """
    duckdb = pytest.importorskip("duckdb")
    source_root = tmp_path / "repo"
    output_root = tmp_path / "out"
    source_root.mkdir()
    config_path = source_root / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            (
                "[backend]",
                'name = "duckdb"',
                "",
                "[embeddings]",
                "enabled = true",
                'vector_store = "sqlite"',
                "",
            )
        ),
        encoding="utf-8",
    )
    (source_root / "sample.py").write_text(
        "def demo() -> int:\n    return 1\n",
        encoding="utf-8",
    )

    def fake_embed_texts(
        texts: list[str],
        root: Path | None = None,
    ) -> list[list[float]]:
        """
        Return deterministic vectors without loading an embedding model.

        Parameters
        ----------
        texts : list[str]
            Text payloads requested by the embedding flush.
        root : pathlib.Path | None, optional
            Repository root supplied by the embedding helper.

        Returns
        -------
        list[list[float]]
            One fixed-size vector per input text.
        """
        del root
        return [[1.0] * 384 for _text in texts]

    monkeypatch.setattr(duckdb_support_module, "embed_texts", fake_embed_texts)

    with override_storage_root(source_root, output_root):
        first_report = index_repo(source_root, full=True)
        first_generation = IndexGenerationStore(source_root).read()
        assert first_report.failed == 0
        assert first_generation is not None
        assert first_generation.state == "ready"

        structural_file_counts: list[int] = []

        def raise_after_structural_commit(
            self: SQLiteVectorStore,
            request: object,
        ) -> None:
            """
            Prove DuckDB committed structural rows before failing vector writes.

            Parameters
            ----------
            self : codira_vector_store_sqlite.SQLiteVectorStore
                Active vector-store instance receiving the bulk write.
            request : object
                Bulk vector-store request that is intentionally rejected.

            Returns
            -------
            None

            Raises
            ------
            RuntimeError
                Always, after observing the committed DuckDB files table.
            """
            del self, request
            raw = duckdb.connect(str(_duckdb_db_path(source_root)))
            try:
                row = raw.execute("SELECT COUNT(*) FROM files").fetchone()
            finally:
                raw.close()
            assert row is not None
            structural_file_counts.append(int(row[0]))
            msg = "injected vector-store failure"
            raise RuntimeError(msg)

        monkeypatch.setattr(
            SQLiteVectorStore,
            "store_vectors_for_full_index",
            raise_after_structural_commit,
        )
        failed_report = index_repo(source_root, full=True)
        failed_generation = IndexGenerationStore(source_root).read()

    assert structural_file_counts == [1]
    assert failed_report.failed == 1
    assert failed_report.publication_ready is False
    assert failed_generation is not None
    assert failed_generation.state == "failed"
    assert failed_generation.generation == first_generation.generation + 1
    assert failed_generation.last_successful_generation == first_generation.generation


def test_duckdb_cache_resolution_handles_large_sqlite_vector_store_lookups(
    tmp_path: Path,
) -> None:
    """
    Reuse a large cache set through the SQLite vector-store boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts DuckDB cache resolution does not exceed SQLite's bind
        limit.
    """
    vector_store = SQLiteVectorStore()
    backend = EmbeddingBackendSpec(name="test-backend", version="1", dim=384)
    identity = VectorSetIdentity(
        engine=EmbeddingEngineSpec(
            engine=backend.name,
            engine_version=backend.version,
            model="test-model",
            model_version="1",
            dimension=backend.dim,
        ),
        vector_store=vector_store.spec({}),
    )
    prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]] = [
        (
            PendingEmbeddingRow(
                object_type="symbol",
                object_id=index,
                stable_id=f"symbol:{index}",
                text=f"text {index}",
            ),
            f"hash-{index}",
            None,
        )
        for index in range(1_001)
    ]
    cached_vectors = {
        content_hash: serialize_vector([float(index)] * backend.dim)
        for index, (_row, content_hash, _vector) in enumerate(prepared_rows)
    }
    vector_store.store_cached_vectors(tmp_path, identity, cached_vectors, {})

    resolved_rows, recomputed, reused = _resolve_cached_prepared_embedding_rows(
        prepared_rows=prepared_rows,
        root=tmp_path,
        vector_store=vector_store,
        vector_set_identity=identity,
        vector_store_config={},
    )

    assert recomputed == 0
    assert reused == len(prepared_rows)
    assert [vector for _row, _hash, vector in resolved_rows] == [
        cached_vectors[f"hash-{index}"] for index in range(1_001)
    ]


def test_duckdb_deferred_session_flushes_pending_rows_after_structural_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Flush deferred pending embeddings after the structural full-index commit.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to wrap the pending-row flush helper.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts pending rows are flushed only after structural rows
        are visible from a separate DuckDB connection.
    """
    duckdb = pytest.importorskip("duckdb")
    module_path = tmp_path / "pkg" / "sample.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("", encoding="utf-8")
    observed_file_counts: list[int] = []

    def wrapped_store_pending(
        conn: _DuckDBPersistenceConnection,
        *,
        prepared_rows: list[tuple[PendingEmbeddingRow, str, bytes | None]],
        backend: EmbeddingBackendSpec,
        profiler: DuckDBProfileRecorder | None = None,
    ) -> None:
        raw = duckdb.connect(str(_duckdb_db_path(tmp_path)))
        try:
            row = raw.execute("SELECT COUNT(*) FROM files").fetchone()
        finally:
            raw.close()
        assert row is not None
        observed_file_counts.append(int(row[0]))
        _store_pending_embedding_rows(
            conn,
            prepared_rows=prepared_rows,
            backend=backend,
            profiler=profiler,
        )

    monkeypatch.setattr(
        duckdb_backend_module,
        "_store_pending_embedding_rows",
        wrapped_store_pending,
    )

    backend = DuckDBIndexBackend()
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=(str(module_path),), deleted_paths=())
        session.persist_analysis(
            BackendPersistAnalysisRequest(
                root=tmp_path,
                file_metadata=FileMetadataSnapshot(
                    path=module_path,
                    sha256="duckdb-deferred-session",
                    mtime=1.0,
                    size=0,
                ),
                analysis=AnalysisResult(
                    source_path=module_path,
                    module=ModuleArtifact(
                        name="pkg.sample",
                        stable_id="python:module:pkg.sample",
                        docstring=None,
                        has_docstring=0,
                    ),
                    classes=(),
                    functions=(),
                    declarations=(),
                    imports=(),
                ),
                embedding_backend=EmbeddingBackendSpec(
                    name="test-backend",
                    version="1",
                    dim=384,
                ),
                defer_embeddings=True,
            )
        )
        session.rebuild_derived_indexes()
        session.commit()
    finally:
        session.close()

    raw = duckdb.connect(str(_duckdb_db_path(tmp_path)))
    try:
        pending_count = raw.execute(
            "SELECT COUNT(*) FROM pending_embeddings"
        ).fetchone()
    finally:
        raw.close()

    assert observed_file_counts == [1]
    assert pending_count == (1,)
