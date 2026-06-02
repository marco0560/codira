"""Package-local tests for the first-party DuckDB backend distribution."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codira.contracts import (
    BackendDocumentationCandidatesRequest,
    BackendEmbeddingCandidatesRequest,
    BackendError,
    BackendPersistAnalysisRequest,
    BackendRuntimeInventoryRequest,
)
from codira.models import (
    AnalysisResult,
    CallSite,
    DocumentationArtifact,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
)
from codira.schema import DDL, SCHEMA_VERSION
from codira_backend_duckdb import (
    DuckDBIndexBackend,
    _duckdb_db_path,
    _duckdb_schema_ddl,
    build_backend,
)
from codira_backend_duckdb.duckdb_support import _flush_pending_reference_scan_rows


_UNRESOLVED_CALL_RECORDS = (
    ("name", "", "PyLong_FromLong", 1, 4),
    ("name", "", "PyUnicode_AsUTF8AndSize", 2, 4),
    ("name", "", "system", 3, 4),
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

    def register(self, view_name: str, python_object: object) -> object:
        """
        Record one replacement-scan registration.

        Parameters
        ----------
        view_name : str
            Registered replacement-scan name.
        python_object : object
            Registered Python object.

        Returns
        -------
        object
            The fake connection itself for cursor-style chaining.
        """
        self.executed.append((f"REGISTER {view_name}", (python_object,)))
        return self

    def unregister(self, view_name: str) -> object:
        """
        Record one replacement-scan unregistration.

        Parameters
        ----------
        view_name : str
            Registered replacement-scan name.

        Returns
        -------
        object
            The fake connection itself for cursor-style chaining.
        """
        self.executed.append((f"UNREGISTER {view_name}", None))
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


class _FakeAnalyzer:
    """Small analyzer stub satisfying the LanguageAnalyzer protocol."""

    name: str
    version: str
    discovery_globs: tuple[str, ...]

    def __init__(
        self,
        name: str,
        version: str,
        discovery_globs: tuple[str, ...],
    ) -> None:
        self.name = name
        self.version = version
        self.discovery_globs = discovery_globs

    def supports_path(self, path: Path) -> bool:
        """
        Report that the stub never claims source files.

        Parameters
        ----------
        path : pathlib.Path
            Candidate file.

        Returns
        -------
        bool
            Always ``False`` for this stub.
        """
        del path
        return False

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Reject analysis requests from the stub.

        Parameters
        ----------
        path : pathlib.Path
            Source file to analyze.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        codira.models.AnalysisResult
            Never returned.

        Raises
        ------
        NotImplementedError
            Raised because the stub never performs real analysis work.
        """
        del path, root
        raise NotImplementedError


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

    assert project["project"]["version"] == "1.40.0"
    assert project["project"]["dependencies"] == [
        "codira>=1.5.0,<2.0.0",
        "duckdb>=1.4,<2.0",
        "pyarrow>=18.0.0",
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


def test_duckdb_schema_ddl_declares_symbol_detail_indexes() -> None:
    """
    Keep DuckDB exact-symbol enrichment lookups backed by supporting indexes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts DuckDB schema DDL includes indexes for module and
        function lookups used while rendering ``sym --json`` details.
    """
    statements = _duckdb_schema_ddl()

    assert any(
        "CREATE INDEX IF NOT EXISTS idx_duckdb_modules_file_name" in stmt
        and "ON modules(file_id, name)" in stmt
        for stmt in statements
    )
    assert any(
        "CREATE INDEX IF NOT EXISTS idx_duckdb_functions_symbol_detail" in stmt
        and "ON functions(name, lineno, is_method, module_id)" in stmt
        for stmt in statements
    )


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
    assert "unresolved_identity TEXT NOT NULL DEFAULT ''" in call_edges_statement
    assert "PRIMARY KEY" not in callable_refs_statement
    assert "target_module TEXT" in callable_refs_statement
    assert "target_name TEXT" in callable_refs_statement
    assert "unresolved_identity TEXT NOT NULL DEFAULT ''" in callable_refs_statement


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
    assert f'"schema_version": "{SCHEMA_VERSION}"' in metadata


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
        lambda: type("DuckDBModuleStub", (), {"Error": _DuckDBDriverError})(),
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
                _FakeAnalyzer("python", "1", ("*.py",)),
                _FakeAnalyzer("bash", "2", ("*.sh",)),
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
        lambda: type("DuckDBModuleStub", (), {"Error": _DuckDBDriverError})(),
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
        msg = "duckdb write failed"
        raise _DuckDBDriverError(msg)

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


def test_duckdb_backend_index_session_repairs_legacy_nullable_edge_schema(
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
        The test asserts starting an index session restores nullable unresolved
        edge target columns while keeping normal read-only opens cheap.
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
            "idx_call_edges_caller_lookup",
            "idx_call_edges_callee",
            "idx_call_edges_callee_lookup",
            "idx_call_edges_resolved",
            "idx_callable_refs_identity",
            "idx_callable_refs_owner",
            "idx_callable_refs_owner_lookup",
            "idx_callable_refs_target",
            "idx_callable_refs_target_lookup",
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
                or "CREATE INDEX IF NOT EXISTS idx_call_edges_caller_lookup"
                in statement
                or "CREATE INDEX IF NOT EXISTS idx_call_edges_callee" in statement
                or "CREATE INDEX IF NOT EXISTS idx_call_edges_callee_lookup"
                in statement
                or "CREATE INDEX IF NOT EXISTS idx_call_edges_resolved" in statement
                or "CREATE TABLE IF NOT EXISTS callable_refs" in statement
                or "CREATE UNIQUE INDEX IF NOT EXISTS idx_callable_refs_identity"
                in statement
                or "CREATE INDEX IF NOT EXISTS idx_callable_refs_owner" in statement
                or "CREATE INDEX IF NOT EXISTS idx_callable_refs_owner_lookup"
                in statement
                or "CREATE INDEX IF NOT EXISTS idx_callable_refs_target" in statement
                or "CREATE INDEX IF NOT EXISTS idx_callable_refs_target_lookup"
                in statement
                or "CREATE INDEX IF NOT EXISTS idx_callable_refs_resolved" in statement
            ):
                raw.execute(statement)
        raw.commit()
    finally:
        raw.close()

    backend = DuckDBIndexBackend()

    connection = backend.open_connection(tmp_path)
    connection.close()

    unrepaired = duckdb.connect(str(db_path))
    try:
        unrepaired.execute("PRAGMA table_info('call_edges')")
        unrepaired_call_edges_info = {
            str(row[1]): bool(int(row[3])) for row in unrepaired.fetchall()
        }
        unrepaired.execute("PRAGMA table_info('callable_refs')")
        unrepaired_callable_refs_info = {
            str(row[1]): bool(int(row[3])) for row in unrepaired.fetchall()
        }
    finally:
        unrepaired.close()

    assert unrepaired_call_edges_info["callee_module"] is True
    assert unrepaired_call_edges_info["callee_name"] is True
    assert unrepaired_callable_refs_info["target_module"] is True
    assert unrepaired_callable_refs_info["target_name"] is True

    session = backend.begin_index_session(tmp_path)
    session.close()

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


def test_duckdb_backend_bulk_reference_rows_preserve_empty_lines(
    tmp_path: Path,
) -> None:
    """
    Preserve empty reference-scan lines during DuckDB bulk import.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts the CSV bulk path stores empty strings instead of
        importing them as NULL values.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = _duckdb_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw = duckdb.connect(str(db_path))
    try:
        for statement in _duckdb_schema_ddl():
            raw.execute(statement)
        raw.execute(
            "INSERT INTO files"
            "(id, path, hash, mtime, size, analyzer_name, analyzer_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, str(tmp_path / "sample.py"), "hash", 1.0, 1, "python", "1"),
        )
        rows = [
            (1, lineno, "" if lineno == 50 else f"line {lineno}")
            for lineno in range(120)
        ]

        _flush_pending_reference_scan_rows(raw, rows)

        stored = raw.execute(
            "SELECT line_text FROM reference_scan_lines WHERE lineno = 50"
        ).fetchone()
        total = raw.execute("SELECT COUNT(*) FROM reference_scan_lines").fetchone()
    finally:
        raw.close()

    assert stored == ("",)
    assert total == (120,)


def test_duckdb_write_session_flushes_relationship_rows_before_rebuild(
    tmp_path: Path,
) -> None:
    """
    Flush session-level relationship rows before derived graph rebuild.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts write-session batching still persists call records
        before derived call edges are rebuilt.
    """
    pytest.importorskip("duckdb")
    backend = DuckDBIndexBackend()
    session = backend.begin_index_session(tmp_path)
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text("def demo():\n    helper()\n", encoding="utf-8")

    try:
        session.persist_analysis(
            BackendPersistAnalysisRequest(
                root=tmp_path,
                file_metadata=FileMetadataSnapshot(
                    path=source,
                    sha256="duckdb-relationship-batch",
                    mtime=1.0,
                    size=source.stat().st_size,
                ),
                analysis=AnalysisResult(
                    source_path=source,
                    module=ModuleArtifact(
                        name="pkg.sample",
                        stable_id="python:module:pkg.sample",
                        docstring=None,
                        has_docstring=0,
                    ),
                    classes=(),
                    functions=(
                        FunctionArtifact(
                            name="demo",
                            stable_id="python:function:pkg.sample:demo",
                            lineno=1,
                            end_lineno=2,
                            signature="def demo()",
                            docstring=None,
                            has_docstring=0,
                            is_method=0,
                            is_public=1,
                            parameters=(),
                            returns_value=0,
                            yields_value=0,
                            raises=0,
                            has_asserts=0,
                            decorators=(),
                            calls=(
                                CallSite(
                                    kind="name",
                                    target="helper",
                                    lineno=2,
                                    col_offset=4,
                                ),
                            ),
                            callable_refs=(),
                        ),
                    ),
                    declarations=(),
                    imports=(),
                ),
            )
        )
        session.rebuild_derived_indexes()
        session.commit()
    finally:
        session.close()

    connection = backend.open_connection(tmp_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM call_records").fetchone() == (
            1,
        )
        assert connection.execute(
            "SELECT caller_module, caller_name, unresolved_identity FROM call_edges"
        ).fetchone() == ("pkg.sample", "demo", '["name","","helper"]')
    finally:
        connection.close()


def test_duckdb_backend_initialize_repairs_legacy_edge_identity_schema(
    tmp_path: Path,
) -> None:
    """
    Repair legacy DuckDB edge tables that predate unresolved-target identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts backend initialization adds the discriminator
        column while preserving existing rows.
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
            "idx_call_edges_caller_lookup",
            "idx_call_edges_callee",
            "idx_call_edges_callee_lookup",
            "idx_call_edges_resolved",
            "idx_callable_refs_identity",
            "idx_callable_refs_owner",
            "idx_callable_refs_owner_lookup",
            "idx_callable_refs_target",
            "idx_callable_refs_target_lookup",
            "idx_callable_refs_resolved",
        ):
            raw.execute(f"DROP INDEX IF EXISTS {index_name}")
        raw.execute("DROP TABLE call_edges")
        raw.execute("DROP TABLE callable_refs")
        raw.execute("""
            CREATE TABLE call_edges (
                caller_file_id INTEGER NOT NULL,
                caller_module TEXT NOT NULL,
                caller_name TEXT NOT NULL,
                callee_module TEXT,
                callee_name TEXT,
                resolved INTEGER NOT NULL
            )
            """)
        raw.execute("""
            CREATE TABLE callable_refs (
                owner_file_id INTEGER NOT NULL,
                owner_module TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                target_module TEXT,
                target_name TEXT,
                resolved INTEGER NOT NULL
            )
            """)
        raw.execute(
            """
            INSERT INTO files(
                id,
                path,
                hash,
                mtime,
                size,
                analyzer_name,
                analyzer_version
            ) VALUES (1, ?, 'seed-hash', 1.0, 1, 'python', '1.0')
            """,
            (str(tmp_path / "pkg" / "sample.py"),),
        )
        raw.execute(
            """
            INSERT INTO call_edges(
                caller_file_id,
                caller_module,
                caller_name,
                callee_module,
                callee_name,
                resolved
            ) VALUES (1, 'pkg.sample', 'caller', NULL, NULL, 0)
            """
        )
        raw.execute(
            """
            INSERT INTO callable_refs(
                owner_file_id,
                owner_module,
                owner_name,
                target_module,
                target_name,
                resolved
            ) VALUES (1, 'pkg.sample', 'caller', NULL, NULL, 0)
            """
        )
        raw.commit()
    finally:
        raw.close()

    backend = DuckDBIndexBackend()
    backend.initialize(tmp_path)

    repaired = duckdb.connect(str(db_path))
    try:
        repaired.execute("PRAGMA table_info('call_edges')")
        call_edges_columns = {str(row[1]) for row in repaired.fetchall()}
        callable_refs_columns = {
            str(row[1])
            for row in repaired.execute("PRAGMA table_info('callable_refs')").fetchall()
        }
        call_edge_row = repaired.execute(
            "SELECT unresolved_identity FROM call_edges"
        ).fetchone()
        callable_ref_row = repaired.execute(
            "SELECT unresolved_identity FROM callable_refs"
        ).fetchone()
    finally:
        repaired.close()

    assert "unresolved_identity" in call_edges_columns
    assert "unresolved_identity" in callable_refs_columns
    assert call_edge_row == ("",)
    assert callable_ref_row == ("",)


def test_duckdb_backend_full_prepare_clears_populated_database_in_session(
    tmp_path: Path,
) -> None:
    """
    Clear a populated DuckDB index during a full rebuild session.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts a second full rebuild can clear previously indexed
        rows without tripping DuckDB foreign-key enforcement.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = _duckdb_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw = duckdb.connect(str(db_path))
    try:
        for statement in _duckdb_schema_ddl():
            raw.execute(statement)
        raw.execute(
            """
            INSERT INTO files(
                id,
                path,
                hash,
                mtime,
                size,
                analyzer_name,
                analyzer_version
            ) VALUES (1, ?, 'seed-hash', 1.0, 1, 'python', '1.0')
            """,
            (str(tmp_path / "pkg" / "sample.py"),),
        )
        raw.execute(
            """
            INSERT INTO modules(id, file_id, name, docstring, has_docstring)
            VALUES (1, 1, 'pkg.sample', NULL, 0)
            """
        )
        raw.execute(
            """
            INSERT INTO classes(
                id,
                module_id,
                name,
                lineno,
                end_lineno,
                docstring,
                has_docstring
            ) VALUES (1, 1, 'SampleClass', 1, 2, NULL, 0)
            """
        )
        raw.execute(
            """
            INSERT INTO functions(
                id,
                module_id,
                class_id,
                name,
                lineno,
                end_lineno,
                signature,
                docstring,
                has_docstring,
                is_method,
                is_public
            ) VALUES (1, 1, 1, 'method', 1, 1, NULL, NULL, 0, 1, 1)
            """
        )
        raw.commit()
    finally:
        raw.close()

    backend = DuckDBIndexBackend()
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=(), deleted_paths=())
        session.commit()
    finally:
        session.close()

    reopened = duckdb.connect(str(db_path))
    try:
        assert reopened.execute("SELECT COUNT(*) FROM files").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM modules").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM classes").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM functions").fetchone() == (0,)
    finally:
        reopened.close()


def test_duckdb_backend_rebuild_keeps_distinct_unresolved_call_edges(
    tmp_path: Path,
) -> None:
    """
    Preserve distinct unresolved call targets owned by one DuckDB caller.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts graph rebuilds keep unresolved raw target identity in
        the derived edge tables.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = _duckdb_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    module_path = tmp_path / "pkg" / "sample.py"
    raw = duckdb.connect(str(db_path))
    try:
        for statement in _duckdb_schema_ddl():
            raw.execute(statement)
        raw.execute(
            """
            INSERT INTO files(
                id,
                path,
                hash,
                mtime,
                size,
                analyzer_name,
                analyzer_version
            ) VALUES (1, ?, 'seed-hash', 1.0, 1, 'python', '1.0')
            """,
            (str(module_path),),
        )
        for kind, base, target, lineno, col_offset in _UNRESOLVED_CALL_RECORDS:
            raw.execute(
                """
                INSERT INTO call_records(
                    file_id,
                    owner_module,
                    owner_name,
                    kind,
                    base,
                    target,
                    lineno,
                    col_offset
                ) VALUES (1, 'pkg.sample', 'caller', ?, ?, ?, ?, ?)
                """,
                (kind, base, target, lineno, col_offset),
            )
        raw.commit()
    finally:
        raw.close()

    backend = DuckDBIndexBackend()
    backend.rebuild_derived_indexes(tmp_path)

    reopened = duckdb.connect(str(db_path))
    try:
        rows = reopened.execute("""
            SELECT callee_module, callee_name, unresolved_identity, resolved
            FROM call_edges
            ORDER BY unresolved_identity
            """).fetchall()
    finally:
        reopened.close()

    assert rows == [
        (
            None,
            None,
            json.dumps((kind, base, target), separators=(",", ":")),
            0,
        )
        for kind, base, target, _lineno, _col_offset in _UNRESOLVED_CALL_RECORDS
    ]


def test_duckdb_backend_rebuild_replaces_existing_resolved_edges(
    tmp_path: Path,
) -> None:
    """
    Replace existing resolved DuckDB edges without unique-index collisions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts graph rebuilds can replace an existing derived edge
        with the same identity produced from raw call records.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = _duckdb_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    module_path = tmp_path / "pkg" / "sample.py"
    raw = duckdb.connect(str(db_path))
    try:
        for statement in _duckdb_schema_ddl():
            raw.execute(statement)
        raw.execute(
            """
            INSERT INTO files(
                id,
                path,
                hash,
                mtime,
                size,
                analyzer_name,
                analyzer_version
            ) VALUES (1, ?, 'seed-hash', 1.0, 1, 'python', '1.0')
            """,
            (str(module_path),),
        )
        raw.execute(
            """
            INSERT INTO modules(id, file_id, name, docstring, has_docstring)
            VALUES (1, 1, 'pkg.sample', NULL, 0)
            """
        )
        raw.execute(
            """
            INSERT INTO functions(
                id,
                module_id,
                class_id,
                name,
                lineno,
                end_lineno,
                signature,
                docstring,
                has_docstring,
                is_method,
                is_public
            ) VALUES (1, 1, NULL, 'target', 1, 1, NULL, NULL, 0, 0, 1)
            """
        )
        raw.execute(
            """
            INSERT INTO call_records(
                file_id,
                owner_module,
                owner_name,
                kind,
                base,
                target,
                lineno,
                col_offset
            ) VALUES (1, 'pkg.sample', 'caller', 'name', '', 'target', 2, 4)
            """
        )
        raw.execute(
            """
            INSERT INTO call_edges(
                caller_file_id,
                caller_module,
                caller_name,
                callee_module,
                callee_name,
                unresolved_identity,
                resolved
            ) VALUES (1, 'pkg.sample', 'caller', 'pkg.sample', 'target', '', 1)
            """
        )
        raw.commit()
    finally:
        raw.close()

    backend = DuckDBIndexBackend()
    backend.rebuild_derived_indexes(tmp_path)

    reopened = duckdb.connect(str(db_path))
    try:
        rows = reopened.execute("""
            SELECT caller_module, caller_name, callee_module, callee_name, resolved
            FROM call_edges
            """).fetchall()
        index_names = {
            str(row[0])
            for row in reopened.execute("""
                SELECT index_name
                FROM duckdb_indexes()
                WHERE table_name IN ('call_edges', 'callable_refs')
                """).fetchall()
        }
    finally:
        reopened.close()

    assert rows == [("pkg.sample", "caller", "pkg.sample", "target", 1)]
    assert {
        "idx_call_edges_identity",
        "idx_call_edges_caller",
        "idx_call_edges_caller_lookup",
        "idx_call_edges_callee",
        "idx_call_edges_callee_lookup",
        "idx_call_edges_resolved",
        "idx_callable_refs_identity",
        "idx_callable_refs_owner",
        "idx_callable_refs_owner_lookup",
        "idx_callable_refs_target",
        "idx_callable_refs_target_lookup",
        "idx_callable_refs_resolved",
    } <= index_names


def test_duckdb_backend_delete_paths_removes_file_owned_edge_rows(
    tmp_path: Path,
) -> None:
    """
    Remove file-owned edge rows before deleting one DuckDB file record.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts deleting one indexed file also removes file-owned
        edge rows that reference the file primary key.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = _duckdb_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    module_path = tmp_path / "pkg" / "sample.py"
    raw = duckdb.connect(str(db_path))
    try:
        for statement in _duckdb_schema_ddl():
            raw.execute(statement)
        raw.execute(
            """
            INSERT INTO files(
                id,
                path,
                hash,
                mtime,
                size,
                analyzer_name,
                analyzer_version
            ) VALUES (1, ?, 'seed-hash', 1.0, 1, 'python', '1.0')
            """,
            (str(module_path),),
        )
        raw.execute(
            """
            INSERT INTO call_edges(
                caller_file_id,
                caller_module,
                caller_name,
                callee_module,
                callee_name,
                resolved
            ) VALUES (1, 'pkg.sample', 'method', NULL, NULL, 0)
            """
        )
        raw.execute(
            """
            INSERT INTO callable_refs(
                owner_file_id,
                owner_module,
                owner_name,
                target_module,
                target_name,
                resolved
            ) VALUES (1, 'pkg.sample', 'method', NULL, NULL, 0)
            """
        )
        raw.commit()
    finally:
        raw.close()

    backend = DuckDBIndexBackend()
    backend.delete_paths(tmp_path, paths=[str(module_path)])

    reopened = duckdb.connect(str(db_path))
    try:
        assert reopened.execute("SELECT COUNT(*) FROM files").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM call_edges").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM callable_refs").fetchone() == (0,)
    finally:
        reopened.close()


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
        "codira_backend_duckdb.duckdb_support.embed_texts",
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
    stored_embedding = connection.execute(
        "SELECT vector_values FROM embeddings"
    ).fetchone()

    assert (recomputed, reused) == (1, 0)
    assert stored_row == (str(tmp_path / "pkg" / "sample.py"),)
    assert stored_embedding is not None
    stored_vector_values = cast("object", stored_embedding[0])
    assert stored_vector_values == [0.0] * 384
    connection.close()


def test_duckdb_session_batches_embedding_generation_across_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Batch DuckDB session embedding generation across persisted files.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace embedding generation with a deterministic test
        double.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts session persistence makes one embedding backend call
        for two file snapshots.
    """
    pytest.importorskip("duckdb")
    calls: list[list[str]] = []

    def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        """
        Record one embedding batch.

        Parameters
        ----------
        texts : list[str]
            Text payloads requested from the embedding backend.

        Returns
        -------
        list[list[float]]
            Deterministic embedding vectors matching the requested payloads.
        """
        calls.append(list(texts))
        return [[0.0] * 384 for _text in texts]

    monkeypatch.setattr(
        "codira_backend_duckdb.duckdb_support.embed_texts",
        fake_embed_texts,
    )

    backend = DuckDBIndexBackend()
    session = backend.begin_index_session(tmp_path)
    try:
        for name in ("alpha", "beta"):
            module_path = tmp_path / "pkg" / f"{name}.py"
            module_path.parent.mkdir(parents=True, exist_ok=True)
            module_path.write_text("", encoding="utf-8")
            session.persist_analysis(
                BackendPersistAnalysisRequest(
                    root=tmp_path,
                    file_metadata=FileMetadataSnapshot(
                        path=module_path,
                        sha256=f"duckdb-session-{name}",
                        mtime=1.0,
                        size=0,
                    ),
                    analysis=AnalysisResult(
                        source_path=module_path,
                        module=ModuleArtifact(
                            name=f"pkg.{name}",
                            stable_id=f"python:module:pkg.{name}",
                            docstring=None,
                            has_docstring=0,
                        ),
                        classes=(),
                        functions=(),
                        declarations=(),
                        imports=(),
                    ),
                )
            )
        session.rebuild_derived_indexes()
        session.commit()
    finally:
        session.close()

    assert len(calls) == 1
    assert len(calls[0]) == 2


def test_duckdb_embedding_candidates_use_stored_vector_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Score DuckDB embedding candidates through stored list vectors.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace embedding generation and reject blob fallback.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts DuckDB can rank candidates without deserializing
        stored embedding blobs in Python.
    """
    pytest.importorskip("duckdb")
    backend = DuckDBIndexBackend()
    monkeypatch.setattr(
        "codira_backend_duckdb.duckdb_support.embed_texts",
        lambda texts: [[1.0] + [0.0] * 383 for _text in texts],
    )
    monkeypatch.setattr(
        "codira_backend_duckdb.duckdb_query_backend.embed_text",
        lambda text: [1.0] + [0.0] * 383,
    )

    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=FileMetadataSnapshot(
                path=tmp_path / "pkg" / "sample.py",
                sha256="duckdb-vector-values",
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
        )
    )

    def reject_blob_deserialization(blob: bytes, *, dim: int) -> list[float]:
        """
        Reject the legacy Python blob-scoring path.

        Parameters
        ----------
        blob : bytes
            Stored embedding blob supplied by a legacy fallback path.
        dim : int
            Expected embedding dimensionality.

        Returns
        -------
        list[float]
            This helper never returns.

        Raises
        ------
        AssertionError
            Always raised when the legacy fallback is used.
        """
        del blob, dim
        raise AssertionError("legacy embedding blob fallback was used")

    monkeypatch.setattr(
        "codira_backend_duckdb.duckdb_query_backend.deserialize_vector",
        reject_blob_deserialization,
    )

    results = backend.embedding_candidates(
        BackendEmbeddingCandidatesRequest(
            root=tmp_path,
            query="sample",
            limit=5,
            min_score=0.0,
        )
    )

    assert results == [
        (
            1.0,
            (
                "module",
                "pkg.sample",
                "pkg.sample",
                str(tmp_path / "pkg" / "sample.py"),
                1,
            ),
        )
    ]


def test_duckdb_documentation_candidates_use_stored_vector_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Score DuckDB documentation candidates through stored list vectors.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace embedding generation and reject blob fallback.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts DuckDB can rank documentation candidates without
        mixing them into the symbol embedding channel.
    """
    pytest.importorskip("duckdb")
    backend = DuckDBIndexBackend()
    monkeypatch.setattr(
        "codira_backend_duckdb.duckdb_support.embed_texts",
        lambda texts: [[1.0] + [0.0] * 383 for _text in texts],
    )
    monkeypatch.setattr(
        "codira_backend_duckdb.duckdb_query_backend.embed_text",
        lambda text: [1.0] + [0.0] * 383,
    )
    document = tmp_path / "docs" / "architecture.md"
    artifact = DocumentationArtifact(
        stable_id="doc:section:docs/architecture.md:plugin-loading:1",
        kind="section",
        source_format="markdown_section",
        source_path=document,
        lineno=1,
        end_lineno=3,
        title="Plugin Loading",
        heading_path=("Plugin Loading",),
        text="Plugin Loading\nPlugins are discovered through entry points.",
    )

    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=FileMetadataSnapshot(
                path=document,
                sha256="duckdb-docs",
                mtime=1.0,
                size=1,
                analyzer_name="markdown",
                analyzer_version="1",
            ),
            analysis=AnalysisResult(
                source_path=document,
                module=ModuleArtifact(
                    name="docs.architecture",
                    stable_id="module:docs.architecture",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(),
                declarations=(),
                imports=(),
                documentation=(artifact,),
                index_symbols=False,
            ),
        )
    )

    def reject_blob_deserialization(blob: bytes, *, dim: int) -> list[float]:
        """
        Reject the legacy Python blob-scoring path.

        Parameters
        ----------
        blob : bytes
            Stored embedding blob supplied by a legacy fallback path.
        dim : int
            Expected embedding dimensionality.

        Returns
        -------
        list[float]
            This helper never returns.

        Raises
        ------
        AssertionError
            Always raised when the legacy fallback is used.
        """
        del blob, dim
        raise AssertionError("legacy embedding blob fallback was used")

    monkeypatch.setattr(
        "codira_backend_duckdb.duckdb_query_backend.deserialize_vector",
        reject_blob_deserialization,
    )

    assert (
        backend.embedding_candidates(
            BackendEmbeddingCandidatesRequest(
                root=tmp_path,
                query="plugin loading entry points",
                limit=5,
                min_score=0.0,
            )
        )
        == []
    )
    assert backend.documentation_candidates(
        BackendDocumentationCandidatesRequest(
            root=tmp_path,
            query="plugin loading entry points",
            limit=5,
            min_score=0.0,
        )
    ) == [
        (
            1.0,
            (
                artifact.stable_id,
                "section",
                "markdown_section",
                str(document),
                1,
                3,
                "Plugin Loading",
                ("Plugin Loading",),
                artifact.text,
            ),
        )
    ]
