"""Persistent storage helpers for the codira SQLite database.

Responsibilities
----------------
- Manage metadata files, advisory locks, and schema application for the local index.
- Initialize, migrate, and query the SQLite database using the centralized DDL definitions.
- Provide helpers for atomic metadata writes, lock acquisition, and coverage diagnostics.

Design principles
-----------------
Storage helpers keep persistence deterministic, leverage Git-owned directories, and use atomic operations when mutating files.

Architectural role
------------------
This module belongs to the **storage layer** that bridges the SQLite database with indexer, analyzer, and query components.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import tempfile
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.schema import DDL, SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Protocol

    class _FcntlModule(Protocol):
        LOCK_EX: int
        LOCK_UN: int

        def flock(self, fd: int, operation: int, /) -> None: ...


_STORAGE_ROOT_OVERRIDES: ContextVar[dict[Path, Path] | None] = ContextVar(
    "_STORAGE_ROOT_OVERRIDES",
    default=None,
)


def _read_metadata_file(path: Path) -> dict[str, str]:
    """
    Load persisted index metadata from one JSON file.

    Parameters
    ----------
    path : pathlib.Path
        Metadata JSON path to decode.

    Returns
    -------
    dict[str, str]
        Parsed metadata values, or an empty mapping when the file does not
        exist or cannot be decoded.
    """
    if not path.exists():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _write_metadata_file(path: Path, data: dict[str, str]) -> None:
    """
    Persist index metadata atomically as JSON.

    Parameters
    ----------
    path : pathlib.Path
        Metadata JSON path to replace.
    data : dict[str, str]
        Metadata payload to serialize.

    Returns
    -------
    None
        The metadata file is replaced atomically in place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    temp_path = Path(handle.name)
    temp_path.replace(path)


def get_index_lock_path(root: Path) -> Path:
    """
    Return the advisory lock path used for index mutations.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to the ``index.lock`` file under ``.codira``.
    """
    return get_codira_dir(root) / "index.lock"


def get_storage_root(root: Path) -> Path:
    """
    Return the effective storage root for one repository target root.

    Parameters
    ----------
    root : pathlib.Path
        Repository target root.

    Returns
    -------
    pathlib.Path
        Effective storage root after applying any active CLI override.
    """

    resolved_root = root.resolve()
    overrides = _STORAGE_ROOT_OVERRIDES.get()
    if overrides is None:
        return resolved_root
    return overrides.get(resolved_root, resolved_root)


@contextlib.contextmanager
def override_storage_root(root: Path, storage_root: Path) -> Iterator[None]:
    """
    Temporarily route ``.codira`` storage for one target root elsewhere.

    Parameters
    ----------
    root : pathlib.Path
        Repository target root used for reads and prefix normalization.
    storage_root : pathlib.Path
        Output root under which ``.codira`` state should be read and written.

    Yields
    ------
    None
        Control while the storage override remains active.
    """

    current = _STORAGE_ROOT_OVERRIDES.get()
    overrides = {} if current is None else dict(current)
    overrides[root.resolve()] = storage_root.resolve()
    token = _STORAGE_ROOT_OVERRIDES.set(overrides)
    try:
        yield
    finally:
        _STORAGE_ROOT_OVERRIDES.reset(token)


@contextlib.contextmanager
def acquire_index_lock(root: Path) -> Iterator[None]:
    """
    Acquire the advisory cross-process lock for index mutations.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose local index should be locked.

    Yields
    ------
    None
        Control while the exclusive lock is held.

    Raises
    ------
    RuntimeError
        If the current platform does not provide ``fcntl.flock``.
    """
    try:
        import fcntl as _fcntl
    except ImportError as error:  # pragma: no cover - exercised on non-POSIX
        msg = "Index locking requires fcntl.flock on this platform."
        raise RuntimeError(msg) from error
    fcntl = cast("_FcntlModule", _fcntl)

    lock_path = get_index_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _refresh_call_edges_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``call_edges`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(call_edges)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "caller_file_id",
        "caller_module",
        "caller_name",
        "callee_module",
        "callee_name",
        "resolved",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_call_edges_identity")
    conn.execute("DROP INDEX IF EXISTS idx_call_edges_caller")
    conn.execute("DROP INDEX IF EXISTS idx_call_edges_callee")
    conn.execute("DROP INDEX IF EXISTS idx_call_edges_resolved")
    conn.execute("DROP TABLE IF EXISTS call_edges")


def _refresh_callable_refs_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``callable_refs`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(callable_refs)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "owner_file_id",
        "owner_module",
        "owner_name",
        "target_module",
        "target_name",
        "resolved",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_callable_refs_identity")
    conn.execute("DROP INDEX IF EXISTS idx_callable_refs_owner")
    conn.execute("DROP INDEX IF EXISTS idx_callable_refs_target")
    conn.execute("DROP INDEX IF EXISTS idx_callable_refs_resolved")
    conn.execute("DROP TABLE IF EXISTS callable_refs")


def _refresh_call_records_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``call_records`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(call_records)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "file_id",
        "owner_module",
        "owner_name",
        "kind",
        "base",
        "target",
        "lineno",
        "col_offset",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_call_records_file")
    conn.execute("DROP INDEX IF EXISTS idx_call_records_owner")
    conn.execute("DROP TABLE IF EXISTS call_records")


def _refresh_callable_ref_records_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``callable_ref_records`` table when an older schema exists.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(callable_ref_records)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "file_id",
        "owner_module",
        "owner_name",
        "kind",
        "ref_kind",
        "base",
        "target",
        "lineno",
        "col_offset",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_callable_ref_records_file")
    conn.execute("DROP INDEX IF EXISTS idx_callable_ref_records_owner")
    conn.execute("DROP TABLE IF EXISTS callable_ref_records")


def _refresh_docstring_issues_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``docstring_issues`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(docstring_issues)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "id",
        "file_id",
        "function_id",
        "class_id",
        "module_id",
        "issue_type",
        "message",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_docstring_issues_file")
    conn.execute("DROP TABLE IF EXISTS docstring_issues")


def _refresh_overloads_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``overloads`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(overloads)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "id",
        "function_id",
        "stable_id",
        "parent_stable_id",
        "ordinal",
        "signature",
        "docstring",
        "lineno",
        "end_lineno",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_overloads_stable_id")
    conn.execute("DROP INDEX IF EXISTS idx_overloads_function")
    conn.execute("DROP TABLE IF EXISTS overloads")


def _refresh_enum_members_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``enum_members`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(enum_members)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "id",
        "file_id",
        "module_name",
        "symbol_name",
        "symbol_lineno",
        "stable_id",
        "parent_stable_id",
        "ordinal",
        "name",
        "signature",
        "lineno",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_enum_members_stable_id")
    conn.execute("DROP INDEX IF EXISTS idx_enum_members_symbol")
    conn.execute("DROP TABLE IF EXISTS enum_members")


def _refresh_imports_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``imports`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(imports)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "id",
        "module_id",
        "name",
        "alias",
        "kind",
        "lineno",
    ]

    if current == expected:
        return

    conn.execute("DROP TABLE IF EXISTS imports")


def _refresh_files_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``files`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(files)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "id",
        "path",
        "hash",
        "mtime",
        "size",
        "analyzer_name",
        "analyzer_version",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_files_path")
    conn.execute("DROP INDEX IF EXISTS idx_embeddings_object_backend_version")
    conn.execute("DROP INDEX IF EXISTS idx_symbol_name")
    conn.execute("DROP INDEX IF EXISTS idx_symbol_file")
    conn.execute("DROP INDEX IF EXISTS idx_docstring_issues_file")
    conn.execute("DROP INDEX IF EXISTS idx_call_edges_identity")
    conn.execute("DROP INDEX IF EXISTS idx_call_edges_caller")
    conn.execute("DROP INDEX IF EXISTS idx_call_edges_callee")
    conn.execute("DROP INDEX IF EXISTS idx_call_edges_resolved")
    conn.execute("DROP INDEX IF EXISTS idx_callable_refs_identity")
    conn.execute("DROP INDEX IF EXISTS idx_callable_refs_owner")
    conn.execute("DROP INDEX IF EXISTS idx_callable_refs_target")
    conn.execute("DROP INDEX IF EXISTS idx_callable_refs_resolved")
    conn.execute("DROP INDEX IF EXISTS idx_call_records_file")
    conn.execute("DROP INDEX IF EXISTS idx_call_records_owner")
    conn.execute("DROP INDEX IF EXISTS idx_callable_ref_records_file")
    conn.execute("DROP INDEX IF EXISTS idx_callable_ref_records_owner")
    conn.execute("DROP INDEX IF EXISTS idx_overloads_stable_id")
    conn.execute("DROP INDEX IF EXISTS idx_overloads_function")
    conn.execute("DROP INDEX IF EXISTS idx_functions_name")
    conn.execute("DROP INDEX IF EXISTS idx_classes_name")
    conn.execute("DROP TABLE IF EXISTS embeddings")
    conn.execute("DROP TABLE IF EXISTS symbol_index")
    conn.execute("DROP TABLE IF EXISTS docstring_issues")
    conn.execute("DROP TABLE IF EXISTS overloads")
    conn.execute("DROP TABLE IF EXISTS callable_ref_records")
    conn.execute("DROP TABLE IF EXISTS call_records")
    conn.execute("DROP TABLE IF EXISTS callable_refs")
    conn.execute("DROP TABLE IF EXISTS call_edges")
    conn.execute("DROP TABLE IF EXISTS imports")
    conn.execute("DROP TABLE IF EXISTS functions")
    conn.execute("DROP TABLE IF EXISTS classes")
    conn.execute("DROP TABLE IF EXISTS modules")
    conn.execute("DROP TABLE IF EXISTS index_runtime")
    conn.execute("DROP TABLE IF EXISTS index_analyzers")
    conn.execute("DROP TABLE IF EXISTS files")


def _refresh_index_runtime_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``index_runtime`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(index_runtime)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "singleton",
        "backend_name",
        "backend_version",
        "coverage_complete",
    ]

    if current == expected:
        return

    conn.execute("DROP TABLE IF EXISTS index_runtime")


def _refresh_index_analyzers_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``index_analyzers`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(index_analyzers)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "name",
        "version",
        "discovery_globs",
    ]

    if current == expected:
        return

    conn.execute("DROP TABLE IF EXISTS index_analyzers")


def _refresh_symbol_index_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``symbol_index`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(symbol_index)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "id",
        "name",
        "stable_id",
        "type",
        "module_name",
        "file_id",
        "lineno",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_embeddings_object_backend_version")
    conn.execute("DROP TABLE IF EXISTS embeddings")
    conn.execute("DROP INDEX IF EXISTS idx_symbol_name")
    conn.execute("DROP INDEX IF EXISTS idx_symbol_file")
    conn.execute("DROP INDEX IF EXISTS idx_symbol_stable_id")
    conn.execute("DROP TABLE IF EXISTS symbol_index")


def _refresh_embeddings_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the ``embeddings`` table when an older schema is present.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection to migrate in place.

    Returns
    -------
    None
        The table is replaced only when its columns do not match the current
        schema definition.
    """
    columns = conn.execute("PRAGMA table_info(embeddings)").fetchall()
    if not columns:
        return

    current = [str(row[1]) for row in columns]
    expected = [
        "id",
        "object_type",
        "object_id",
        "backend",
        "version",
        "content_hash",
        "dim",
        "vector",
    ]

    if current == expected:
        return

    conn.execute("DROP INDEX IF EXISTS idx_embeddings_object_backend")
    conn.execute("DROP INDEX IF EXISTS idx_embeddings_object_backend_version")
    conn.execute("DROP TABLE IF EXISTS embeddings")


def get_codira_dir(root: Path) -> Path:
    """
    Return the repository-local storage directory.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to the ``.codira`` directory under the effective storage root.
    """
    return get_storage_root(root) / ".codira"


def get_db_path(root: Path) -> Path:
    """
    Return the SQLite database path for a repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to the ``index.db`` file under ``.codira``.
    """
    return get_codira_dir(root) / "index.db"


def get_metadata_path(root: Path) -> Path:
    """
    Return the metadata JSON path for a repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to the ``metadata.json`` file under ``.codira``.
    """
    return get_codira_dir(root) / "metadata.json"


def init_db(root: Path) -> None:
    """
    Create or refresh the codira database schema.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose ``.codira`` directory should be initialized.

    Returns
    -------
    None
        The schema and metadata files are created or refreshed under
        ``root / ".codira"``.
    """
    repo_dir = get_codira_dir(root)
    repo_dir.mkdir(parents=True, exist_ok=True)

    db_path = get_db_path(root)

    conn = sqlite3.connect(db_path)
    try:
        _refresh_files_schema(conn)
        _refresh_call_edges_schema(conn)
        _refresh_callable_refs_schema(conn)
        _refresh_call_records_schema(conn)
        _refresh_callable_ref_records_schema(conn)
        _refresh_docstring_issues_schema(conn)
        _refresh_overloads_schema(conn)
        _refresh_enum_members_schema(conn)
        _refresh_imports_schema(conn)
        _refresh_symbol_index_schema(conn)
        _refresh_embeddings_schema(conn)
        _refresh_index_runtime_schema(conn)
        _refresh_index_analyzers_schema(conn)
        for stmt in DDL:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()

    metadata_path = get_metadata_path(root)
    metadata = _read_metadata_file(metadata_path)
    metadata["schema_version"] = str(SCHEMA_VERSION)
    _write_metadata_file(metadata_path, metadata)
