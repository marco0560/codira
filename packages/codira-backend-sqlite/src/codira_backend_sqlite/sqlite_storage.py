"""SQLite backend-owned database path and schema bootstrap entrypoints.

Responsibilities
----------------
- Resolve package-local SQLite database paths for repository indexes.
- Initialize the SQLite schema using the shared codira DDL.

Design principles
-----------------
SQLite storage stays package-owned so codira-core remains backend-neutral.

Architectural role
------------------
This module belongs to the **SQLite backend plugin layer** and owns SQLite
physical storage bootstrap.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from codira.schema import DDL, SCHEMA_VERSION
from codira.storage import (
    _read_metadata_file,
    _write_metadata_file,
    get_codira_dir,
    get_metadata_path,
)

__all__ = ["get_db_path", "init_db"]


def get_db_path(root: Path) -> Path:
    """
    Return the SQLite database path for one repository root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose backend database path should be resolved.

    Returns
    -------
    pathlib.Path
        Path to the SQLite backend database file.
    """
    return get_codira_dir(root) / "index.db"


def _database_has_current_schema(db_path: Path) -> bool:
    """
    Return whether an existing SQLite database exposes current schema columns.

    Parameters
    ----------
    db_path : pathlib.Path
        Existing SQLite database path.

    Returns
    -------
    bool
        ``True`` when required relation columns and documentation tables are
        present.
    """
    conn = sqlite3.connect(db_path)
    try:
        table_columns = {
            table_name: {
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info('{table_name}')")
            }
            for table_name in (
                "call_edges",
                "callable_refs",
                "call_records",
                "callable_ref_records",
                "documentation_artifacts",
            )
        }
    finally:
        conn.close()

    required_relation_columns = {"external_target_kind", "external_target_name"}
    return all(
        required_relation_columns.issubset(table_columns[table_name])
        for table_name in (
            "call_edges",
            "callable_refs",
            "call_records",
            "callable_ref_records",
        )
    ) and {
        "stable_id",
        "kind",
        "source_format",
        "heading_path",
        "text",
        "owner_kind",
        "attachment_confidence",
    }.issubset(table_columns["documentation_artifacts"])


def init_db(root: Path) -> None:
    """
    Create the SQLite backend schema for one repository root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose backend schema should be initialized.

    Returns
    -------
    None
        The repository-local SQLite backend state is prepared in place. Existing
        databases with mismatched schema metadata are discarded and rebuilt.
    """
    repo_dir = get_codira_dir(root)
    repo_dir.mkdir(parents=True, exist_ok=True)

    db_path = get_db_path(root)
    metadata_path = get_metadata_path(root)
    metadata = _read_metadata_file(metadata_path)
    if db_path.exists() and (
        metadata.get("schema_version") != str(SCHEMA_VERSION)
        or not _database_has_current_schema(db_path)
    ):
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        for stmt in DDL:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()

    metadata["schema_version"] = str(SCHEMA_VERSION)
    _write_metadata_file(metadata_path, metadata)
