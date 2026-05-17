"""SQLite-storage compatibility entrypoints localized for the DuckDB package.

Responsibilities
----------------
- Expose package-local SQLite database path resolution for compatibility code.
- Expose package-local SQLite schema bootstrap entrypoints used by the
  localized DuckDB compatibility backend.
- Isolate DuckDB compatibility callers from direct imports of core storage
  helpers.

Design principles
-----------------
This module currently delegates to the stable core storage implementation so
the DuckDB compatibility layer keeps behavior unchanged while import
boundaries become package-local.

Architectural role
------------------
This module belongs to the **DuckDB backend plugin layer** and owns the
package-local SQLite compatibility bootstrap seam.
"""

from __future__ import annotations

from pathlib import Path

from codira.storage import get_db_path as _core_get_db_path
from codira.storage import init_db as _core_init_db

__all__ = ["get_db_path", "init_db"]


def get_db_path(root: Path) -> Path:
    """
    Return the compatibility SQLite database path for one repository root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose compatibility database path should be resolved.

    Returns
    -------
    pathlib.Path
        Path to the compatibility SQLite database file.
    """
    return _core_get_db_path(root)


def init_db(root: Path) -> None:
    """
    Create or refresh the compatibility SQLite schema for one repository root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose compatibility schema should be initialized.

    Returns
    -------
    None
        The repository-local compatibility SQLite state is prepared in place.
    """
    _core_init_db(root)
