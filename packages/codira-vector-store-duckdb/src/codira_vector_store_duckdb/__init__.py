"""DuckDB vector-store plugin for codira."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import duckdb

from codira.contracts import VectorStoreSpec

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from codira.contracts import VectorStore

__all__ = [
    "PACKAGE_VERSION",
    "DuckDBVectorStore",
    "build_vector_store",
    "get_vector_store_path",
]

PACKAGE_VERSION = "1.0.0"
FORMAT_VERSION = "1"


def get_vector_store_path(root: Path) -> Path:
    """
    Return the DuckDB vector-store path for one repository root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to `.codira/embeddings.duckdb`.
    """
    return root / ".codira" / "embeddings.duckdb"


class DuckDBVectorStore:
    """
    DuckDB-backed vector store.

    Parameters
    ----------
    None
    """

    name = "duckdb"
    version = PACKAGE_VERSION

    def spec(self, config: Mapping[str, object]) -> VectorStoreSpec:
        """
        Return the DuckDB vector-store identity.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        codira.contracts.VectorStoreSpec
            DuckDB vector-store identity.
        """
        del config
        return VectorStoreSpec(
            store=self.name,
            store_version=self.version,
            format_version=FORMAT_VERSION,
        )

    def initialize(self, root: Path, config: Mapping[str, object]) -> None:
        """
        Initialize the separated DuckDB vector-store schema.

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
        conn = duckdb.connect(str(path))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vector_sets (
                    id UBIGINT PRIMARY KEY,
                    engine TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    model TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    precision TEXT NOT NULL,
                    store TEXT NOT NULL,
                    store_version TEXT NOT NULL,
                    format_version TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
                )
                """
            )
            conn.execute(
                """
                CREATE SEQUENCE IF NOT EXISTS vector_sets_id_seq START 1
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    vector_set_id UBIGINT NOT NULL,
                    object_type TEXT NOT NULL,
                    stable_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    vector_values DOUBLE[],
                    PRIMARY KEY (vector_set_id, object_type, stable_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vector_cache (
                    vector_set_id UBIGINT NOT NULL,
                    content_hash TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    vector_values DOUBLE[],
                    PRIMARY KEY (vector_set_id, content_hash)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_vectors (
                    vector_set_id UBIGINT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id BIGINT NOT NULL,
                    stable_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    PRIMARY KEY (vector_set_id, object_type, stable_id)
                )
                """
            )
        finally:
            conn.close()

    def reset_runtime_caches(self) -> None:
        """
        Clear process-local vector-store caches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The DuckDB vector store has no process-local cache yet.
        """


def build_vector_store() -> VectorStore:
    """
    Build the DuckDB vector-store plugin.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.VectorStore
        DuckDB vector-store instance.
    """
    return cast("VectorStore", DuckDBVectorStore())
