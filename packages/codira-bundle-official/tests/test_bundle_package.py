"""Package-local tests for the first-party bundle distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_bundle_package_declares_expected_first_party_dependencies() -> None:
    """
    Keep bundle metadata aligned to the curated first-party package set.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the bundle dependencies match the official package set.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "1.5.5"
    assert project["project"]["dependencies"] == [
        "codira[semantic]>=1.5.0,<2.0.0",
        "codira-analyzer-python==1.5.2",
        "codira-analyzer-json==1.5.0",
        "codira-analyzer-c==1.5.2",
        "codira-analyzer-bash==1.5.0",
        "codira-backend-sqlite==1.5.2",
    ]
