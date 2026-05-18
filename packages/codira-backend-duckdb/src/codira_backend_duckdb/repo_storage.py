"""DuckDB backend-owned repository storage path entrypoints.

Responsibilities
----------------
- Expose package-local `.codira` directory resolution for the DuckDB backend.
- Expose package-local metadata path resolution used by the production backend.
- Isolate the DuckDB package root from direct imports of core storage helpers.

Design principles
-----------------
This module currently delegates to stable core storage helpers so operator
behavior stays unchanged while the package boundary becomes explicit.

Architectural role
------------------
This module belongs to the **DuckDB backend plugin layer** and owns the
package-local repository-storage seam for backend metadata and path handling.
"""

from __future__ import annotations

from pathlib import Path

from codira.storage import get_codira_dir as _core_get_codira_dir
from codira.storage import get_metadata_path as _core_get_metadata_path

__all__ = ["get_codira_dir", "get_metadata_path"]


def get_codira_dir(root: Path) -> Path:
    """
    Return the repository-local `.codira` directory for one root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose backend storage directory should be resolved.

    Returns
    -------
    pathlib.Path
        Effective `.codira` directory for the repository root.
    """
    return _core_get_codira_dir(root)


def get_metadata_path(root: Path) -> Path:
    """
    Return the repository-local metadata path for one root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose backend metadata path should be resolved.

    Returns
    -------
    pathlib.Path
        Effective metadata JSON path for the repository root.
    """
    return _core_get_metadata_path(root)
