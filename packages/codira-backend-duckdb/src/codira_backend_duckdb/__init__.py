"""First-party DuckDB backend plugin package for codira.

Responsibilities
----------------
- Publish the canonical DuckDB backend through the `codira.backends` entry-point group.
- Own the concrete DuckDB backend implementation at the package boundary.
- Keep the package-facing backend factory explicit and deterministic.

Design principles
-----------------
The package mirrors the SQLite backend contract while keeping DuckDB-specific
storage initialization and connection behavior local to the package.

Architectural role
------------------
This module belongs to the **first-party backend plugin layer** and provides
the production DuckDB backend introduced by issue `#10`.
"""

from __future__ import annotations

import importlib
import json
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from codira.contracts import (
    BackendError,
    BackendPersistAnalysisRequest,
    BackendRuntimeInventoryRequest,
)
from codira.schema import DDL, SCHEMA_VERSION
from codira.semantic.embeddings import get_embedding_backend
from codira.sqlite_backend_support import _store_analysis
from codira.storage import get_codira_dir, get_metadata_path
from codira_backend_sqlite import SQLiteIndexBackend

if TYPE_CHECKING:
    from collections.abc import Sequence

    from codira.contracts import IndexBackend
    from codira.sqlite_backend_support import StoredEmbeddingRow

PACKAGE_VERSION = "1.5.3"
_INSERT_TABLE_PATTERN = re.compile(r"^\s*INSERT\s+INTO\s+([a-z_]+)", re.IGNORECASE)
_SEQUENCED_TABLES: tuple[str, ...] = (
    "files",
    "modules",
    "classes",
    "functions",
    "imports",
    "overloads",
    "enum_members",
    "docstring_issues",
    "symbol_index",
    "embeddings",
)
_TABLE_ID_SEQUENCE: dict[str, str] = {
    table: f"{table}_id_seq" for table in _SEQUENCED_TABLES
}
_SEQUENCE_REWRITE_PREFIXES: tuple[str, ...] = tuple(
    f"CREATE TABLE IF NOT EXISTS {table} (" for table in _SEQUENCED_TABLES
)


class _DuckDBRawConnection(Protocol):
    """DuckDB connection surface used by the backend wrapper."""

    def execute(self, query: str, parameters: Sequence[object] | None = None) -> object:
        """
        Execute one SQL statement.

        Parameters
        ----------
        query : str
            SQL statement to execute.
        parameters : Sequence[object] | None, optional
            Positional parameters bound to ``query``.

        Returns
        -------
        object
            Driver-specific execution result.
        """

    def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[object]],
    ) -> object:
        """
        Execute one statement against many parameter rows.

        Parameters
        ----------
        query : str
            SQL statement to execute repeatedly.
        parameters : Sequence[Sequence[object]]
            Parameter rows bound to ``query``.

        Returns
        -------
        object
            Driver-specific execution result.
        """

    def fetchone(self) -> tuple[object, ...] | None:
        """
        Fetch one row from the most recent result.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[object, ...] | None
            Next available row, or ``None`` when the result is exhausted.
        """

    def fetchall(self) -> list[tuple[object, ...]]:
        """
        Fetch all rows from the most recent result.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[object, ...]]
            Remaining result rows.
        """

    def commit(self) -> None:
        """
        Commit the current transaction.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The active transaction is committed in place.
        """

    def close(self) -> None:
        """
        Close the active connection.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The active connection is closed in place.
        """


class _DuckDBModule(Protocol):
    """DuckDB module surface used for lazy dependency loading."""

    Error: type[BaseException]

    def connect(self, database: str) -> _DuckDBRawConnection:
        """
        Open one persistent DuckDB database.

        Parameters
        ----------
        database : str
            Database path passed to the DuckDB driver.

        Returns
        -------
        _DuckDBRawConnection
            Open raw DuckDB connection handle.
        """


class _DuckDBCursorWrapper:
    """Minimal DB-API-like cursor wrapper with `lastrowid` support."""

    def __init__(
        self,
        raw: _DuckDBRawConnection,
        *,
        lastrowid: int | None = None,
    ) -> None:
        self._raw = raw
        self.lastrowid = lastrowid

    def fetchone(self) -> tuple[object, ...] | None:
        """
        Return the next result row from the wrapped DuckDB connection.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[object, ...] | None
            Next available row or ``None`` when the result is exhausted.
        """
        return self._raw.fetchone()

    def fetchall(self) -> list[tuple[object, ...]]:
        """
        Return every remaining result row from the wrapped connection.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[object, ...]]
            Remaining result rows.
        """
        return self._raw.fetchall()


class DuckDBConnection:
    """Connection adapter exposing the subset used by codira helpers."""

    def __init__(self, raw: _DuckDBRawConnection) -> None:
        self._raw = raw

    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
    ) -> _DuckDBCursorWrapper:
        """
        Execute one SQL statement and expose a cursor-like wrapper.

        Parameters
        ----------
        query : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[object] | None, optional
            Positional parameters for the statement.

        Returns
        -------
        _DuckDBCursorWrapper
            Cursor wrapper exposing fetch methods and `lastrowid` when
            applicable.
        """
        if parameters is None:
            self._raw.execute(query)
        else:
            self._raw.execute(query, parameters)
        return _DuckDBCursorWrapper(
            self._raw,
            lastrowid=_duckdb_lastrowid(self._raw, query),
        )

    def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[object]],
    ) -> _DuckDBCursorWrapper:
        """
        Execute one SQL statement against many parameter rows.

        Parameters
        ----------
        query : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[collections.abc.Sequence[object]]
            Parameter rows for the statement.

        Returns
        -------
        _DuckDBCursorWrapper
            Cursor wrapper over the most recent execution.
        """
        self._raw.executemany(query, parameters)
        return _DuckDBCursorWrapper(self._raw)

    def commit(self) -> None:
        """
        Commit the active DuckDB transaction.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Pending writes are committed.
        """
        self._raw.commit()

    def close(self) -> None:
        """
        Close the active DuckDB connection.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The wrapped connection is closed.
        """
        self._raw.close()


def _duckdb_module() -> _DuckDBModule:
    """
    Return the lazily imported DuckDB Python module.

    Parameters
    ----------
    None

    Returns
    -------
    _DuckDBModule
        Imported DuckDB module.

    Raises
    ------
    codira.contracts.BackendError
        If the optional DuckDB dependency is not installed.
    """
    try:
        module = importlib.import_module("duckdb")
    except ModuleNotFoundError as exc:
        msg = (
            "DuckDB backend requires the optional `duckdb` package. "
            "Install `codira-backend-duckdb` with its declared dependencies."
        )
        raise BackendError(msg) from exc
    return cast("_DuckDBModule", module)


def _duckdb_db_path(root: Path) -> Path:
    """
    Return the DuckDB database path for one repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to the `index.duckdb` file under `.codira`.
    """
    return get_codira_dir(root) / "index.duckdb"


def _rewrite_duckdb_ddl(statement: str) -> str:
    """
    Rewrite one canonical schema statement for DuckDB sequence-backed IDs.

    Parameters
    ----------
    statement : str
        Canonical schema DDL statement.

    Returns
    -------
    str
        DuckDB-compatible statement.
    """
    for table, prefix in zip(
        _SEQUENCED_TABLES, _SEQUENCE_REWRITE_PREFIXES, strict=True
    ):
        if prefix in statement:
            return statement.replace(
                "id INTEGER PRIMARY KEY,",
                f"id INTEGER PRIMARY KEY DEFAULT nextval('{_TABLE_ID_SEQUENCE[table]}'),",
                1,
            )
    return statement


def _duckdb_schema_ddl() -> tuple[str, ...]:
    """
    Return DuckDB schema statements for the codira backend store.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[str, ...]
        Sequence creation statements followed by rewritten table/index DDL.
    """
    sequence_statements = tuple(
        f"CREATE SEQUENCE IF NOT EXISTS {sequence_name} START 1;"
        for sequence_name in _TABLE_ID_SEQUENCE.values()
    )
    table_statements = tuple(_rewrite_duckdb_ddl(statement) for statement in DDL)
    return (*sequence_statements, *table_statements)


def _write_schema_metadata(root: Path) -> None:
    """
    Persist the active schema version under the repository metadata file.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose metadata should be updated.

    Returns
    -------
    None
        Metadata is rewritten atomically in place.
    """
    metadata_path = get_metadata_path(root)
    metadata: dict[str, str]
    if metadata_path.exists():
        try:
            metadata = dict(json.loads(metadata_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            metadata = {}
    else:
        metadata = {}
    metadata["schema_version"] = str(SCHEMA_VERSION)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )


def _duckdb_lastrowid(raw: _DuckDBRawConnection, query: str) -> int | None:
    """
    Resolve one sequence-backed inserted ID for helper compatibility.

    Parameters
    ----------
    raw : _DuckDBRawConnection
        Active raw DuckDB connection.
    query : str
        SQL statement that was just executed.

    Returns
    -------
    int | None
        Inserted integer ID for sequence-backed tables, otherwise ``None``.

    Raises
    ------
    codira.contracts.BackendError
        Raised when DuckDB returns a non-integer sequence value.
    """
    match = _INSERT_TABLE_PATTERN.match(query)
    if match is None:
        return None
    table_name = match.group(1).lower()
    sequence_name = _TABLE_ID_SEQUENCE.get(table_name)
    if sequence_name is None:
        return None
    raw.execute(f"SELECT currval('{sequence_name}')")
    row = raw.fetchone()
    if row is None:
        return None
    value = row[0]
    if isinstance(value, (int, str, bytes, bytearray)):
        return int(value)
    msg = "DuckDB sequence returned a non-integer identifier."
    raise BackendError(msg)


class DuckDBIndexBackend(SQLiteIndexBackend):
    """
    Concrete DuckDB backend exposed from the package boundary.

    The backend mirrors SQLite query semantics while owning a DuckDB-specific
    storage file, schema bootstrap, and error translation layer.
    """

    name = "duckdb"
    version = SCHEMA_VERSION

    def initialize(self, root: Path) -> None:
        """
        Prepare the repository-local DuckDB database.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should exist.

        Returns
        -------
        None
            The DuckDB schema and metadata are created or refreshed in place.
        """
        db_path = _duckdb_db_path(root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        module = _duckdb_module()
        raw = module.connect(str(db_path))
        try:
            for statement in _duckdb_schema_ddl():
                raw.execute(statement)
            raw.commit()
        finally:
            raw.close()
        _write_schema_metadata(root)

    def open_connection(self, root: Path) -> sqlite3.Connection:
        """
        Open a DuckDB connection for one repository index.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index database should be opened.

        Returns
        -------
        sqlite3.Connection
            Open DuckDB connection adapter.
        """
        if not _duckdb_db_path(root).exists():
            self.initialize(root)
        raw = _duckdb_module().connect(str(_duckdb_db_path(root)))
        return cast("sqlite3.Connection", DuckDBConnection(raw))

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Persist normalized artifacts for one analyzed file.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request carrying file metadata, normalized analysis,
            embedding backend metadata, reusable embeddings, and optional
            connection reuse.

        Returns
        -------
        tuple[int, int]
            ``(recomputed, reused)`` embedding counts for the file.

        Raises
        ------
        codira.contracts.BackendError
            Raised when the DuckDB driver reports one persistence failure.
        """
        root = request.root
        error_type = _duckdb_module().Error
        conn = cast("DuckDBConnection | None", request.conn)
        owns_connection = conn is None
        if conn is None:
            conn = cast("DuckDBConnection", self.open_connection(root))
        assert conn is not None
        active_backend = (
            get_embedding_backend()
            if request.embedding_backend is None
            else request.embedding_backend
        )
        try:
            if owns_connection:
                written = _store_analysis(
                    cast("sqlite3.Connection", conn),
                    request.file_metadata,
                    request.analysis,
                    backend=active_backend,
                    previous_embeddings=cast(
                        "dict[str, StoredEmbeddingRow] | None",
                        request.previous_embeddings,
                    ),
                )
            else:
                # DuckDB does not support SQLite-style savepoints, so isolate
                # each file write in its own transaction on the shared
                # connection instead.
                conn.commit()
                conn.execute("BEGIN TRANSACTION")
                try:
                    written = _store_analysis(
                        cast("sqlite3.Connection", conn),
                        request.file_metadata,
                        request.analysis,
                        backend=active_backend,
                        previous_embeddings=cast(
                            "dict[str, StoredEmbeddingRow] | None",
                            request.previous_embeddings,
                        ),
                    )
                except (OSError, error_type, RuntimeError, ValueError):
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
            if owns_connection:
                conn.commit()
            return written
        except error_type as exc:
            msg = str(exc)
            raise BackendError(msg) from exc
        finally:
            if owns_connection:
                conn.close()

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Persist backend and analyzer inventory for one successful index run.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory persistence request.

        Returns
        -------
        None
            Runtime inventory rows are replaced in place.

        Raises
        ------
        codira.contracts.BackendError
            Raised when the DuckDB driver reports one inventory-write failure.
        """
        root = request.root
        backend_name = request.backend_name
        backend_version = request.backend_version
        coverage_complete = request.coverage_complete
        analyzers = request.analyzers
        error_type = _duckdb_module().Error
        conn = cast("DuckDBConnection | None", request.conn)
        owns_connection = conn is None
        if conn is None:
            conn = cast("DuckDBConnection", self.open_connection(root))
        assert conn is not None
        try:
            conn.execute("DELETE FROM index_runtime")
            conn.execute("DELETE FROM index_analyzers")
            conn.execute(
                """
                INSERT INTO index_runtime(
                    singleton,
                    backend_name,
                    backend_version,
                    coverage_complete
                ) VALUES (?, ?, ?, ?)
                """,
                (1, backend_name, backend_version, int(coverage_complete)),
            )
            for analyzer in sorted(analyzers, key=lambda item: str(item.name)):
                conn.execute(
                    """
                    INSERT INTO index_analyzers(name, version, discovery_globs)
                    VALUES (?, ?, ?)
                    """,
                    (
                        str(analyzer.name),
                        str(analyzer.version),
                        json.dumps(tuple(analyzer.discovery_globs)),
                    ),
                )
            if owns_connection:
                conn.commit()
        except error_type as exc:
            msg = str(exc)
            raise BackendError(msg) from exc
        finally:
            if owns_connection:
                conn.close()


def build_backend() -> IndexBackend:
    """
    Build the first-party DuckDB backend plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.IndexBackend
        Active DuckDB backend instance.
    """
    return cast("IndexBackend", DuckDBIndexBackend())
