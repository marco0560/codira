"""Package-local tests for the first-party DuckDB vector store."""

from __future__ import annotations

import tomllib
from pathlib import Path

import duckdb

from codira.contracts import VectorStore
from codira_vector_store_duckdb import (
    DuckDBVectorStore,
    build_vector_store,
    get_vector_store_path,
)


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
