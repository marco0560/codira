"""Package-local tests for the first-party DuckDB backend distribution."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codira.models import (
    AnalysisResult,
)
from codira.semantic.embeddings import EmbeddingBackendSpec
from codira_backend_duckdb.duckdb_support import EmbeddingTextRequest
from codira_backend_duckdb.duckdb_call_resolution import (
    _import_alias_map,
    _unresolved_identity,
)
from codira_backend_duckdb.duckdb_embedding_payload import (
    _embedding_content_hash,
    _embedding_text,
)
from codira_backend_duckdb.duckdb_bulk_io import (
    _flush_registered_arrow_table,
    _temporary_csv_path_for_rows,
)
from codira_backend_duckdb.duckdb_reference_scan import (
    _reference_scan_rows,
)
from codira_backend_duckdb.duckdb_index_state import (
    _count_indexed_files,
    _current_embedding_state_matches,
    _load_existing_file_hashes,
    _load_existing_file_ownership,
)
from codira_backend_duckdb.duckdb_embedding_state import (
    _count_reused_embeddings,
    _load_previous_embeddings_by_path,
    _load_previous_symbol_embeddings,
    _prune_orphaned_embeddings,
)
from codira_backend_duckdb.duckdb_docstring_policy import (
    _should_audit_docstrings,
    _should_require_raises_section,
)
from codira_backend_duckdb.duckdb_maintenance import (
    _clear_index_tables,
    _purge_skipped_docstring_issues,
)
from codira_backend_duckdb.duckdb_query_graph import _validated_graph_identifier
from codira_backend_duckdb.duckdb_graph_lookup import _caller_class_from_owner
from codira_backend_duckdb.duckdb_query_primitives import (
    _backend_bytes,
    _backend_float,
    _backend_int,
)

if TYPE_CHECKING:
    from codira_backend_duckdb.duckdb_support import _DuckDBPersistenceConnection


_UNRESOLVED_CALL_RECORDS = (
    ("name", "", "PyLong_FromLong", 1, 4),
    ("name", "", "PyUnicode_AsUTF8AndSize", 2, 4),
    ("name", "", "system", 3, 4),
)


def test_duckdb_call_resolution_helpers_preserve_alias_and_identity_rules() -> None:
    """
    Preserve the isolated DuckDB call-resolution helper behavior.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts aliases and unresolved identities remain deterministic.
    """
    assert _import_alias_map([{"name": "package.module", "alias": None}]) == {
        "module": "package.module",
        "package.module": "package.module",
    }
    assert (
        _unresolved_identity(
            {"kind": "name", "base": "", "target": "missing"}, resolved=0
        )
        == '["name","","missing"]'
    )


def test_duckdb_embedding_payload_helpers_preserve_text_and_hash_rules() -> None:
    """
    Preserve the isolated DuckDB embedding payload helper behavior.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts payload order and content identity remain deterministic.
    """
    text = _embedding_text(
        EmbeddingTextRequest(
            module_name="package.module",
            symbol_name="symbol",
            symbol_type="function",
            signature="() -> None",
            docstring="Summary.",
            extra_context=("context", ""),
        )
    )
    assert text == "function\npackage.module\nsymbol\n() -> None\nSummary.\ncontext"
    assert _embedding_content_hash(text) == _embedding_content_hash(text)


def test_duckdb_docstring_policy_preserves_audit_exclusions() -> None:
    """Preserve DuckDB docstring-audit source and pytest exclusions.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts shell files and pytest test callables remain excluded.
    """
    assert not _should_audit_docstrings(Path("script.sh"))
    assert _should_audit_docstrings(Path("src/package.py"))
    assert not _should_require_raises_section(Path("tests/test_sample.py"), "test_case")
    assert _should_require_raises_section(Path("src/package.py"), "run")


def test_duckdb_graph_identifier_guard_preserves_the_query_vocabulary() -> None:
    """
    Restrict interpolated graph identifiers to the package-owned vocabulary.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts valid graph names are retained and arbitrary SQL is rejected.
    """
    assert _validated_graph_identifier("call_edges", kind="table") == "call_edges"
    assert _validated_graph_identifier("caller_module", kind="column") == (
        "caller_module"
    )
    assert _caller_class_from_owner("Package.Class.method") == "Package.Class"
    assert _caller_class_from_owner("function") is None

    with pytest.raises(ValueError, match="Unsafe DuckDB graph table identifier"):
        _validated_graph_identifier("call_edges; DROP TABLE files", kind="table")
    with pytest.raises(ValueError, match="Unsupported DuckDB graph column identifier"):
        _validated_graph_identifier("path", kind="column")


def test_duckdb_query_primitives_preserve_scalar_coercions() -> None:
    """
    Retain scalar coercion semantics used by DuckDB query rows.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts each helper retains its prior conversion behavior.
    """
    assert _backend_int(2.0) == 2
    assert _backend_float("1.25") == 1.25
    assert _backend_bytes(bytearray(b"codira")) == b"codira"


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


def test_duckdb_bulk_io_helpers_preserve_csv_and_cleanup_rules() -> None:
    """
    Preserve DuckDB bulk transport serialization and replacement-scan cleanup.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts CSV rows are retained and temporary views are released.
    """
    csv_path = _temporary_csv_path_for_rows(((1, "alpha"), (2, "")))
    try:
        assert csv_path.read_text(encoding="utf-8").splitlines() == [
            "1,alpha",
            "2,",
        ]
    finally:
        csv_path.unlink()

    connection = _FakeDuckDBConnection()
    table = object()
    _flush_registered_arrow_table(
        cast("_DuckDBPersistenceConnection", connection),
        view_name="__codira_test_rows",
        table=table,
        insert_sql="INSERT INTO target SELECT * FROM __codira_test_rows",
    )
    assert connection.executed == [
        ("REGISTER __codira_test_rows", (table,)),
        ("INSERT INTO target SELECT * FROM __codira_test_rows", None),
        ("UNREGISTER __codira_test_rows", None),
    ]


def test_duckdb_maintenance_helpers_preserve_cleanup_statements() -> None:
    """Preserve DuckDB maintenance cleanup ownership and statement order.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts lifecycle cleanup statements remain package-local.
    """
    connection = _FakeDuckDBConnection()
    _clear_index_tables(cast("_DuckDBPersistenceConnection", connection))
    _purge_skipped_docstring_issues(cast("_DuckDBPersistenceConnection", connection))

    assert connection.executed[0] == ("DELETE FROM docstring_issues", None)
    assert connection.executed[-2] == ("DELETE FROM analysis_status", None)
    assert "analyzer_name = 'bash'" in connection.executed[-1][0]


def test_duckdb_reference_scan_rows_exclude_import_lines(tmp_path: Path) -> None:
    """
    Keep query-time reference scans free of import declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used to hold the source fixture.

    Returns
    -------
    None
        The test asserts only non-import source lines are retained.
    """
    path = tmp_path / "sample.py"
    path.write_text(
        "import module\nfrom package import name\nname()\n", encoding="utf-8"
    )

    assert _reference_scan_rows(path) == [(str(path), 3, "name()")]


def test_duckdb_index_state_helpers_preserve_backend_metadata_rules(
    tmp_path: Path,
) -> None:
    """
    Preserve DuckDB index-state query behavior at its extraction boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used for the isolated DuckDB database.

    Returns
    -------
    None
        The test asserts metadata, hash, ownership, and count queries agree.
    """
    duckdb = pytest.importorskip("duckdb")
    raw = duckdb.connect(":memory:")
    try:
        raw.execute(
            "CREATE TABLE files (path VARCHAR, hash VARCHAR, analyzer_name VARCHAR, analyzer_version VARCHAR)"
        )
        raw.execute(
            "CREATE TABLE embeddings (backend VARCHAR, version VARCHAR, dim INTEGER)"
        )
        raw.execute(
            "INSERT INTO files VALUES (?, ?, ?, ?)",
            (str(tmp_path / "module.py"), "hash", "python", "11"),
        )
        raw.execute("INSERT INTO embeddings VALUES (?, ?, ?)", ("local", "1", 3))
        connection = cast("_DuckDBPersistenceConnection", raw)
        backend = EmbeddingBackendSpec(name="local", version="1", dim=3)

        assert _current_embedding_state_matches(connection, backend)
        assert _load_existing_file_hashes(connection) == {
            str(tmp_path / "module.py"): "hash"
        }
        assert _count_indexed_files(connection) == 1
        assert _load_existing_file_ownership(connection) == {
            str(tmp_path / "module.py"): ("python", "11")
        }
    finally:
        raw.close()


def test_duckdb_embedding_state_loads_symbol_and_documentation_rows(
    tmp_path: Path,
) -> None:
    """
    Preserve reusable DuckDB embedding loading across durable owner types.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used to derive the indexed source path.

    Returns
    -------
    None
        The test asserts both symbol and documentation embeddings are returned.
    """
    duckdb = pytest.importorskip("duckdb")
    raw = duckdb.connect(":memory:")
    path = str(tmp_path / "module.py")
    try:
        raw.execute("CREATE TABLE files (id INTEGER, path VARCHAR)")
        raw.execute(
            "CREATE TABLE symbol_index (id INTEGER, file_id INTEGER, stable_id VARCHAR)"
        )
        raw.execute(
            "CREATE TABLE documentation_artifacts (id INTEGER, file_id INTEGER, stable_id VARCHAR)"
        )
        raw.execute(
            "CREATE TABLE embeddings (object_type VARCHAR, object_id INTEGER, backend VARCHAR, version VARCHAR, content_hash VARCHAR, dim INTEGER, vector BLOB)"
        )
        raw.execute("INSERT INTO files VALUES (1, ?)", (path,))
        raw.execute("INSERT INTO symbol_index VALUES (2, 1, 'symbol-id')")
        raw.execute("INSERT INTO documentation_artifacts VALUES (3, 1, 'docs-id')")
        raw.execute(
            "INSERT INTO embeddings VALUES ('symbol', 2, 'local', '1', 'symbol-hash', 2, ?)",
            (b"12",),
        )
        raw.execute(
            "INSERT INTO embeddings VALUES ('documentation', 3, 'local', '1', 'docs-hash', 2, ?)",
            (b"34",),
        )
        raw.execute(
            "INSERT INTO embeddings VALUES ('symbol', 99, 'local', '1', 'orphan-hash', 2, ?)",
            (b"56",),
        )

        rows = _load_previous_symbol_embeddings(
            cast("_DuckDBPersistenceConnection", raw),
            path,
            backend=EmbeddingBackendSpec(name="local", version="1", dim=2),
        )
        rows_by_path = _load_previous_embeddings_by_path(
            cast("_DuckDBPersistenceConnection", raw),
            [path],
            backend=EmbeddingBackendSpec(name="local", version="1", dim=2),
        )
        reused_count = _count_reused_embeddings(
            cast("_DuckDBPersistenceConnection", raw),
            [path],
        )
        _prune_orphaned_embeddings(cast("_DuckDBPersistenceConnection", raw))
        remaining = raw.execute("SELECT COUNT(*) FROM embeddings").fetchone()
    finally:
        raw.close()

    assert rows["symbol-id"].content_hash == "symbol-hash"
    assert rows["symbol-id"].vector == b"12"
    assert rows["docs-id"].content_hash == "docs-hash"
    assert set(rows_by_path[path]) == {"symbol-id", "docs-id"}
    assert reused_count == 3
    assert remaining == (2,)


class _RejectingExecutemanyDuckDBConnection(_FakeDuckDBConnection):
    """Fake DuckDB connection that rejects row-wise batch execution."""

    def executemany(
        self,
        query: str,
        parameters: list[tuple[object, ...]],
    ) -> object:
        """
        Reject row-wise DuckDB batch execution.

        Parameters
        ----------
        query : str
            SQL statement text.
        parameters : list[tuple[object, ...]]
            Bound parameter rows.

        Returns
        -------
        object
            Never returned because the method always fails.

        Raises
        ------
        AssertionError
            Raised whenever a helper attempts row-wise execution.
        """
        raise AssertionError("executemany must not be used for DuckDB batches")


class _FailingExecuteDuckDBConnection(_RejectingExecutemanyDuckDBConnection):
    """Fake DuckDB connection that fails registered batch execution."""

    def execute(
        self,
        query: str,
        parameters: tuple[object, ...] | None = None,
    ) -> object:
        """
        Fail non-registration SQL execution.

        Parameters
        ----------
        query : str
            SQL statement text.
        parameters : tuple[object, ...] | None, optional
            Bound parameters.

        Returns
        -------
        object
            The fake connection itself for registration statements.

        Raises
        ------
        RuntimeError
            Raised for the statement executed against a registered table.
        """
        self.executed.append((query, parameters))
        raise RuntimeError("synthetic DuckDB batch failure")


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
