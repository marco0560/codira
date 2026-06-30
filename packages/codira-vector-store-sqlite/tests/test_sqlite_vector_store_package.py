"""Package-local tests for the first-party SQLite vector store."""

from __future__ import annotations

import sqlite3
import tomllib
from pathlib import Path

from codira.contracts import (
    EmbeddingEngineSpec,
    PendingEmbeddingRow,
    PreparedVectorRow,
    VectorSetIdentity,
    VectorStore,
    VectorStorePurgeRequest,
)
from codira_vector_store_sqlite import (
    SQLiteVectorStore,
    build_vector_store,
    get_vector_store_path,
)


def _vector_identity(
    store: SQLiteVectorStore,
    *,
    model_version: str = "rev1",
) -> VectorSetIdentity:
    """
    Return a deterministic vector-set identity for package tests.

    Parameters
    ----------
    store : codira_vector_store_sqlite.SQLiteVectorStore
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


def test_sqlite_vector_store_package_declares_expected_entry_point() -> None:
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

    assert project["project"]["version"] == "1.0.2"
    assert project["project"]["entry-points"]["codira.vector_stores"] == {
        "sqlite": "codira_vector_store_sqlite:build_vector_store"
    }


def test_sqlite_vector_store_exposes_configuration_schema() -> None:
    """
    Expose a strict first-party vector-store configuration schema.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts SQLite currently accepts only common plugin options.
    """
    schema = SQLiteVectorStore().configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)

    assert schema["additionalProperties"] is False
    assert sorted(properties) == ["enabled"]


def test_sqlite_vector_store_initializes_separated_database(tmp_path: Path) -> None:
    """
    Initialize `.codira/embeddings.db` with separated vector-store tables.

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

    assert isinstance(store, SQLiteVectorStore)
    assert isinstance(store, VectorStore)
    store.initialize(tmp_path, {})

    db_path = get_vector_store_path(tmp_path)
    assert db_path == tmp_path / ".codira" / "embeddings.db"
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"vector_sets", "vectors", "vector_cache", "pending_vectors"} <= tables


def test_sqlite_vector_store_persists_vector_rows(tmp_path: Path) -> None:
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
    store = SQLiteVectorStore()
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

    with sqlite3.connect(get_vector_store_path(tmp_path)) as conn:
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

    store.clear_pending_vectors(tmp_path, identity, {})
    with sqlite3.connect(get_vector_store_path(tmp_path)) as conn:
        pending_after_clear = conn.execute(
            "SELECT COUNT(*) FROM pending_vectors"
        ).fetchone()
    assert pending_after_clear == (0,)


def test_sqlite_vector_store_purges_stale_sets_with_retention(
    tmp_path: Path,
) -> None:
    """
    Purge stale SQLite vector sets while preserving active and kept sets.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts dry-run counts and confirmed deletion behavior.
    """

    store = SQLiteVectorStore()
    active = _vector_identity(store, model_version="active")
    stale_old = _vector_identity(store, model_version="stale-old")
    stale_new = _vector_identity(store, model_version="stale-new")
    rows = _prepared_rows()
    for identity in (active, stale_old, stale_new):
        store.store_cached_vectors(tmp_path, identity, {"hash-one": b"cached"}, {})
        store.store_pending_vectors(tmp_path, identity, rows, {})
        store.store_vectors(tmp_path, identity, rows, {})
    with sqlite3.connect(get_vector_store_path(tmp_path)) as conn:
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
    assert result.note is not None
    with sqlite3.connect(get_vector_store_path(tmp_path)) as conn:
        remaining = conn.execute(
            """
            SELECT model_version
            FROM vector_sets
            ORDER BY model_version
            """
        ).fetchall()
    assert remaining == [("active",), ("stale-new",)]
