"""Package-local tests for the first-party SQLite backend distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_backend_sqlite import SQLiteIndexBackend, build_backend


def test_sqlite_backend_package_declares_expected_entry_point() -> None:
    """Keep package metadata aligned to the backend entry-point contract."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert project["project"]["entry-points"]["codira.backends"] == {
        "sqlite": "codira_backend_sqlite:build_backend"
    }


def test_sqlite_backend_package_builds_expected_backend() -> None:
    """Keep the package-local factory aligned to the published backend name."""
    backend = build_backend()

    assert isinstance(backend, SQLiteIndexBackend)
    assert backend.name == "sqlite"
