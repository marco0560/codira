"""Package-local tests for the first-party SQLite backend distribution."""

from __future__ import annotations

import json
import sqlite3
import tomllib
from pathlib import Path

import pytest

from codira.contracts import BackendPersistAnalysisRequest, PendingEmbeddingRow
from codira.models import AnalysisResult, FileMetadataSnapshot, ModuleArtifact
from codira.schema import DDL
from codira.semantic.embeddings import EmbeddingBackendSpec, deserialize_vector
from codira_backend_sqlite import SQLiteIndexBackend, build_backend
from codira_backend_sqlite.sqlite_support import _flush_pending_embedding_rows


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

    assert project["project"]["version"] == "1.45.0"
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


def test_sqlite_backend_exposes_configuration_schema() -> None:
    """
    Expose a strict first-party backend configuration schema.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts SQLite currently accepts only common plugin options.
    """

    schema = SQLiteIndexBackend().configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)

    assert schema["additionalProperties"] is False
    assert sorted(properties) == ["enabled"]


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


def test_sqlite_backend_counts_reusable_embeddings_in_path_batches(
    tmp_path: Path,
) -> None:
    """
    Count reusable embeddings when reused paths exceed SQLite variable limits.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts reusable embedding counting chunks path bindings.
    """
    backend = SQLiteIndexBackend()
    connection = backend.open_connection(tmp_path)
    try:
        for index in range(1001):
            path = tmp_path / "pkg" / f"module_{index}.py"
            connection.execute(
                """
                INSERT INTO files(path, hash, mtime, size, analyzer_name, analyzer_version)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(path), f"hash-{index}", 1.0, 1, "python", "4"),
            )
            file_id = int(
                connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO symbol_index(name, stable_id, type, module_name, file_id, lineno)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"pkg.module_{index}",
                    f"python:module:pkg.module_{index}",
                    "module",
                    f"pkg.module_{index}",
                    file_id,
                    1,
                ),
            )
            symbol_id = int(
                connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO embeddings(
                    object_type,
                    object_id,
                    backend,
                    version,
                    content_hash,
                    dim,
                    vector
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("symbol", symbol_id, "local", "1", f"content-{index}", 1, b"\0"),
            )
        connection.commit()

        count = backend.count_reusable_embeddings(
            tmp_path,
            paths=[
                str(tmp_path / "pkg" / f"module_{index}.py") for index in range(1001)
            ],
            conn=connection,
        )
    finally:
        connection.close()

    assert count == 1001


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


def test_sqlite_session_batches_embedding_generation_across_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Batch SQLite session embedding generation across persisted files.

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
    calls: list[list[str]] = []

    def fake_embed_texts(
        texts: list[str], *, root: Path | None = None
    ) -> list[list[float]]:
        """
        Record one embedding batch.

        Parameters
        ----------
        texts : list[str]
            Text payloads requested from the embedding backend.
        root : pathlib.Path | None, optional
            Repository root passed by backend persistence.

        Returns
        -------
        list[list[float]]
            Deterministic embedding vectors matching the requested payloads.
        """
        assert root == tmp_path
        calls.append(list(texts))
        return [[0.0] * 384 for _text in texts]

    monkeypatch.setattr(
        "codira_backend_sqlite.sqlite_support.embed_texts",
        fake_embed_texts,
    )

    backend = SQLiteIndexBackend()
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
                        sha256=f"sqlite-session-{name}",
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


def test_sqlite_pending_embeddings_replace_duplicate_documentation_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Replace duplicate pending documentation embeddings by storage key.

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
        The test asserts duplicate pending documentation embedding rows are
        collapsed and persisted with the latest payload.
    """
    calls: list[list[str]] = []

    def fake_embed_texts(
        texts: list[str], *, root: Path | None = None
    ) -> list[list[float]]:
        """
        Record one embedding batch.

        Parameters
        ----------
        texts : list[str]
            Text payloads requested from the embedding backend.
        root : pathlib.Path | None, optional
            Repository root passed by backend persistence.

        Returns
        -------
        list[list[float]]
            Deterministic embedding vectors matching the requested payloads.
        """
        assert root == tmp_path
        calls.append(list(texts))
        return [[float(index + 1)] + [0.0] * 383 for index, _text in enumerate(texts)]

    monkeypatch.setattr(
        "codira_backend_sqlite.sqlite_support.embed_texts",
        fake_embed_texts,
    )

    backend = SQLiteIndexBackend()
    connection = backend.open_connection(tmp_path)
    try:
        _flush_pending_embedding_rows(
            connection,
            tmp_path,
            pending_embedding_rows=[
                (
                    PendingEmbeddingRow(
                        object_type="documentation",
                        object_id=1,
                        stable_id="doc:existing",
                        text="existing",
                    ),
                    "existing-hash",
                    None,
                ),
            ],
            backend=EmbeddingBackendSpec(
                name="test-backend",
                version="1",
                dim=384,
            ),
        )
        _flush_pending_embedding_rows(
            connection,
            tmp_path,
            pending_embedding_rows=[
                (
                    PendingEmbeddingRow(
                        object_type="documentation",
                        object_id=1,
                        stable_id="doc:first",
                        text="first",
                    ),
                    "first-hash",
                    None,
                ),
                (
                    PendingEmbeddingRow(
                        object_type="documentation",
                        object_id=1,
                        stable_id="doc:latest",
                        text="latest",
                    ),
                    "latest-hash",
                    None,
                ),
            ],
            backend=EmbeddingBackendSpec(
                name="test-backend",
                version="1",
                dim=384,
            ),
        )
        stored_rows = connection.execute(
            """
            SELECT object_type, object_id, backend, version, content_hash, vector
            FROM embeddings
            """
        ).fetchall()
    finally:
        connection.close()

    assert calls == [["existing"], ["latest"]]
    assert len(stored_rows) == 1
    assert stored_rows[0][:5] == (
        "documentation",
        1,
        "test-backend",
        "1",
        "latest-hash",
    )
    assert deserialize_vector(stored_rows[0][5], dim=384) == [1.0] + [0.0] * 383
