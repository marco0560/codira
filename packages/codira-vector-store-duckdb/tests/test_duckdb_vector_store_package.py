"""Package-local tests for the first-party DuckDB vector store."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

import duckdb
import pytest

from codira.contracts import (
    EmbeddingEngineSpec,
    PendingEmbeddingRow,
    PreparedVectorIdentityRow,
    PreparedVectorRow,
    VectorSimilarityRequest,
    VectorSetIdentity,
    VectorStore,
    VectorStoreFullIndexRequest,
    VectorStorePurgeRequest,
)
from codira.semantic.embeddings import (
    deserialize_vector as deserialize_embedding_vector,
    serialize_vector,
)
from codira_vector_store_duckdb import (
    DuckDBVectorStore,
    build_vector_store,
    get_vector_store_path,
)
import codira_vector_store_duckdb as duckdb_vector_store_module


def _vector_identity(
    store: DuckDBVectorStore,
    *,
    model_version: str = "rev1",
) -> VectorSetIdentity:
    """
    Return a deterministic vector-set identity for package tests.

    Parameters
    ----------
    store : codira_vector_store_duckdb.DuckDBVectorStore
        Vector store under test.
    model_version : str, optional
        Model revision used to distinguish vector sets.

    Returns
    -------
    codira.contracts.VectorSetIdentity
        Complete vector-set identity.
    """
    return VectorSetIdentity(
        engine=EmbeddingEngineSpec(
            engine="test-engine",
            engine_version="1",
            model="test-model",
            model_version=model_version,
            dimension=3,
        ),
        vector_store=store.spec({}),
    )


def _prepared_rows() -> list[PreparedVectorRow]:
    """
    Return deterministic prepared vector rows for package tests.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.contracts.PreparedVectorRow]
        Prepared rows carrying pending and materialized vectors.
    """
    return [
        PreparedVectorRow(
            row=PendingEmbeddingRow(
                object_type="symbol",
                object_id=1,
                stable_id="symbol:one",
                text="symbol text",
            ),
            content_hash="hash-one",
            vector=serialize_vector([1.0, 0.0, 0.0]),
        ),
        PreparedVectorRow(
            row=PendingEmbeddingRow(
                object_type="documentation",
                object_id=2,
                stable_id="doc:two",
                text="doc text",
            ),
            content_hash="hash-two",
            vector=serialize_vector([0.0, 1.0, 0.0]),
        ),
    ]


def test_duckdb_vector_store_package_declares_expected_entry_point() -> None:
    """
    Keep package metadata aligned to the vector-store entry-point contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the package advertises the expected factory.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "1.0.8"
    assert project["project"]["entry-points"]["codira.vector_stores"] == {
        "duckdb": "codira_vector_store_duckdb:build_vector_store"
    }


def test_duckdb_vector_store_exposes_configuration_schema() -> None:
    """
    Expose a strict first-party vector-store configuration schema.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts DuckDB currently accepts only common plugin options.
    """
    schema = DuckDBVectorStore().configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)

    assert schema["additionalProperties"] is False
    assert sorted(properties) == ["enabled"]


def test_duckdb_vector_store_disables_python_replacements(tmp_path: Path) -> None:
    """
    Disable DuckDB Python replacement scans on vector-store connections.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts vector-store-owned connections do not scan Python
        frames for replacement values.
    """
    path = tmp_path / ".codira" / "embeddings.duckdb"
    path.parent.mkdir(parents=True)

    conn = duckdb_vector_store_module._connect(path)
    try:
        row = conn.execute(
            """
            SELECT value
            FROM duckdb_settings()
            WHERE name = 'python_enable_replacements'
            """
        ).fetchone()
    finally:
        conn.close()

    assert row == ("false",)


def test_duckdb_vector_store_initializes_separated_database(tmp_path: Path) -> None:
    """
    Initialize `.codira/embeddings.duckdb` with separated vector-store tables.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts expected vector-store tables exist.
    """
    store = build_vector_store()

    assert isinstance(store, DuckDBVectorStore)
    assert isinstance(store, VectorStore)
    store.initialize(tmp_path, {})

    db_path = get_vector_store_path(tmp_path)
    assert db_path == tmp_path / ".codira" / "embeddings.duckdb"
    with duckdb.connect(str(db_path), read_only=True) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
    assert {"vector_sets", "vectors", "vector_cache", "pending_vectors"} <= tables


def test_duckdb_vector_store_persists_vector_rows(tmp_path: Path) -> None:
    """
    Persist vector-set, cache, pending, and materialized vector rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts separated vector-store row operations round-trip.
    """
    store = DuckDBVectorStore()
    identity = _vector_identity(store)
    rows = _prepared_rows()

    vector_set_id = store.ensure_vector_set(tmp_path, identity, {})

    assert vector_set_id == store.ensure_vector_set(tmp_path, identity, {})

    store.store_cached_vectors(
        tmp_path,
        identity,
        {
            "hash-one": serialize_vector([1.0, 0.0, 0.0]),
            "hash-two": serialize_vector([0.0, 1.0, 0.0]),
        },
        {},
    )
    assert store.load_cached_vectors(
        tmp_path,
        identity,
        ["hash-two", "hash-one", "hash-one"],
        {},
    ) == {
        "hash-one": serialize_vector([1.0, 0.0, 0.0]),
        "hash-two": serialize_vector([0.0, 1.0, 0.0]),
    }

    store.store_pending_vectors(tmp_path, identity, rows, {})
    store.store_vectors(tmp_path, identity, rows, {})
    store.delete_pending_vectors(tmp_path, identity, rows[:1], {})

    with duckdb.connect(str(get_vector_store_path(tmp_path)), read_only=True) as conn:
        pending_rows = conn.execute(
            """
            SELECT object_type, object_id, stable_id, content_hash, text
            FROM pending_vectors
            ORDER BY object_type, object_id
            """
        ).fetchall()
        vector_rows = conn.execute(
            """
            SELECT object_type, stable_id, content_hash, vector
            FROM vectors
            ORDER BY object_type, stable_id
            """
        ).fetchall()

    assert pending_rows == [("documentation", 2, "doc:two", "hash-two", "doc text")]
    assert vector_rows == [
        ("documentation", "doc:two", "hash-two", serialize_vector([0.0, 1.0, 0.0])),
        ("symbol", "symbol:one", "hash-one", serialize_vector([1.0, 0.0, 0.0])),
    ]

    store.clear_pending_vectors(tmp_path, identity, {})
    with duckdb.connect(str(get_vector_store_path(tmp_path)), read_only=True) as conn:
        pending_after_clear = conn.execute(
            "SELECT COUNT(*) FROM pending_vectors"
        ).fetchone()
    assert pending_after_clear == (0,)


def test_duckdb_vector_store_bulk_full_index_writer_persists_rows(
    tmp_path: Path,
) -> None:
    """
    Persist materialized rows through the full-index bulk writer contract.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The optional bulk writer stores rows in the separated DuckDB vector
        store.
    """
    store = DuckDBVectorStore()
    identity = _vector_identity(store)
    stale_rows = [
        PreparedVectorRow(
            row=PendingEmbeddingRow(
                object_type="symbol",
                object_id=9,
                stable_id="symbol:stale",
                text="stale text",
            ),
            content_hash="hash-stale",
            vector=serialize_vector([0.0, 0.0, 1.0]),
        )
    ]

    store.store_vectors(tmp_path, identity, stale_rows, {})
    store.store_pending_vectors(tmp_path, identity, stale_rows, {})

    store.store_vectors_for_full_index(
        VectorStoreFullIndexRequest(
            root=tmp_path,
            identity=identity,
            rows=_prepared_rows(),
            cached_vectors={"hash-cache": serialize_vector([0.25, 0.5, 0.75])},
            config={},
            backend_connection=object(),
        )
    )

    with duckdb.connect(str(get_vector_store_path(tmp_path)), read_only=True) as conn:
        vector_rows = conn.execute(
            """
            SELECT object_type, stable_id, content_hash, vector
            FROM vectors
            ORDER BY object_type, stable_id
            """
        ).fetchall()
        pending_count = conn.execute("SELECT COUNT(*) FROM pending_vectors").fetchone()
        cache_rows = conn.execute(
            """
            SELECT content_hash, vector
            FROM vector_cache
            ORDER BY content_hash
            """
        ).fetchall()

    assert vector_rows == [
        ("documentation", "doc:two", "hash-two", serialize_vector([0.0, 1.0, 0.0])),
        ("symbol", "symbol:one", "hash-one", serialize_vector([1.0, 0.0, 0.0])),
    ]
    assert pending_count == (0,)
    assert cache_rows == [("hash-cache", serialize_vector([0.25, 0.5, 0.75]))]


def test_duckdb_vector_store_full_index_preserves_unchanged_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Preserve unchanged materialized rows during DuckDB full-index writes.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to count vector deserialization calls.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The unchanged row keeps its existing vector payload while changed and
        new rows are materialized from the request.
    """
    store = DuckDBVectorStore()
    identity = _vector_identity(store)
    preserved_blob = serialize_vector([0.1, 0.2, 0.3])
    changed_blob = serialize_vector([0.0, 1.0, 0.0])
    new_blob = serialize_vector([1.0, 0.0, 0.0])
    stale_rows = [
        PreparedVectorRow(
            row=PendingEmbeddingRow(
                object_type="symbol",
                object_id=1,
                stable_id="symbol:one",
                text="old text",
            ),
            content_hash="hash-one",
            vector=preserved_blob,
        ),
        PreparedVectorRow(
            row=PendingEmbeddingRow(
                object_type="symbol",
                object_id=9,
                stable_id="symbol:stale",
                text="stale text",
            ),
            content_hash="hash-stale",
            vector=serialize_vector([0.0, 0.0, 1.0]),
        ),
    ]
    store.store_vectors(tmp_path, identity, stale_rows, {})
    deserialize_calls = 0

    def counted_deserialize(vector: bytes, *, dim: int) -> list[float]:
        """
        Count deserialization calls before delegating.

        Parameters
        ----------
        vector : bytes
            Serialized vector payload.
        dim : int
            Expected vector dimensionality.

        Returns
        -------
        list[float]
            Deserialized vector values.
        """
        nonlocal deserialize_calls
        deserialize_calls += 1
        return deserialize_embedding_vector(vector, dim=dim)

    monkeypatch.setattr(
        duckdb_vector_store_module,
        "deserialize_vector",
        counted_deserialize,
    )

    store.store_vectors_for_full_index(
        VectorStoreFullIndexRequest(
            root=tmp_path,
            identity=identity,
            rows=[
                PreparedVectorRow(
                    row=PendingEmbeddingRow(
                        object_type="symbol",
                        object_id=1,
                        stable_id="symbol:one",
                        text="new text",
                    ),
                    content_hash="hash-one",
                    vector=serialize_vector([9.0, 9.0, 9.0]),
                ),
                PreparedVectorRow(
                    row=PendingEmbeddingRow(
                        object_type="documentation",
                        object_id=2,
                        stable_id="doc:two",
                        text="doc text",
                    ),
                    content_hash="hash-two",
                    vector=changed_blob,
                ),
                PreparedVectorRow(
                    row=PendingEmbeddingRow(
                        object_type="symbol",
                        object_id=3,
                        stable_id="symbol:three",
                        text="new text",
                    ),
                    content_hash="hash-three",
                    vector=new_blob,
                ),
            ],
            identity_rows=[
                PreparedVectorIdentityRow(
                    object_type="symbol",
                    stable_id="symbol:one",
                    content_hash="hash-one",
                ),
                PreparedVectorIdentityRow(
                    object_type="documentation",
                    stable_id="doc:two",
                    content_hash="hash-two",
                    vector=changed_blob,
                ),
                PreparedVectorIdentityRow(
                    object_type="symbol",
                    stable_id="symbol:three",
                    content_hash="hash-three",
                    vector=new_blob,
                ),
            ],
            cached_vectors={},
            config={},
            preserve_existing=True,
        )
    )

    with duckdb.connect(str(get_vector_store_path(tmp_path)), read_only=True) as conn:
        vector_rows = conn.execute(
            """
            SELECT object_type, stable_id, content_hash, vector
            FROM vectors
            ORDER BY object_type, stable_id
            """
        ).fetchall()

    assert vector_rows == [
        ("documentation", "doc:two", "hash-two", changed_blob),
        ("symbol", "symbol:one", "hash-one", preserved_blob),
        ("symbol", "symbol:three", "hash-three", new_blob),
    ]
    assert deserialize_calls == 2


def test_duckdb_vector_store_caches_vector_set_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Cache vector-set identity lookups inside one vector-store instance.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to count schema initialization calls.

    Returns
    -------
    None
        The test asserts repeated lookups reuse the process-local cache until
        runtime caches are reset.
    """
    store = DuckDBVectorStore()
    identity = _vector_identity(store)
    initialize_calls = 0
    original_initialize = store.initialize

    def counted_initialize(root: Path, config: Mapping[str, object]) -> None:
        """
        Count vector-store initialization calls before delegating.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        config : collections.abc.Mapping[str, object]
            Vector-store configuration mapping.

        Returns
        -------
        None
            Initialization is delegated to the original method.
        """
        nonlocal initialize_calls
        initialize_calls += 1
        original_initialize(root, config)

    monkeypatch.setattr(store, "initialize", counted_initialize)

    first = store.ensure_vector_set(tmp_path, identity, {})
    second = store.ensure_vector_set(tmp_path, identity, {})
    store.reset_runtime_caches()
    third = store.ensure_vector_set(tmp_path, identity, {})

    assert first == second == third
    assert initialize_calls == 2


def test_duckdb_vector_store_scores_native_and_legacy_vectors(
    tmp_path: Path,
) -> None:
    """
    Score native vector-value rows and legacy blob-only rows together.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts DuckDB returns deterministic similarity scores for
        both current and legacy vector encodings.
    """
    store = DuckDBVectorStore()
    identity = _vector_identity(store)
    vector_set_id = store.ensure_vector_set(tmp_path, identity, {})
    store.store_vectors(tmp_path, identity, _prepared_rows(), {})

    with duckdb.connect(str(get_vector_store_path(tmp_path))) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO vectors(
                vector_set_id,
                object_type,
                stable_id,
                content_hash,
                vector,
                vector_values
            )
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (
                vector_set_id,
                "symbol",
                "symbol:legacy",
                "hash-legacy",
                serialize_vector([0.5, 0.5, 0.0]),
            ),
        )

    scores = store.similarity_scores(
        VectorSimilarityRequest(
            root=tmp_path,
            identity=identity,
            object_type="symbol",
            query_vector=[1.0, 0.0, 0.0],
            min_score=0.4,
            config={},
        )
    )

    assert [score.stable_id for score in scores] == ["symbol:one", "symbol:legacy"]
    assert [score.score for score in scores] == pytest.approx([1.0, 0.5])


def test_duckdb_vector_store_purges_stale_sets_with_retention(
    tmp_path: Path,
) -> None:
    """
    Purge stale DuckDB vector sets while preserving active and kept sets.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts dry-run counts, retention, and confirmed deletion.
    """

    store = DuckDBVectorStore()
    active = _vector_identity(store, model_version="active")
    stale_old = _vector_identity(store, model_version="stale-old")
    stale_new = _vector_identity(store, model_version="stale-new")
    rows = _prepared_rows()
    for identity in (active, stale_old, stale_new):
        store.store_cached_vectors(
            tmp_path,
            identity,
            {"hash-one": serialize_vector([0.25, 0.5, 0.75])},
            {},
        )
        store.store_pending_vectors(tmp_path, identity, rows, {})
        store.store_vectors(tmp_path, identity, rows, {})
    with duckdb.connect(str(get_vector_store_path(tmp_path))) as conn:
        conn.execute(
            "UPDATE vector_sets SET created_at = ? WHERE model_version = ?",
            ("2026-01-01 00:00:00", "stale-old"),
        )
        conn.execute(
            "UPDATE vector_sets SET created_at = ? WHERE model_version = ?",
            ("2026-06-01 00:00:00", "stale-new"),
        )

    dry_run = store.purge_vector_sets(
        VectorStorePurgeRequest(
            root=tmp_path,
            identity=active,
            config={},
            stale=True,
            all_sets=False,
            dry_run=True,
            older_than_days=30,
            keep=0,
        )
    )
    assert dry_run.deleted_vector_sets == 1
    assert dry_run.deleted_vectors == 2
    assert dry_run.deleted_cached_vectors == 1
    assert dry_run.deleted_pending_vectors == 2

    result = store.purge_vector_sets(
        VectorStorePurgeRequest(
            root=tmp_path,
            identity=active,
            config={},
            stale=True,
            all_sets=False,
            dry_run=False,
            older_than_days=None,
            keep=1,
        )
    )

    assert result.deleted_vector_sets == 1
    assert result.kept_stale_vector_sets == 1
    assert result.size_before_bytes is not None
    assert result.size_after_bytes is not None
    assert result.note == (
        "DuckDB may reuse freed blocks before the file shrinks; "
        "CHECKPOINT was run after the purge."
    )
    with duckdb.connect(str(get_vector_store_path(tmp_path))) as conn:
        remaining = conn.execute(
            """
            SELECT model_version
            FROM vector_sets
            ORDER BY model_version
            """
        ).fetchall()
    assert remaining == [("active",), ("stale-new",)]
