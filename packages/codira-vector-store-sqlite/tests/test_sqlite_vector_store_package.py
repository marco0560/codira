"""Package-local tests for the first-party SQLite vector store."""

from __future__ import annotations

import sqlite3
import tomllib
from pathlib import Path

from codira.contracts import VectorStore
from codira_vector_store_sqlite import (
    SQLiteVectorStore,
    build_vector_store,
    get_vector_store_path,
)


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

    assert project["project"]["version"] == "1.0.0"
    assert project["project"]["entry-points"]["codira.vector_stores"] == {
        "sqlite": "codira_vector_store_sqlite:build_vector_store"
    }


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
