"""SQLite backend-owned database path and bootstrap entrypoints.

Responsibilities
----------------
- Expose package-local database path resolution for the SQLite backend.
- Expose package-local schema bootstrap entrypoints used by the backend class.
- Isolate SQLite backend callers from direct imports of core storage helpers.

Design principles
-----------------
This module currently delegates to the stable core storage implementation so
runtime behavior stays unchanged while the package boundary becomes explicit.

Architectural role
------------------
This module belongs to the **SQLite backend plugin layer** and owns the
package-facing storage bootstrap seam for later migration work.
"""

from __future__ import annotations

from pathlib import Path

from codira.storage import get_db_path as _core_get_db_path
from codira.storage import init_db as _core_init_db

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
    return _core_get_db_path(root)


def init_db(root: Path) -> None:
    """
    Create or refresh the SQLite backend schema for one repository root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose backend schema should be initialized.

    Returns
    -------
    None
        The repository-local SQLite backend state is prepared in place.
    """
    _core_init_db(root)
