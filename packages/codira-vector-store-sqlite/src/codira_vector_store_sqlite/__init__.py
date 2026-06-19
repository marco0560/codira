"""SQLite vector-store plugin for codira.

Responsibilities
----------------
- Publish the `sqlite` vector-store plugin.
- Own the local `.codira/embeddings.db` storage boundary.
- Initialize the first separated vector-store schema.

Architectural role
------------------
This module belongs to the **first-party vector-store plugin layer**.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from codira.contracts import VectorStoreSpec

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from codira.contracts import VectorStore

__all__ = [
    "PACKAGE_VERSION",
    "SQLiteVectorStore",
    "build_vector_store",
    "get_vector_store_path",
]

PACKAGE_VERSION = "1.0.0"
FORMAT_VERSION = "1"


def get_vector_store_path(root: Path) -> Path:
    """
    Return the SQLite vector-store path for one repository root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to `.codira/embeddings.db`.
    """
    return root / ".codira" / "embeddings.db"


class SQLiteVectorStore:
    """
    SQLite-backed vector store.

    Parameters
    ----------
    None
    """

    name = "sqlite"
    version = PACKAGE_VERSION

    def spec(self, config: Mapping[str, object]) -> VectorStoreSpec:
        """
        Return the SQLite vector-store identity.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        codira.contracts.VectorStoreSpec
            SQLite vector-store identity.
        """
        del config
        return VectorStoreSpec(
            store=self.name,
            store_version=self.version,
            format_version=FORMAT_VERSION,
        )

    def initialize(self, root: Path, config: Mapping[str, object]) -> None:
        """
        Initialize the separated SQLite vector-store schema.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            The schema exists after this call.
        """
        del config
        path = get_vector_store_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vector_sets (
                    id INTEGER PRIMARY KEY,
                    engine TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    model TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    precision TEXT NOT NULL,
                    store TEXT NOT NULL,
                    store_version TEXT NOT NULL,
                    format_version TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (
                        engine,
                        engine_version,
                        model,
                        model_version,
                        dimension,
                        precision,
                        store,
                        store_version,
                        format_version
                    )
                );
                CREATE TABLE IF NOT EXISTS vectors (
                    vector_set_id INTEGER NOT NULL,
                    object_type TEXT NOT NULL,
                    stable_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    PRIMARY KEY (vector_set_id, object_type, stable_id),
                    FOREIGN KEY (vector_set_id) REFERENCES vector_sets(id)
                );
                CREATE TABLE IF NOT EXISTS vector_cache (
                    vector_set_id INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    PRIMARY KEY (vector_set_id, content_hash),
                    FOREIGN KEY (vector_set_id) REFERENCES vector_sets(id)
                );
                CREATE TABLE IF NOT EXISTS pending_vectors (
                    vector_set_id INTEGER NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id INTEGER NOT NULL,
                    stable_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    PRIMARY KEY (vector_set_id, object_type, stable_id),
                    FOREIGN KEY (vector_set_id) REFERENCES vector_sets(id)
                );
                """
            )

    def reset_runtime_caches(self) -> None:
        """
        Clear process-local vector-store caches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The SQLite vector store has no process-local cache yet.
        """


def build_vector_store() -> VectorStore:
    """
    Build the SQLite vector-store plugin.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.VectorStore
        SQLite vector-store instance.
    """
    return SQLiteVectorStore()
