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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import sqlite_vec  # type: ignore[import-untyped]

from codira.contracts import (
    PreparedVectorIdentityRow,
    PreparedVectorRow,
    StoredVectorRow,
    VectorSetIdentity,
    VectorSnapshot,
    VectorSnapshotMetadata,
    VectorSnapshotRequest,
    VectorStoreError,
    VectorStorePurgeRequest,
    VectorStorePurgeResult,
    VectorStoreResetRequest,
    VectorStoreResetResult,
    VectorStoreSpec,
    VectorStoreFullIndexRequest,
)
from codira.plugin_config import plugin_json_schema
from codira.semantic.embeddings import deserialize_vector
from codira.storage import get_codira_dir
from codira.utils import iter_batched

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

PACKAGE_VERSION = "1.0.6"
FORMAT_VERSION = "4"
_CACHE_LOOKUP_HASH_BATCH_SIZE = 900


def _parse_sqlite_timestamp(value: str) -> datetime | None:
    """
    Parse SQLite CURRENT_TIMESTAMP values as UTC datetimes.

    Parameters
    ----------
    value : str
        Timestamp text from ``vector_sets.created_at``.

    Returns
    -------
    datetime.datetime | None
        Parsed UTC datetime, or ``None`` when the value is not parseable.
    """
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


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


def _payload_table_name(vector_set_id: int) -> str:
    """Return the sqlite-vec table name for one vector set.

    Parameters
    ----------
    vector_set_id : int
        Persistent vector-set identifier.

    Returns
    -------
    str
        Valid, store-owned virtual table name.
    """
    return f"vector_payload_index_{vector_set_id}"


def _connect(path: Path) -> sqlite3.Connection:
    """Open a SQLite vector-store connection with sqlite-vec loaded.

    Parameters
    ----------
    path : pathlib.Path
        Vector-store database path.

    Returns
    -------
    sqlite3.Connection
        Connection ready to access ``vec0`` virtual tables.
    """
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


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

        Raises
        ------
        VectorStoreError
            If existing semantic state uses the retired storage format.
        """
        del config
        path = get_vector_store_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(path) as conn:
            existing_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(vector_sets)").fetchall()
            }
            if existing_columns and "revision" not in existing_columns:
                raise VectorStoreError(
                    f"SQLite vector-store state at {path} uses an unsupported "
                    "format. Run `codira emb reset --yes` from this repository, "
                    "then run `codira index --full`."
                )
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
                    revision INTEGER NOT NULL DEFAULT 0,
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
                CREATE TABLE IF NOT EXISTS vector_payloads (
                    id INTEGER PRIMARY KEY,
                    vector_set_id INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    UNIQUE (vector_set_id, content_hash),
                    FOREIGN KEY (vector_set_id) REFERENCES vector_sets(id)
                );
                CREATE TABLE IF NOT EXISTS vector_bindings (
                    vector_set_id INTEGER NOT NULL,
                    object_type TEXT NOT NULL,
                    stable_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    PRIMARY KEY (vector_set_id, object_type, stable_id),
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

    @staticmethod
    def _bump_revision(conn: sqlite3.Connection, vector_set_id: int) -> None:
        """Advance one vector-set revision inside the active transaction.

        Parameters
        ----------
        conn : sqlite3.Connection
            Transaction-owned vector-store connection.
        vector_set_id : int
            Materialized vector-set row to advance.

        Returns
        -------
        None
            The durable source revision increases by one.
        """

        conn.execute(
            "UPDATE vector_sets SET revision = revision + 1 WHERE id = ?",
            (vector_set_id,),
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
        with _connect(get_vector_store_path(root)) as conn:
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
        vector_set_id = int(row[0])
        table_name = _payload_table_name(vector_set_id)
        with _connect(get_vector_store_path(root)) as conn:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING vec0("
                f"content_hash TEXT, embedding float[{identity.engine.dimension}] "
                "distance_metric=cosine"
                ")"
            )
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
        cached_vectors: dict[str, bytes] = {}
        with _connect(get_vector_store_path(root)) as conn:
            for content_hash_batch in iter_batched(
                ordered_hashes,
                batch_size=_CACHE_LOOKUP_HASH_BATCH_SIZE,
            ):
                placeholders = ",".join("?" for _item in content_hash_batch)
                rows = conn.execute(
                    f"""
                    SELECT payloads.content_hash, payload_index.embedding
                    FROM vector_payloads payloads
                    JOIN vector_payload_index_{vector_set_id} payload_index
                      ON payload_index.rowid = payloads.id
                    WHERE payloads.vector_set_id = ?
                      AND payloads.content_hash IN ({placeholders})
                    """,
                    (vector_set_id, *content_hash_batch),
                ).fetchall()
                cached_vectors.update(
                    {str(content_hash): bytes(vector) for content_hash, vector in rows}
                )
        return cached_vectors

    def _store_payloads(
        self,
        conn: sqlite3.Connection,
        *,
        vector_set_id: int,
        dimension: int,
        vectors: Mapping[str, bytes],
    ) -> None:
        """Persist each payload once and mirror new payloads into sqlite-vec.

        Parameters
        ----------
        conn : sqlite3.Connection
            Open transaction-owned vector-store connection.
        vector_set_id : int
            Persistent vector-set identifier.
        dimension : int
            Embedding dimensionality used to decode vectors.
        vectors : collections.abc.Mapping[str, bytes]
            Serialized vectors keyed by their content hash.

        Returns
        -------
        None
            Missing payloads are inserted once in both persistent structures.
        """
        if not vectors:
            return
        table_name = _payload_table_name(vector_set_id)
        for content_hash, vector in sorted(vectors.items()):
            existing = conn.execute(
                "SELECT id FROM vector_payloads WHERE vector_set_id = ? AND content_hash = ?",
                (vector_set_id, content_hash),
            ).fetchone()
            if existing is not None:
                continue
            cursor = conn.execute(
                "INSERT INTO vector_payloads(vector_set_id, content_hash) VALUES (?, ?)",
                (vector_set_id, content_hash),
            )
            assert cursor.lastrowid is not None
            conn.execute(
                f"INSERT INTO {table_name}(rowid, content_hash, embedding) VALUES (?, ?, ?)",
                (
                    int(cursor.lastrowid),
                    content_hash,
                    sqlite_vec.serialize_float32(
                        deserialize_vector(vector, dim=dimension)
                    ),
                ),
            )

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
        with _connect(get_vector_store_path(root)) as conn:
            self._store_payloads(
                conn,
                vector_set_id=vector_set_id,
                dimension=identity.engine.dimension,
                vectors=vectors,
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
        with _connect(get_vector_store_path(root)) as conn:
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
        with _connect(get_vector_store_path(root)) as conn:
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
        with _connect(get_vector_store_path(root)) as conn:
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
        with _connect(get_vector_store_path(root)) as conn:
            self._store_payloads(
                conn,
                vector_set_id=vector_set_id,
                dimension=identity.engine.dimension,
                vectors={
                    prepared.content_hash: prepared.vector
                    for prepared in materialized
                    if prepared.vector is not None
                },
            )
            changed = [
                prepared
                for prepared in materialized
                if conn.execute(
                    """SELECT content_hash FROM vector_bindings
                    WHERE vector_set_id = ? AND object_type = ? AND stable_id = ?""",
                    (
                        vector_set_id,
                        prepared.row.object_type,
                        prepared.row.stable_id,
                    ),
                ).fetchone()
                != (prepared.content_hash,)
            ]
            if changed:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO vector_bindings(
                        vector_set_id, object_type, stable_id, content_hash
                    ) VALUES (?, ?, ?, ?)
                    """,
                    [
                        (
                            vector_set_id,
                            prepared.row.object_type,
                            prepared.row.stable_id,
                            prepared.content_hash,
                        )
                        for prepared in changed
                    ],
                )
                self._bump_revision(conn, vector_set_id)

    def vector_snapshot(self, request: VectorSnapshotRequest) -> VectorSnapshot:
        """Return a deterministic authoritative SQLite vector snapshot.

        Parameters
        ----------
        request : VectorSnapshotRequest
            Requested authoritative vector rows.

        Returns
        -------
        VectorSnapshot
            Rows ordered by stable identity and their durable source revision.

        Raises
        ------
        VectorStoreError
            If the configured durable vector set is no longer available.
        """
        vector_set_id = self.ensure_vector_set(
            request.root, request.identity, request.config
        )
        table_name = _payload_table_name(vector_set_id)
        with _connect(get_vector_store_path(request.root)) as conn:
            conn.execute("BEGIN")
            revision_row = conn.execute(
                "SELECT revision FROM vector_sets WHERE id = ?", (vector_set_id,)
            ).fetchone()
            if revision_row is None:
                raise VectorStoreError("Configured SQLite vector set disappeared.")
            rows = conn.execute(
                f"""
                SELECT bindings.object_type, bindings.stable_id,
                       bindings.content_hash, payload_index.embedding
                FROM vector_bindings bindings
                JOIN vector_payloads payloads
                  ON payloads.vector_set_id = bindings.vector_set_id
                 AND payloads.content_hash = bindings.content_hash
                JOIN {table_name} payload_index ON payload_index.rowid = payloads.id
                WHERE bindings.vector_set_id = ? AND bindings.object_type = ?
                ORDER BY bindings.object_type, bindings.stable_id
                """,
                (vector_set_id, request.object_type),
            ).fetchall()
        snapshot_rows = tuple(
            StoredVectorRow(
                object_type=str(object_type),
                stable_id=str(stable_id),
                content_hash=str(content_hash),
                dimension=request.identity.engine.dimension,
                vector=bytes(vector),
            )
            for object_type, stable_id, content_hash, vector in rows
        )
        return VectorSnapshot(
            metadata=VectorSnapshotMetadata(
                identity=request.identity,
                revision=int(revision_row[0]),
                object_type=request.object_type,
                row_count=len(snapshot_rows),
            ),
            rows=snapshot_rows,
        )

    def store_vectors_for_full_index(
        self,
        request: VectorStoreFullIndexRequest,
    ) -> None:
        """Persist one complete vector index in a single SQLite transaction.

        Parameters
        ----------
        request : codira.contracts.VectorStoreFullIndexRequest
            Complete materialized rows and newly encoded cache payloads.

        Returns
        -------
        None
            Bindings, payloads, and pending rows are atomically synchronized.

        Raises
        ------
        sqlite3.Error
            Raised when SQLite cannot persist the vector rows.
        ValueError
            Raised when vector payloads are incompatible with the configured
            vector-set dimension.
        """
        vector_set_id = self.ensure_vector_set(
            request.root, request.identity, request.config
        )
        materialized = [row for row in request.rows if row.vector is not None]
        desired = request.identity_rows or tuple(
            PreparedVectorIdentityRow(
                object_type=row.row.object_type,
                stable_id=row.row.stable_id,
                content_hash=row.content_hash,
                vector=row.vector,
            )
            for row in materialized
        )
        with _connect(get_vector_store_path(request.root)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing_bindings = {
                    (str(object_type), str(stable_id), str(content_hash))
                    for object_type, stable_id, content_hash in conn.execute(
                        """SELECT object_type, stable_id, content_hash
                        FROM vector_bindings WHERE vector_set_id = ?""",
                        (vector_set_id,),
                    ).fetchall()
                }
                desired_bindings = {
                    (row.object_type, row.stable_id, row.content_hash)
                    for row in desired
                }
                self._store_payloads(
                    conn,
                    vector_set_id=vector_set_id,
                    dimension=request.identity.engine.dimension,
                    vectors=request.cached_vectors,
                )
                self._store_payloads(
                    conn,
                    vector_set_id=vector_set_id,
                    dimension=request.identity.engine.dimension,
                    vectors={
                        row.content_hash: row.vector
                        for row in materialized
                        if row.vector is not None
                    },
                )
                if request.preserve_existing:
                    conn.execute(
                        "CREATE TEMP TABLE desired_bindings(object_type TEXT, stable_id TEXT)"
                    )
                    conn.executemany(
                        "INSERT INTO desired_bindings VALUES (?, ?)",
                        [(row.object_type, row.stable_id) for row in desired],
                    )
                    conn.execute(
                        """DELETE FROM vector_bindings WHERE vector_set_id = ?
                        AND NOT EXISTS (SELECT 1 FROM desired_bindings desired
                        WHERE desired.object_type = vector_bindings.object_type
                        AND desired.stable_id = vector_bindings.stable_id)""",
                        (vector_set_id,),
                    )
                else:
                    conn.execute(
                        "DELETE FROM vector_bindings WHERE vector_set_id = ?",
                        (vector_set_id,),
                    )
                conn.executemany(
                    """INSERT OR REPLACE INTO vector_bindings(
                    vector_set_id, object_type, stable_id, content_hash)
                    VALUES (?, ?, ?, ?)""",
                    [
                        (
                            vector_set_id,
                            row.row.object_type,
                            row.row.stable_id,
                            row.content_hash,
                        )
                        for row in materialized
                    ],
                )
                conn.execute(
                    "DELETE FROM pending_vectors WHERE vector_set_id = ?",
                    (vector_set_id,),
                )
                if existing_bindings != desired_bindings:
                    self._bump_revision(conn, vector_set_id)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def purge_vector_sets(
        self,
        request: VectorStorePurgeRequest,
    ) -> VectorStorePurgeResult:
        """
        Purge inactive vector sets from the SQLite vector store.

        Parameters
        ----------
        request : codira.contracts.VectorStorePurgeRequest
            Purge mode, active identity, retention filters, and dry-run flag.

        Returns
        -------
        codira.contracts.VectorStorePurgeResult
            Purge summary.
        """
        path = get_vector_store_path(request.root)
        size_before = path.stat().st_size if path.exists() else None
        active_id = (
            None
            if request.all_sets
            else self.ensure_vector_set(request.root, request.identity, request.config)
        )
        mode = "all" if request.all_sets else "stale"
        with _connect(path) as conn:
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
                parsed_created = _parse_sqlite_timestamp(str(created_at))
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
            vector_count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM vector_bindings WHERE vector_set_id IN ({placeholders})",
                    selected_ids,
                ).fetchone()[0]
            )
            cache_count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM vector_payloads WHERE vector_set_id IN ({placeholders})",
                    selected_ids,
                ).fetchone()[0]
            )
            pending_count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM pending_vectors WHERE vector_set_id IN ({placeholders})",
                    selected_ids,
                ).fetchone()[0]
            )
            if not request.dry_run:
                conn.execute(
                    f"DELETE FROM vector_bindings WHERE vector_set_id IN ({placeholders})",
                    selected_ids,
                )
                conn.execute(
                    f"DELETE FROM vector_payloads WHERE vector_set_id IN ({placeholders})",
                    selected_ids,
                )
                conn.execute(
                    f"DELETE FROM pending_vectors WHERE vector_set_id IN ({placeholders})",
                    selected_ids,
                )
                conn.execute(
                    f"DELETE FROM vector_sets WHERE id IN ({placeholders})",
                    selected_ids,
                )
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
                "SQLite may reuse freed pages before the file shrinks; "
                "run VACUUM manually if a smaller file is required."
            )
            if not request.dry_run
            else None,
        )

    def reset_runtime_caches(self) -> None:
        """Clear process-local vector-store caches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The SQLite vector store has no process-local cache yet.
        """

    def reset_persistent_state(
        self,
        request: VectorStoreResetRequest,
    ) -> VectorStoreResetResult:
        """Remove the SQLite database and its write-ahead-log sidecars.

        Parameters
        ----------
        request : codira.contracts.VectorStoreResetRequest
            Confirmed repository-local teardown request.

        Returns
        -------
        codira.contracts.VectorStoreResetResult
            Removed SQLite artifacts relative to the repository root.
        """

        path = get_vector_store_path(request.root)
        removed: list[str] = []
        for candidate in (
            path,
            path.with_name(f"{path.name}-shm"),
            path.with_name(f"{path.name}-wal"),
        ):
            if candidate.exists():
                candidate.unlink()
                removed.append(str(candidate.relative_to(request.root)))
        self.reset_runtime_caches()
        return VectorStoreResetResult(self.name, tuple(sorted(removed)))


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
