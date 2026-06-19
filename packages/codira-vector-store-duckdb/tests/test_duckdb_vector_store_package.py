"""Package-local tests for the first-party DuckDB vector store."""

from __future__ import annotations

import tomllib
from pathlib import Path

import duckdb

from codira.contracts import (
    EmbeddingEngineSpec,
    PendingEmbeddingRow,
    PreparedVectorRow,
    VectorSetIdentity,
    VectorStore,
)
from codira_vector_store_duckdb import (
    DuckDBVectorStore,
    build_vector_store,
    get_vector_store_path,
)


def _vector_identity(store: DuckDBVectorStore) -> VectorSetIdentity:
    """
    Return a deterministic vector-set identity for package tests.

    Parameters
    ----------
    store : codira_vector_store_duckdb.DuckDBVectorStore
        Vector store under test.

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
            model_version="rev1",
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
            vector=b"vector-one",
        ),
        PreparedVectorRow(
            row=PendingEmbeddingRow(
                object_type="documentation",
                object_id=2,
                stable_id="doc:two",
                text="doc text",
            ),
            content_hash="hash-two",
            vector=b"vector-two",
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

    assert project["project"]["version"] == "1.0.0"
    assert project["project"]["entry-points"]["codira.vector_stores"] == {
        "duckdb": "codira_vector_store_duckdb:build_vector_store"
    }


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
        {"hash-one": b"cached-one", "hash-two": b"cached-two"},
        {},
    )
    assert store.load_cached_vectors(
        tmp_path,
        identity,
        ["hash-two", "hash-one", "hash-one"],
        {},
    ) == {"hash-one": b"cached-one", "hash-two": b"cached-two"}

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
        ("documentation", "doc:two", "hash-two", b"vector-two"),
        ("symbol", "symbol:one", "hash-one", b"vector-one"),
    ]
