"""Tests for the standalone demo backend package metadata.

Responsibilities
----------------
- Keep the documented third-party backend example installable without ambient
  development dependencies.

Design principles
-----------------
Example plugin metadata must declare every distribution imported by its entry
point implementation.

Architectural role
------------------
This module guards the package boundary of the demo backend distribution.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_BACKEND_PYPROJECT = (
    REPO_ROOT / "examples" / "plugins" / "codira_demo_backend" / "pyproject.toml"
)


def test_demo_backend_example_declares_its_sqlite_backend_dependency() -> None:
    """Require the demo backend package to install its imported SQLite backend.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the standalone package metadata supplies the direct
        distribution imported by its entry-point implementation.
    """
    with DEMO_BACKEND_PYPROJECT.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    dependencies = pyproject["project"]["dependencies"]

    assert "codira-backend-sqlite>=2.0.0,<3.0.0" in dependencies
