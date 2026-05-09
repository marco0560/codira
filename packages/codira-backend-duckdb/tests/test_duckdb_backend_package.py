"""Package-local tests for the first-party DuckDB backend distribution."""

from __future__ import annotations

import json
import sys
import tomllib
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codira.contracts import (
    BackendError,
    BackendPersistAnalysisRequest,
    BackendRuntimeInventoryRequest,
)
from codira.models import AnalysisResult, FileMetadataSnapshot, ModuleArtifact
from codira.schema import DDL
from codira_backend_duckdb import (
    DuckDBIndexBackend,
    _duckdb_db_path,
    _duckdb_schema_ddl,
    build_backend,
)


class _FakeDuckDBConnection:
    """Small fake raw DuckDB connection used by package-local tests."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self.committed = False
        self.closed = False

    def execute(
        self,
        query: str,
        parameters: tuple[object, ...] | None = None,
    ) -> object:
        """
        Record one executed SQL statement.

        Parameters
        ----------
        query : str
            SQL statement text.
        parameters : tuple[object, ...] | None, optional
            Bound parameters.

        Returns
        -------
        object
            The fake connection itself for cursor-style chaining.
        """
        self.executed.append((query, parameters))
        return self

    def executemany(
        self,
        query: str,
        parameters: list[tuple[object, ...]],
    ) -> object:
        """
        Record one batched SQL execution.

        Parameters
        ----------
        query : str
            SQL statement text.
        parameters : list[tuple[object, ...]]
            Bound parameter rows.

        Returns
        -------
        object
            The fake connection itself for cursor-style chaining.
        """
        self.executed.append((query, tuple(parameters)))
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        """
        Return no result rows.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[object, ...] | None
            Always ``None`` for this fake.
        """
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        """
        Return no result rows.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[object, ...]]
            Always an empty list for this fake.
        """
        return []

    def commit(self) -> None:
        """
        Mark the fake connection as committed.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The commit flag is updated in place.
        """
        self.committed = True

    def close(self) -> None:
        """
        Mark the fake connection as closed.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The closed flag is updated in place.
        """
        self.closed = True


class _FakeDuckDBModule:
    """Small fake DuckDB module used to avoid the optional dependency."""

    Error = RuntimeError

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.connections: list[_FakeDuckDBConnection] = []

    def connect(self, database: str) -> _FakeDuckDBConnection:
        """
        Return one fake connection for a database path.

        Parameters
        ----------
        database : str
            Database file path.

        Returns
        -------
        _FakeDuckDBConnection
            Fake raw connection bound to the supplied path.
        """
        self.paths.append(database)
        connection = _FakeDuckDBConnection()
        self.connections.append(connection)
        return connection


class _InventoryConnection:
    """Small connection stub that stores runtime inventory rows in memory."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self.runtime_row: tuple[str, str, int] | None = None
        self.analyzer_rows: list[tuple[str, str, str]] = []
        self.fetchone_result: tuple[object, ...] | None = None
        self.fetchall_result: list[tuple[object, ...]] = []
        self.committed = False
        self.closed = False

    def execute(
        self,
        query: str,
        parameters: tuple[object, ...] | None = None,
    ) -> object:
        """
        Record one executed SQL statement and emulate inventory tables.

        Parameters
        ----------
        query : str
            SQL statement text.
        parameters : tuple[object, ...] | None, optional
            Bound parameters.

        Returns
        -------
        object
            The fake connection itself for cursor-style chaining.
        """
        self.executed.append((query, parameters))
        normalized = " ".join(query.split())
        if normalized == "DELETE FROM index_runtime":
            self.runtime_row = None
        elif normalized == "DELETE FROM index_analyzers":
            self.analyzer_rows = []
        elif normalized.startswith("INSERT INTO index_runtime("):
            assert parameters is not None
            coverage = parameters[3]
            assert isinstance(coverage, (int, str, bytes, bytearray))
            self.runtime_row = (
                str(parameters[1]),
                str(parameters[2]),
                int(coverage),
            )
        elif normalized.startswith(
            "INSERT INTO index_analyzers(name, version, discovery_globs)"
        ):
            assert parameters is not None
            self.analyzer_rows.append(
                (
                    str(parameters[0]),
                    str(parameters[1]),
                    str(parameters[2]),
                )
            )
        elif normalized.startswith(
            "SELECT backend_name, backend_version, coverage_complete FROM index_runtime"
        ):
            self.fetchone_result = self.runtime_row
        elif normalized.startswith(
            "SELECT name, version, discovery_globs FROM index_analyzers"
        ):
            self.fetchall_result = [
                tuple(row)
                for row in sorted(self.analyzer_rows, key=lambda item: item[0])
            ]
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        """
        Return one prepared fetch-one result row.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[object, ...] | None
            Prepared runtime inventory row.
        """
        return self.fetchone_result

    def fetchall(self) -> list[tuple[object, ...]]:
        """
        Return prepared fetch-all result rows.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[object, ...]]
            Prepared analyzer inventory rows.
        """
        return list(self.fetchall_result)

    def commit(self) -> None:
        """
        Mark the fake connection as committed.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The commit flag is updated in place.
        """
        self.committed = True

    def close(self) -> None:
        """
        Mark the fake connection as closed.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The closed flag is updated in place.
        """
        self.closed = True


class _DuckDBDriverError(RuntimeError):
    """Dedicated fake DuckDB driver error type used for translation tests."""


def test_duckdb_backend_package_declares_expected_entry_point() -> None:
    """
    Keep package metadata aligned to the backend entry-point contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the package advertises the expected backend factory.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "1.5.3"
    assert project["project"]["dependencies"] == [
        "codira>=1.5.0,<2.0.0",
        "duckdb>=1.4,<2.0",
    ]
    assert project["project"]["entry-points"]["codira.backends"] == {
        "duckdb": "codira_backend_duckdb:build_backend"
    }


def test_duckdb_backend_package_builds_expected_backend() -> None:
    """
    Keep the package-local factory aligned to the published backend name.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the factory returns the expected backend type and name.
    """
    backend = build_backend()

    assert backend.__class__.__name__ == "DuckDBIndexBackend"
    assert backend.__class__.__module__ == "codira_backend_duckdb"
    assert backend.name == "duckdb"


def test_duckdb_schema_ddl_declares_sequences_and_defaults() -> None:
    """
    Keep the DuckDB schema bootstrap aligned to sequence-backed identifiers.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts rewritten DDL creates sequences and uses `nextval`.
    """
    statements = _duckdb_schema_ddl()

    assert any(
        "CREATE SEQUENCE IF NOT EXISTS files_id_seq" in stmt for stmt in statements
    )
    assert any("DEFAULT nextval('files_id_seq')" in stmt for stmt in statements)
    assert any("DEFAULT nextval('symbol_index_id_seq')" in stmt for stmt in statements)


def test_duckdb_schema_ddl_keeps_unresolved_edge_targets_nullable() -> None:
    """
    Keep unresolved graph edge targets nullable in DuckDB schema rewrites.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts DuckDB-specific edge tables avoid composite primary
        keys that would force nullable target columns to become ``NOT NULL``.
    """
    statements = _duckdb_schema_ddl()
    call_edges_statement = next(
        stmt for stmt in statements if "CREATE TABLE IF NOT EXISTS call_edges" in stmt
    )
    callable_refs_statement = next(
        stmt
        for stmt in statements
        if "CREATE TABLE IF NOT EXISTS callable_refs" in stmt
    )

    assert "PRIMARY KEY" not in call_edges_statement
    assert "callee_module TEXT" in call_edges_statement
    assert "callee_name TEXT" in call_edges_statement
    assert "PRIMARY KEY" not in callable_refs_statement
    assert "target_module TEXT" in callable_refs_statement
    assert "target_name TEXT" in callable_refs_statement


def test_duckdb_backend_initialize_bootstraps_schema_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Keep DuckDB initialization local to the package without requiring DuckDB.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the optional DuckDB import with a fake module.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts initialization opens the DuckDB path, executes schema
        DDL, commits, closes, and writes metadata.
    """
    fake_module = _FakeDuckDBModule()
    monkeypatch.setattr("codira_backend_duckdb._duckdb_module", lambda: fake_module)

    backend = DuckDBIndexBackend()
    backend.initialize(tmp_path)

    assert fake_module.paths == [str(_duckdb_db_path(tmp_path))]
    assert fake_module.connections[0].committed is True
    assert fake_module.connections[0].closed is True
    assert any(
        "CREATE SEQUENCE IF NOT EXISTS files_id_seq" in query
        for query, _parameters in fake_module.connections[0].executed
    )
    metadata = (tmp_path / ".codira" / "metadata.json").read_text(encoding="utf-8")
    assert '"schema_version": "14"' in metadata


def test_duckdb_backend_open_connection_initializes_missing_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Keep `open_connection()` responsible for initializing a missing database.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the initializer and optional dependency import.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts missing storage triggers initialization before the
        connection wrapper is returned.
    """
    fake_module = _FakeDuckDBModule()
    calls: list[Path] = []

    def fake_initialize(self: DuckDBIndexBackend, root: Path) -> None:
        del self
        calls.append(root)

    monkeypatch.setattr("codira_backend_duckdb._duckdb_module", lambda: fake_module)
    monkeypatch.setattr(DuckDBIndexBackend, "initialize", fake_initialize)

    backend = DuckDBIndexBackend()
    connection = backend.open_connection(tmp_path)

    assert calls == [tmp_path]
    assert fake_module.paths == [str(_duckdb_db_path(tmp_path))]
    assert connection is not None


def test_duckdb_backend_persist_runtime_inventory_round_trips_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Persist backend and analyzer inventory through the DuckDB backend surface.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace backend connection creation.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts runtime inventory persists and reloads
        deterministically.
    """
    connection = _InventoryConnection()
    backend = DuckDBIndexBackend()

    monkeypatch.setattr(
        "codira_backend_duckdb._duckdb_module",
        lambda: SimpleNamespace(Error=_DuckDBDriverError),
    )
    monkeypatch.setattr(
        DuckDBIndexBackend,
        "open_connection",
        lambda self, root: connection,
    )

    backend.persist_runtime_inventory(
        BackendRuntimeInventoryRequest(
            root=tmp_path,
            backend_name="duckdb",
            backend_version="1.5.3",
            coverage_complete=True,
            analyzers=(
                SimpleNamespace(
                    name="python",
                    version="1",
                    discovery_globs=("*.py",),
                ),
                SimpleNamespace(
                    name="bash",
                    version="2",
                    discovery_globs=("*.sh",),
                ),
            ),
        )
    )

    assert backend.load_runtime_inventory(tmp_path) == ("duckdb", "1.5.3", 1)
    assert backend.load_analyzer_inventory(tmp_path) == [
        ("bash", "2", json.dumps(("*.sh",))),
        ("python", "1", json.dumps(("*.py",))),
    ]
    assert connection.committed is True


def test_duckdb_backend_persist_analysis_translates_driver_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Translate driver failures into backend-neutral errors during persistence.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the optional driver and storage helper.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts driver failures surface as ``BackendError``.
    """
    connection = _InventoryConnection()
    backend = DuckDBIndexBackend()

    monkeypatch.setattr(
        "codira_backend_duckdb._duckdb_module",
        lambda: SimpleNamespace(Error=_DuckDBDriverError),
    )
    monkeypatch.setattr(
        DuckDBIndexBackend,
        "open_connection",
        lambda self, root: connection,
    )
    monkeypatch.setattr(
        "codira_backend_duckdb.get_embedding_backend",
        lambda: object(),
    )

    def _raise_driver_error(*args: object, **kwargs: object) -> tuple[int, int]:
        del args, kwargs
        raise _DuckDBDriverError("duckdb write failed")

    monkeypatch.setattr("codira_backend_duckdb._store_analysis", _raise_driver_error)

    with pytest.raises(BackendError, match="duckdb write failed"):
        backend.persist_analysis(
            BackendPersistAnalysisRequest(
                root=tmp_path,
                file_metadata=FileMetadataSnapshot(
                    path=tmp_path / "pkg" / "sample.py",
                    sha256="duckdb-analysis",
                    mtime=1.0,
                    size=1,
                ),
                analysis=AnalysisResult(
                    source_path=tmp_path / "pkg" / "sample.py",
                    module=ModuleArtifact(
                        name="pkg.sample",
                        stable_id="python:module:pkg.sample",
                        docstring=None,
                        has_docstring=0,
                    ),
                    classes=(),
                    functions=(),
                    declarations=(),
                    imports=(),
                ),
                embedding_backend=None,
            )
        )

    assert connection.closed is True


def test_duckdb_backend_open_connection_repairs_legacy_nullable_edge_schema(
    tmp_path: Path,
) -> None:
    """
    Repair legacy DuckDB edge tables created with composite primary keys.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts reopening a legacy DuckDB database restores nullable
        unresolved edge target columns.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = _duckdb_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw = duckdb.connect(str(db_path))
    try:
        for statement in _duckdb_schema_ddl():
            raw.execute(statement)
        for index_name in (
            "idx_call_edges_identity",
            "idx_call_edges_caller",
            "idx_call_edges_callee",
            "idx_call_edges_resolved",
            "idx_callable_refs_identity",
            "idx_callable_refs_owner",
            "idx_callable_refs_target",
            "idx_callable_refs_resolved",
        ):
            raw.execute(f"DROP INDEX IF EXISTS {index_name}")
        raw.execute("DROP TABLE call_edges")
        raw.execute("DROP TABLE callable_refs")
        for statement in DDL:
            if (
                "CREATE TABLE IF NOT EXISTS call_edges" in statement
                or "CREATE UNIQUE INDEX IF NOT EXISTS idx_call_edges_identity"
                in statement
                or "CREATE INDEX IF NOT EXISTS idx_call_edges_caller" in statement
                or "CREATE INDEX IF NOT EXISTS idx_call_edges_callee" in statement
                or "CREATE INDEX IF NOT EXISTS idx_call_edges_resolved" in statement
                or "CREATE TABLE IF NOT EXISTS callable_refs" in statement
                or "CREATE UNIQUE INDEX IF NOT EXISTS idx_callable_refs_identity"
                in statement
                or "CREATE INDEX IF NOT EXISTS idx_callable_refs_owner" in statement
                or "CREATE INDEX IF NOT EXISTS idx_callable_refs_target" in statement
                or "CREATE INDEX IF NOT EXISTS idx_callable_refs_resolved" in statement
            ):
                raw.execute(statement)
        raw.commit()
    finally:
        raw.close()

    connection = DuckDBIndexBackend().open_connection(tmp_path)
    connection.close()

    repaired = duckdb.connect(str(db_path))
    try:
        repaired.execute("PRAGMA table_info('call_edges')")
        call_edges_info = {
            str(row[1]): bool(int(row[3])) for row in repaired.fetchall()
        }
        repaired.execute("PRAGMA table_info('callable_refs')")
        callable_refs_info = {
            str(row[1]): bool(int(row[3])) for row in repaired.fetchall()
        }
    finally:
        repaired.close()

    assert call_edges_info["callee_module"] is False
    assert call_edges_info["callee_name"] is False
    assert callable_refs_info["target_module"] is False
    assert callable_refs_info["target_name"] is False


def test_duckdb_backend_persist_analysis_with_shared_connection_uses_real_driver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Persist one file through a shared DuckDB connection without savepoints.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace embedding generation with deterministic test
        doubles.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts shared-connection persistence succeeds against the
        real DuckDB driver and stores the indexed file row.
    """
    pytest.importorskip("duckdb")
    backend = DuckDBIndexBackend()
    connection = backend.open_connection(tmp_path)
    monkeypatch.setattr(
        "codira.sqlite_backend_support.embed_texts",
        lambda texts: [[0.0] * 384 for _text in texts],
    )

    recomputed, reused = backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=FileMetadataSnapshot(
                path=tmp_path / "pkg" / "sample.py",
                sha256="duckdb-shared-connection",
                mtime=1.0,
                size=1,
            ),
            analysis=AnalysisResult(
                source_path=tmp_path / "pkg" / "sample.py",
                module=ModuleArtifact(
                    name="pkg.sample",
                    stable_id="python:module:pkg.sample",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(),
                declarations=(),
                imports=(),
            ),
            embedding_backend=None,
            conn=connection,
        )
    )

    stored_row = connection.execute(
        "SELECT path FROM files WHERE path = ?",
        (str(tmp_path / "pkg" / "sample.py"),),
    ).fetchone()

    assert (recomputed, reused) == (1, 0)
    assert stored_row == (str(tmp_path / "pkg" / "sample.py"),)
    connection.close()
