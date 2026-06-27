"""DuckDB vector-store plugin for codira."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import duckdb

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
    "DuckDBVectorStore",
    "build_vector_store",
    "get_vector_store_path",
]

PACKAGE_VERSION = "1.0.2"
FORMAT_VERSION = "1"


def _flush_registered_arrow_table(
    conn: duckdb.DuckDBPyConnection,
    *,
    view_name: str,
    table: object,
    sql: str,
) -> None:
    """
    Execute one DuckDB statement against a registered Arrow table.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        Open DuckDB vector-store connection.
    view_name : str
        Temporary relation name to register.
    table : object
        PyArrow table carrying columnar batch rows.
    sql : str
        DuckDB statement that reads from ``view_name``.

    Returns
    -------
    None
        The statement is executed and the temporary relation is unregistered.
    """
    conn.register(view_name, table)
    try:
        conn.execute(sql)
    finally:
        conn.unregister(view_name)


def _connect(path: Path, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    Open a configured DuckDB vector-store connection.

    Parameters
    ----------
    path : pathlib.Path
        DuckDB database path.
    read_only : bool, optional
        Whether the connection should open the database read-only.

    Returns
    -------
    object
        DuckDB connection with Python replacement scans disabled.
    """
    conn = duckdb.connect(str(path), read_only=read_only)
    conn.execute("SET python_enable_replacements = false")
    return conn


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
    return get_codira_dir(root) / "embeddings.duckdb"


class DuckDBVectorStore:
    """
    DuckDB-backed vector store.

    Parameters
    ----------
    None
    """

    name = "duckdb"
    version = PACKAGE_VERSION

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the DuckDB vector-store plugin configuration schema.

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
        conn = _connect(path)
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

    def ensure_vector_set(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> int:
        """
        Return the DuckDB identifier for a vector-set identity.

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
        conn = _connect(get_vector_store_path(root))
        try:
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
            if row is None:
                conn.execute(
                    """
                    INSERT INTO vector_sets(
                        id,
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
                    VALUES (
                        nextval('vector_sets_id_seq'),
                        ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
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
        finally:
            conn.close()
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
        conn = _connect(get_vector_store_path(root), read_only=True)
        try:
            rows = conn.execute(
                f"""
                SELECT content_hash, vector
                FROM vector_cache
                WHERE vector_set_id = ?
                  AND content_hash IN ({placeholders})
                """,
                (vector_set_id, *ordered_hashes),
            ).fetchall()
        finally:
            conn.close()
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
        import pyarrow as pa

        vector_set_id = self.ensure_vector_set(root, identity, config)
        ordered_vectors = sorted(vectors.items())
        table = pa.table(
            {
                "vector_set_id": pa.array(
                    [vector_set_id for _content_hash, _vector in ordered_vectors],
                    type=pa.uint64(),
                ),
                "content_hash": pa.array(
                    [content_hash for content_hash, _vector in ordered_vectors],
                    type=pa.string(),
                ),
                "vector": pa.array(
                    [vector for _content_hash, vector in ordered_vectors],
                    type=pa.binary(),
                ),
                "vector_values": pa.array(
                    [
                        deserialize_vector(vector, dim=identity.engine.dimension)
                        for _content_hash, vector in ordered_vectors
                    ],
                    type=pa.list_(pa.float64()),
                ),
            }
        )
        conn = _connect(get_vector_store_path(root))
        try:
            _flush_registered_arrow_table(
                conn,
                view_name="__codira_vector_cache_rows",
                table=table,
                sql="""
                INSERT OR REPLACE INTO vector_cache(
                    vector_set_id, content_hash, vector, vector_values
                )
                SELECT vector_set_id, content_hash, vector, vector_values
                FROM __codira_vector_cache_rows
                """,
            )
        finally:
            conn.close()

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
        import pyarrow as pa

        vector_set_id = self.ensure_vector_set(root, identity, config)
        table = pa.table(
            {
                "vector_set_id": pa.array(
                    [vector_set_id for _prepared in rows],
                    type=pa.uint64(),
                ),
                "object_type": pa.array(
                    [prepared.row.object_type for prepared in rows],
                    type=pa.string(),
                ),
                "object_id": pa.array(
                    [prepared.row.object_id for prepared in rows],
                    type=pa.int64(),
                ),
                "stable_id": pa.array(
                    [prepared.row.stable_id for prepared in rows],
                    type=pa.string(),
                ),
                "content_hash": pa.array(
                    [prepared.content_hash for prepared in rows],
                    type=pa.string(),
                ),
                "text": pa.array(
                    [prepared.row.text for prepared in rows],
                    type=pa.string(),
                ),
            }
        )
        conn = _connect(get_vector_store_path(root))
        try:
            _flush_registered_arrow_table(
                conn,
                view_name="__codira_pending_vector_rows",
                table=table,
                sql="""
                INSERT OR REPLACE INTO pending_vectors(
                    vector_set_id,
                    object_type,
                    object_id,
                    stable_id,
                    content_hash,
                    text
                )
                SELECT
                    vector_set_id,
                    object_type,
                    object_id,
                    stable_id,
                    content_hash,
                    text
                FROM __codira_pending_vector_rows
                """,
            )
        finally:
            conn.close()

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
        import pyarrow as pa

        vector_set_id = self.ensure_vector_set(root, identity, config)
        table = pa.table(
            {
                "vector_set_id": pa.array(
                    [vector_set_id for _prepared in rows],
                    type=pa.uint64(),
                ),
                "object_type": pa.array(
                    [prepared.row.object_type for prepared in rows],
                    type=pa.string(),
                ),
                "object_id": pa.array(
                    [prepared.row.object_id for prepared in rows],
                    type=pa.int64(),
                ),
            }
        )
        conn = _connect(get_vector_store_path(root))
        try:
            _flush_registered_arrow_table(
                conn,
                view_name="__codira_pending_vector_delete_rows",
                table=table,
                sql="""
                DELETE FROM pending_vectors
                USING __codira_pending_vector_delete_rows delete_rows
                WHERE pending_vectors.vector_set_id = delete_rows.vector_set_id
                  AND pending_vectors.object_type = delete_rows.object_type
                  AND pending_vectors.object_id = delete_rows.object_id
                """,
            )
        finally:
            conn.close()

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
        conn = _connect(get_vector_store_path(root))
        try:
            conn.execute(
                """
                DELETE FROM pending_vectors
                WHERE vector_set_id = ?
                """,
                (vector_set_id,),
            )
        finally:
            conn.close()

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
        materialized = [
            (prepared, prepared.vector)
            for prepared in rows
            if prepared.vector is not None
        ]
        if not materialized:
            return
        import pyarrow as pa

        vector_set_id = self.ensure_vector_set(root, identity, config)
        table = pa.table(
            {
                "vector_set_id": pa.array(
                    [vector_set_id for _prepared, _vector in materialized],
                    type=pa.uint64(),
                ),
                "object_type": pa.array(
                    [prepared.row.object_type for prepared, _vector in materialized],
                    type=pa.string(),
                ),
                "stable_id": pa.array(
                    [prepared.row.stable_id for prepared, _vector in materialized],
                    type=pa.string(),
                ),
                "content_hash": pa.array(
                    [prepared.content_hash for prepared, _vector in materialized],
                    type=pa.string(),
                ),
                "vector": pa.array(
                    [vector for _prepared, vector in materialized],
                    type=pa.binary(),
                ),
                "vector_values": pa.array(
                    [
                        deserialize_vector(vector, dim=identity.engine.dimension)
                        for _prepared, vector in materialized
                    ],
                    type=pa.list_(pa.float64()),
                ),
            }
        )
        conn = _connect(get_vector_store_path(root))
        try:
            _flush_registered_arrow_table(
                conn,
                view_name="__codira_vector_rows",
                table=table,
                sql="""
                INSERT OR REPLACE INTO vectors(
                    vector_set_id,
                    object_type,
                    stable_id,
                    content_hash,
                    vector,
                    vector_values
                )
                SELECT
                    vector_set_id,
                    object_type,
                    stable_id,
                    content_hash,
                    vector,
                    vector_values
                FROM __codira_vector_rows
                """,
            )
        finally:
            conn.close()

    def similarity_scores(
        self,
        request: VectorSimilarityRequest,
    ) -> list[VectorSimilarityScore]:
        """
        Return DuckDB-backed vector similarity scores.

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
        conn = _connect(get_vector_store_path(request.root), read_only=True)
        try:
            scored_rows = conn.execute(
                """
                SELECT stable_id, list_dot_product(vector_values, ?) AS score
                FROM vectors
                WHERE vector_set_id = ?
                  AND object_type = ?
                  AND vector_values IS NOT NULL
                  AND list_dot_product(vector_values, ?) >= ?
                ORDER BY score DESC, stable_id
                """,
                (
                    list(request.query_vector),
                    vector_set_id,
                    request.object_type,
                    list(request.query_vector),
                    request.min_score,
                ),
            ).fetchall()
            legacy_rows = conn.execute(
                """
                SELECT stable_id, vector
                FROM vectors
                WHERE vector_set_id = ?
                  AND object_type = ?
                  AND vector_values IS NULL
                ORDER BY stable_id
                """,
                (vector_set_id, request.object_type),
            ).fetchall()
        finally:
            conn.close()
        scores = [
            VectorSimilarityScore(stable_id=str(stable_id), score=float(score))
            for stable_id, score in scored_rows
        ]
        scores.extend(
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
            for stable_id, vector in legacy_rows
        )
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
