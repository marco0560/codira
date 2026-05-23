"""Package-local tests for the first-party SQLite backend distribution."""

from __future__ import annotations

import json
import sqlite3
import tomllib
from pathlib import Path

from codira.schema import DDL
from codira_backend_sqlite import SQLiteIndexBackend, build_backend


_UNRESOLVED_CALL_RECORDS = (
    ("name", "", "PyLong_FromLong", 1, 4),
    ("name", "", "PyUnicode_AsUTF8AndSize", 2, 4),
    ("name", "", "system", 3, 4),
)


def test_sqlite_backend_package_declares_expected_entry_point() -> None:
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
    assert project["project"]["dependencies"] == ["codira>=1.5.0,<2.0.0"]
    assert project["project"]["entry-points"]["codira.backends"] == {
        "sqlite": "codira_backend_sqlite:build_backend"
    }


def test_sqlite_backend_package_builds_expected_backend() -> None:
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

    assert backend.__class__.__name__ == "SQLiteIndexBackend"
    assert backend.__class__.__module__ == "codira_backend_sqlite"
    assert backend.name == "sqlite"


def test_sqlite_backend_open_connection_enables_foreign_keys(
    tmp_path: Path,
) -> None:
    """
    Enable SQLite foreign-key enforcement on every opened connection.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts opened SQLite connections report
        `PRAGMA foreign_keys = ON`.
    """
    backend = SQLiteIndexBackend()
    connection = backend.open_connection(tmp_path)
    try:
        pragma_value = connection.execute("PRAGMA foreign_keys").fetchone()
    finally:
        connection.close()

    assert pragma_value == (1,)


def test_sqlite_backend_full_prepare_clears_populated_database_in_session(
    tmp_path: Path,
) -> None:
    """
    Clear a populated SQLite index during a full rebuild session.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts full-rebuild preparation succeeds with foreign-key
        enforcement enabled and removes previously indexed rows.
    """
    backend = SQLiteIndexBackend()
    db_path = tmp_path / ".codira" / "index.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        for statement in DDL:
            connection.execute(statement)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
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
        connection.execute(
            """
            INSERT INTO modules(id, file_id, name, docstring, has_docstring)
            VALUES (1, 1, 'pkg.sample', NULL, 0)
            """
        )
        connection.execute(
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
        connection.execute(
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
        connection.commit()
    finally:
        connection.close()

    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=(), deleted_paths=())
        session.commit()
    finally:
        session.close()

    reopened = backend.open_connection(tmp_path)
    try:
        assert reopened.execute("SELECT COUNT(*) FROM files").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM modules").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM classes").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM functions").fetchone() == (0,)
    finally:
        reopened.close()


def test_sqlite_backend_rebuild_keeps_distinct_unresolved_call_edges(
    tmp_path: Path,
) -> None:
    """
    Preserve distinct unresolved call targets owned by one SQLite caller.

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
    backend = SQLiteIndexBackend()
    db_path = tmp_path / ".codira" / "index.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    module_path = tmp_path / "pkg" / "sample.py"
    connection = sqlite3.connect(db_path)
    try:
        for statement in DDL:
            connection.execute(statement)
        connection.execute(
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
            connection.execute(
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
        connection.commit()
    finally:
        connection.close()

    backend.rebuild_derived_indexes(tmp_path)

    reopened = sqlite3.connect(db_path)
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


def test_sqlite_backend_delete_paths_removes_file_owned_edge_rows(
    tmp_path: Path,
) -> None:
    """
    Remove file-owned edge rows before deleting one SQLite file record.

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
    backend = SQLiteIndexBackend()
    db_path = tmp_path / ".codira" / "index.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    module_path = tmp_path / "pkg" / "sample.py"
    connection = sqlite3.connect(db_path)
    try:
        for statement in DDL:
            connection.execute(statement)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
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
        connection.execute(
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
        connection.execute(
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
        connection.commit()
    finally:
        connection.close()

    backend.delete_paths(tmp_path, paths=[str(module_path)])

    reopened = backend.open_connection(tmp_path)
    try:
        assert reopened.execute("SELECT COUNT(*) FROM files").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM call_edges").fetchone() == (0,)
        assert reopened.execute("SELECT COUNT(*) FROM callable_refs").fetchone() == (0,)
    finally:
        reopened.close()
