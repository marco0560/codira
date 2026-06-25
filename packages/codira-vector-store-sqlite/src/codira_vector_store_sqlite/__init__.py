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

from codira.contracts import (
    PreparedVectorRow,
    VectorSetIdentity,
    VectorSimilarityRequest,
    VectorSimilarityScore,
    VectorStoreSpec,
)
from codira.plugin_config import plugin_json_schema
from codira.semantic.embeddings import deserialize_vector
from codira.storage import get_codira_dir

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from codira.contracts import VectorStore

__all__ = [
    "PACKAGE_VERSION",
    "SQLiteVectorStore",
    "build_vector_store",
    "get_vector_store_path",
]

PACKAGE_VERSION = "1.0.1"
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
    return get_codira_dir(root) / "embeddings.db"


class SQLiteVectorStore:
    """
    SQLite-backed vector store.

    Parameters
    ----------
    None
    """

    name = "sqlite"
    version = PACKAGE_VERSION

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the SQLite vector-store plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for vector-store options.
        """
        return plugin_json_schema({})

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

    def ensure_vector_set(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> int:
        """
        Return the SQLite identifier for a vector-set identity.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        int
            Persistent vector-set identifier.
        """
        del config
        self.initialize(root, {})
        values = (
            identity.engine.engine,
            identity.engine.engine_version,
            identity.engine.model,
            identity.engine.model_version,
            identity.engine.dimension,
            identity.engine.precision,
            identity.vector_store.store,
            identity.vector_store.store_version,
            identity.vector_store.format_version,
        )
        with sqlite3.connect(get_vector_store_path(root)) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO vector_sets(
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            row = conn.execute(
                """
                SELECT id
                FROM vector_sets
                WHERE engine = ?
                  AND engine_version = ?
                  AND model = ?
                  AND model_version = ?
                  AND dimension = ?
                  AND precision = ?
                  AND store = ?
                  AND store_version = ?
                  AND format_version = ?
                """,
                values,
            ).fetchone()
        assert row is not None
        return int(row[0])

    def load_cached_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        content_hashes: Sequence[str],
        config: Mapping[str, object],
    ) -> dict[str, bytes]:
        """
        Load cached vectors keyed by content hash.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        content_hashes : collections.abc.Sequence[str]
            Candidate content hashes.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        dict[str, bytes]
            Serialized vectors keyed by content hash.
        """
        ordered_hashes = list(dict.fromkeys(content_hashes))
        if not ordered_hashes:
            return {}
        vector_set_id = self.ensure_vector_set(root, identity, config)
        placeholders = ",".join("?" for _item in ordered_hashes)
        with sqlite3.connect(get_vector_store_path(root)) as conn:
            rows = conn.execute(
                f"""
                SELECT content_hash, vector
                FROM vector_cache
                WHERE vector_set_id = ?
                  AND content_hash IN ({placeholders})
                """,
                (vector_set_id, *ordered_hashes),
            ).fetchall()
        return {str(content_hash): bytes(vector) for content_hash, vector in rows}

    def store_cached_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        vectors: Mapping[str, bytes],
        config: Mapping[str, object],
    ) -> None:
        """
        Store cached vectors keyed by content hash.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        vectors : collections.abc.Mapping[str, bytes]
            Serialized vectors keyed by content hash.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Cache rows are inserted or replaced in place.
        """
        if not vectors:
            return
        vector_set_id = self.ensure_vector_set(root, identity, config)
        with sqlite3.connect(get_vector_store_path(root)) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO vector_cache(
                    vector_set_id, content_hash, vector
                )
                VALUES (?, ?, ?)
                """,
                [
                    (vector_set_id, content_hash, vector)
                    for content_hash, vector in sorted(vectors.items())
                ],
            )

    def store_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: Mapping[str, object],
    ) -> None:
        """
        Store deferred vector rows.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Prepared rows to persist as pending.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Pending rows are inserted or replaced in place.
        """
        if not rows:
            return
        vector_set_id = self.ensure_vector_set(root, identity, config)
        with sqlite3.connect(get_vector_store_path(root)) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO pending_vectors(
                    vector_set_id,
                    object_type,
                    object_id,
                    stable_id,
                    content_hash,
                    text
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        vector_set_id,
                        prepared.row.object_type,
                        prepared.row.object_id,
                        prepared.row.stable_id,
                        prepared.content_hash,
                        prepared.row.text,
                    )
                    for prepared in rows
                ],
            )

    def delete_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: Mapping[str, object],
    ) -> None:
        """
        Delete deferred vector rows.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Prepared rows identifying pending entries.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Matching pending rows are deleted in place.
        """
        if not rows:
            return
        vector_set_id = self.ensure_vector_set(root, identity, config)
        with sqlite3.connect(get_vector_store_path(root)) as conn:
            conn.executemany(
                """
                DELETE FROM pending_vectors
                WHERE vector_set_id = ?
                  AND object_type = ?
                  AND object_id = ?
                """,
                [
                    (
                        vector_set_id,
                        prepared.row.object_type,
                        prepared.row.object_id,
                    )
                    for prepared in rows
                ],
            )

    def clear_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> None:
        """
        Delete all deferred rows for one vector set.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Matching pending rows are deleted in place.
        """
        vector_set_id = self.ensure_vector_set(root, identity, config)
        with sqlite3.connect(get_vector_store_path(root)) as conn:
            conn.execute(
                """
                DELETE FROM pending_vectors
                WHERE vector_set_id = ?
                """,
                (vector_set_id,),
            )

    def store_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: Mapping[str, object],
    ) -> None:
        """
        Store materialized vector rows.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Prepared rows carrying serialized vectors.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Vector rows are inserted or replaced in place.
        """
        materialized = [prepared for prepared in rows if prepared.vector is not None]
        if not materialized:
            return
        vector_set_id = self.ensure_vector_set(root, identity, config)
        with sqlite3.connect(get_vector_store_path(root)) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO vectors(
                    vector_set_id,
                    object_type,
                    stable_id,
                    content_hash,
                    vector
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        vector_set_id,
                        prepared.row.object_type,
                        prepared.row.stable_id,
                        prepared.content_hash,
                        prepared.vector,
                    )
                    for prepared in materialized
                ],
            )

    def similarity_scores(
        self,
        request: VectorSimilarityRequest,
    ) -> list[VectorSimilarityScore]:
        """
        Return SQLite-backed vector similarity scores.

        Parameters
        ----------
        request : codira.contracts.VectorSimilarityRequest
            Vector-store similarity request.

        Returns
        -------
        list[codira.contracts.VectorSimilarityScore]
            Scores ordered by descending score and stable identity.
        """
        vector_set_id = self.ensure_vector_set(
            request.root,
            request.identity,
            request.config,
        )
        with sqlite3.connect(get_vector_store_path(request.root)) as conn:
            rows = conn.execute(
                """
                SELECT stable_id, vector
                FROM vectors
                WHERE vector_set_id = ?
                  AND object_type = ?
                ORDER BY stable_id
                """,
                (vector_set_id, request.object_type),
            ).fetchall()
        scores = [
            VectorSimilarityScore(
                stable_id=str(stable_id),
                score=sum(
                    left * right
                    for left, right in zip(
                        request.query_vector,
                        deserialize_vector(
                            bytes(vector),
                            dim=request.identity.engine.dimension,
                        ),
                        strict=True,
                    )
                ),
            )
            for stable_id, vector in rows
        ]
        return sorted(
            (score for score in scores if score.score >= request.min_score),
            key=lambda item: (-item.score, item.stable_id),
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
