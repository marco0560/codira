"""DuckDB vector-store plugin for codira."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import duckdb

from codira.contracts import (
    PreparedVectorIdentityRow,
    PreparedVectorRow,
    VectorSetIdentity,
    VectorStoreFullIndexRequest,
    VectorStorePurgeRequest,
    VectorStorePurgeResult,
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

PACKAGE_VERSION = "1.0.8"
FORMAT_VERSION = "1"


def _normalize_duckdb_timestamp(value: object) -> datetime | None:
    """
    Normalize DuckDB timestamp values to UTC datetimes.

    Parameters
    ----------
    value : object
        Timestamp value returned by DuckDB.

    Returns
    -------
    datetime.datetime | None
        Parsed UTC datetime, or ``None`` when the value is not parseable.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _flush_registered_arrow_table(
    conn: duckdb.DuckDBPyConnection,
    *,
    view_name: str,
    table: object,
    sql: str,
    parameters: tuple[object, ...] | None = None,
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
    parameters : tuple[object, ...] | None, optional
        Bound parameters for ``sql``.

    Returns
    -------
    None
        The statement is executed and the temporary relation is unregistered.
    """
    conn.register(view_name, table)
    try:
        if parameters is None:
            conn.execute(sql)
        else:
            conn.execute(sql, parameters)
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


def _materialized_identity_rows(
    request: VectorStoreFullIndexRequest,
) -> tuple[PreparedVectorIdentityRow, ...]:
    """
    Return complete desired materialized vector identities for a full index.

    Parameters
    ----------
    request : codira.contracts.VectorStoreFullIndexRequest
        Full-index vector-store request.

    Returns
    -------
    tuple[codira.contracts.PreparedVectorIdentityRow, ...]
        Complete identity rows when supplied by the caller, otherwise a
        compatibility projection from payload-bearing rows.
    """
    if request.identity_rows:
        return tuple(request.identity_rows)
    return tuple(
        PreparedVectorIdentityRow(
            object_type=prepared.row.object_type,
            stable_id=prepared.row.stable_id,
            content_hash=prepared.content_hash,
            vector=prepared.vector,
        )
        for prepared in request.rows
    )


def _matching_materialized_keys(
    conn: duckdb.DuckDBPyConnection,
    *,
    vector_set_id: int,
    identity_rows: Sequence[PreparedVectorIdentityRow],
) -> set[tuple[str, str, str]]:
    """
    Return existing materialized vector keys that already match the full index.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        Open vector-store connection.
    vector_set_id : int
        Persistent vector-set identifier.
    identity_rows : collections.abc.Sequence[codira.contracts.PreparedVectorIdentityRow]
        Desired materialized vector identities.

    Returns
    -------
    set[tuple[str, str, str]]
        Existing ``(object_type, stable_id, content_hash)`` keys that can be
        preserved without rewriting vector payloads.
    """
    if not identity_rows:
        return set()
    import pyarrow as pa

    table = pa.table(
        {
            "vector_set_id": pa.array(
                [vector_set_id for _row in identity_rows],
                type=pa.uint64(),
            ),
            "object_type": pa.array(
                [row.object_type for row in identity_rows],
                type=pa.string(),
            ),
            "stable_id": pa.array(
                [row.stable_id for row in identity_rows],
                type=pa.string(),
            ),
            "content_hash": pa.array(
                [row.content_hash for row in identity_rows],
                type=pa.string(),
            ),
        }
    )
    conn.register("__codira_full_index_vector_identity_rows", table)
    try:
        rows = conn.execute(
            """
            SELECT vectors.object_type, vectors.stable_id, vectors.content_hash
            FROM vectors
            JOIN __codira_full_index_vector_identity_rows desired
              ON vectors.vector_set_id = desired.vector_set_id
             AND vectors.object_type = desired.object_type
             AND vectors.stable_id = desired.stable_id
             AND vectors.content_hash = desired.content_hash
            """
        ).fetchall()
    finally:
        conn.unregister("__codira_full_index_vector_identity_rows")
    return {(str(row[0]), str(row[1]), str(row[2])) for row in rows}


def _delete_stale_materialized_vectors(
    conn: duckdb.DuckDBPyConnection,
    *,
    vector_set_id: int,
    identity_rows: Sequence[PreparedVectorIdentityRow],
) -> None:
    """
    Delete materialized vector rows absent from the desired full-index set.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        Open vector-store connection.
    vector_set_id : int
        Persistent vector-set identifier.
    identity_rows : collections.abc.Sequence[codira.contracts.PreparedVectorIdentityRow]
        Desired materialized vector identities.

    Returns
    -------
    None
        Stale materialized vectors for the vector set are removed in place.
    """
    import pyarrow as pa

    table = pa.table(
        {
            "vector_set_id": pa.array(
                [vector_set_id for _row in identity_rows],
                type=pa.uint64(),
            ),
            "object_type": pa.array(
                [row.object_type for row in identity_rows],
                type=pa.string(),
            ),
            "stable_id": pa.array(
                [row.stable_id for row in identity_rows],
                type=pa.string(),
            ),
        }
    )
    _flush_registered_arrow_table(
        conn,
        view_name="__codira_full_index_desired_vector_rows",
        table=table,
        sql="""
        DELETE FROM vectors
        WHERE vector_set_id = ?
          AND NOT EXISTS (
              SELECT 1
              FROM __codira_full_index_desired_vector_rows desired
              WHERE desired.vector_set_id = vectors.vector_set_id
                AND desired.object_type = vectors.object_type
                AND desired.stable_id = vectors.stable_id
          )
        """,
        parameters=(vector_set_id,),
    )


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

    def __init__(self) -> None:
        """
        Initialize process-local DuckDB vector-store caches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Cache storage starts empty for the vector-store instance.
        """
        self._vector_set_ids: dict[tuple[str, VectorSetIdentity], int] = {}

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
        cache_key = (str(root.resolve()), identity)
        cached_id = self._vector_set_ids.get(cache_key)
        if cached_id is not None:
            return cached_id

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
        vector_set_id = int(row[0])
        self._vector_set_ids[cache_key] = vector_set_id
        return vector_set_id

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

    def store_vectors_for_full_index(
        self,
        request: VectorStoreFullIndexRequest,
    ) -> None:
        """
        Persist materialized vectors for one full-index bulk run.

        Parameters
        ----------
        request : codira.contracts.VectorStoreFullIndexRequest
            Bulk vector persistence request. DuckDB vector storage currently
            remains separated from the structural backend database, so the
            optional backend connection is intentionally ignored.

        Returns
        -------
        None
            Vector rows replace the materialized contents for the vector set.

        Raises
        ------
        BaseException
            Propagates DuckDB or Arrow failures after rolling back the active
            transaction when possible.
        """
        materialized = [
            (prepared, prepared.vector)
            for prepared in request.rows
            if prepared.vector is not None
        ]
        identity_rows = _materialized_identity_rows(request)
        vector_set_id = self.ensure_vector_set(
            request.root,
            request.identity,
            request.config,
        )
        conn = _connect(get_vector_store_path(request.root))
        transaction_open = False
        try:
            conn.execute("BEGIN TRANSACTION")
            transaction_open = True
            preserved_keys: set[tuple[str, str, str]] = set()
            if request.preserve_existing:
                preserved_keys = _matching_materialized_keys(
                    conn,
                    vector_set_id=vector_set_id,
                    identity_rows=identity_rows,
                )
                _delete_stale_materialized_vectors(
                    conn,
                    vector_set_id=vector_set_id,
                    identity_rows=identity_rows,
                )
            else:
                conn.execute(
                    "DELETE FROM vectors WHERE vector_set_id = ?",
                    (vector_set_id,),
                )
            conn.execute(
                "DELETE FROM pending_vectors WHERE vector_set_id = ?",
                (vector_set_id,),
            )
            if request.cached_vectors:
                import pyarrow as pa

                ordered_vectors = sorted(request.cached_vectors.items())
                cache_table = pa.table(
                    {
                        "vector_set_id": pa.array(
                            [
                                vector_set_id
                                for _content_hash, _vector in ordered_vectors
                            ],
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
                                deserialize_vector(
                                    vector,
                                    dim=request.identity.engine.dimension,
                                )
                                for _content_hash, vector in ordered_vectors
                            ],
                            type=pa.list_(pa.float64()),
                        ),
                    }
                )
                _flush_registered_arrow_table(
                    conn,
                    view_name="__codira_full_index_vector_cache_rows",
                    table=cache_table,
                    sql="""
                    INSERT OR REPLACE INTO vector_cache(
                        vector_set_id,
                        content_hash,
                        vector,
                        vector_values
                    )
                    SELECT
                        vector_set_id,
                        content_hash,
                        vector,
                        vector_values
                    FROM __codira_full_index_vector_cache_rows
                    """,
                )
            materialized_to_write = [
                (prepared, vector)
                for prepared, vector in materialized
                if (
                    prepared.row.object_type,
                    prepared.row.stable_id,
                    prepared.content_hash,
                )
                not in preserved_keys
            ]
            if materialized_to_write:
                import pyarrow as pa

                table = pa.table(
                    {
                        "vector_set_id": pa.array(
                            [
                                vector_set_id
                                for _prepared, _vector in materialized_to_write
                            ],
                            type=pa.uint64(),
                        ),
                        "object_type": pa.array(
                            [
                                prepared.row.object_type
                                for prepared, _vector in materialized_to_write
                            ],
                            type=pa.string(),
                        ),
                        "stable_id": pa.array(
                            [
                                prepared.row.stable_id
                                for prepared, _vector in materialized_to_write
                            ],
                            type=pa.string(),
                        ),
                        "content_hash": pa.array(
                            [
                                prepared.content_hash
                                for prepared, _vector in materialized_to_write
                            ],
                            type=pa.string(),
                        ),
                        "vector": pa.array(
                            [vector for _prepared, vector in materialized_to_write],
                            type=pa.binary(),
                        ),
                        "vector_values": pa.array(
                            [
                                deserialize_vector(
                                    vector,
                                    dim=request.identity.engine.dimension,
                                )
                                for _prepared, vector in materialized_to_write
                            ],
                            type=pa.list_(pa.float64()),
                        ),
                    }
                )
                _flush_registered_arrow_table(
                    conn,
                    view_name="__codira_full_index_vector_rows",
                    table=table,
                    sql="""
                    INSERT INTO vectors(
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
                    FROM __codira_full_index_vector_rows
                    """,
                )
            conn.execute("COMMIT")
            transaction_open = False
        except BaseException:
            if transaction_open:
                conn.execute("ROLLBACK")
            raise
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

    def purge_vector_sets(
        self,
        request: VectorStorePurgeRequest,
    ) -> VectorStorePurgeResult:
        """
        Purge vector sets from the DuckDB vector store.

        Parameters
        ----------
        request : codira.contracts.VectorStorePurgeRequest
            Purge mode, active identity, retention filters, and dry-run flag.

        Returns
        -------
        codira.contracts.VectorStorePurgeResult
            Purge summary.

        Raises
        ------
        RuntimeError
            If DuckDB returns an invalid aggregate count result.
        """
        path = get_vector_store_path(request.root)
        size_before = path.stat().st_size if path.exists() else None
        active_id = (
            None
            if request.all_sets
            else self.ensure_vector_set(request.root, request.identity, request.config)
        )
        mode = "all" if request.all_sets else "stale"
        conn = _connect(path)
        try:
            rows = conn.execute(
                """
                SELECT id, created_at
                FROM vector_sets
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
            cutoff = (
                datetime.now(UTC) - timedelta(days=request.older_than_days)
                if request.older_than_days is not None
                else None
            )
            candidates: list[tuple[int, datetime | None]] = []
            kept_stale = 0
            for row_id, created_at in rows:
                vector_set_id = int(row_id)
                if active_id is not None and vector_set_id == active_id:
                    continue
                parsed_created = _normalize_duckdb_timestamp(created_at)
                if not request.all_sets and cutoff is not None:
                    if parsed_created is None or parsed_created >= cutoff:
                        kept_stale += 1
                        continue
                candidates.append((vector_set_id, parsed_created))
            if not request.all_sets and request.keep > 0:
                kept_stale += min(request.keep, len(candidates))
                candidates = candidates[request.keep :]
            selected_ids = [vector_set_id for vector_set_id, _created in candidates]
            if not selected_ids:
                return VectorStorePurgeResult(
                    store=self.name,
                    mode=mode,
                    dry_run=request.dry_run,
                    active_vector_set_id=active_id,
                    stale_vector_sets=0,
                    kept_stale_vector_sets=kept_stale,
                    deleted_vectors=0,
                    deleted_cached_vectors=0,
                    deleted_pending_vectors=0,
                    deleted_vector_sets=0,
                    size_before_bytes=size_before,
                    size_after_bytes=size_before,
                )
            placeholders = ",".join("?" for _item in selected_ids)
            vector_count_row = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM vectors
                WHERE vector_set_id IN ({placeholders})
                """,
                selected_ids,
            ).fetchone()
            cache_count_row = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM vector_cache
                WHERE vector_set_id IN ({placeholders})
                """,
                selected_ids,
            ).fetchone()
            pending_count_row = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM pending_vectors
                WHERE vector_set_id IN ({placeholders})
                """,
                selected_ids,
            ).fetchone()
            if (
                vector_count_row is None
                or cache_count_row is None
                or pending_count_row is None
            ):
                msg = "DuckDB COUNT query returned no row during vector purge"
                raise RuntimeError(msg)
            vector_count = int(vector_count_row[0])
            cache_count = int(cache_count_row[0])
            pending_count = int(pending_count_row[0])
            if not request.dry_run:
                conn.execute(
                    f"DELETE FROM vectors WHERE vector_set_id IN ({placeholders})",
                    selected_ids,
                )
                conn.execute(
                    f"""
                    DELETE FROM vector_cache
                    WHERE vector_set_id IN ({placeholders})
                    """,
                    selected_ids,
                )
                conn.execute(
                    f"""
                    DELETE FROM pending_vectors
                    WHERE vector_set_id IN ({placeholders})
                    """,
                    selected_ids,
                )
                conn.execute(
                    f"DELETE FROM vector_sets WHERE id IN ({placeholders})",
                    selected_ids,
                )
                conn.execute("CHECKPOINT")
                self.reset_runtime_caches()
        finally:
            conn.close()
        return VectorStorePurgeResult(
            store=self.name,
            mode=mode,
            dry_run=request.dry_run,
            active_vector_set_id=active_id,
            stale_vector_sets=len(selected_ids),
            kept_stale_vector_sets=kept_stale,
            deleted_vectors=vector_count,
            deleted_cached_vectors=cache_count,
            deleted_pending_vectors=pending_count,
            deleted_vector_sets=len(selected_ids),
            size_before_bytes=size_before,
            size_after_bytes=path.stat().st_size if path.exists() else None,
            note=(
                "DuckDB may reuse freed blocks before the file shrinks; "
                "CHECKPOINT was run after the purge."
            )
            if not request.dry_run
            else None,
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
            Process-local vector-set identity cache entries are cleared.
        """
        self._vector_set_ids.clear()


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
