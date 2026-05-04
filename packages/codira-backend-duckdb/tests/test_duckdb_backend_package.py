"""Package-local tests for the first-party DuckDB backend distribution."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codira.contracts import IndexBackend
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

    assert isinstance(backend, IndexBackend)
    assert isinstance(backend, DuckDBIndexBackend)
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
