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
        databases are expected to already match the current development schema.
    """
    repo_dir = get_codira_dir(root)
    repo_dir.mkdir(parents=True, exist_ok=True)

    db_path = get_db_path(root)

    conn = sqlite3.connect(db_path)
    try:
        for stmt in DDL:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()

    metadata_path = get_metadata_path(root)
    metadata = _read_metadata_file(metadata_path)
    metadata["schema_version"] = str(SCHEMA_VERSION)
    _write_metadata_file(metadata_path, metadata)
