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

    assert project["project"]["version"] == "1.52.5"
    assert project["project"]["dependencies"] == [
        "codira[semantic]>=1.42.0,<2.0.0",
        "einops>=0.8,<1.0",
        "codira-analyzer-python==1.43.0",
        "codira-analyzer-json==1.41.0",
        "codira-analyzer-c==1.43.0",
        "codira-analyzer-cpp==1.44.0",
        "codira-analyzer-bash==1.41.0",
        "codira-analyzer-markdown==1.44.0",
        "codira-analyzer-text==1.43.0",
        "codira-backend-sqlite==1.45.0",
        "codira-backend-duckdb==1.49.3",
        "codira-embedding-sentence-transformers==1.0.1",
        "codira-embedding-onnx==1.0.1",
        "codira-vector-store-sqlite==1.0.1",
        "codira-vector-store-duckdb==1.0.3",
    ]
