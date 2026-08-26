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

    assert project["project"]["version"] == "2.0.0"
    assert project["project"]["dependencies"] == [
        "codira[semantic]==2.0.0",
        "einops>=0.8,<1.0",
        "codira-analyzer-python==2.0.0",
        "codira-analyzer-json==2.0.0",
        "codira-analyzer-c==2.0.0",
        "codira-analyzer-cpp==2.0.0",
        "codira-analyzer-rust==2.0.0",
        "codira-analyzer-javascript==2.0.0",
        "codira-analyzer-typescript==2.0.0",
        "codira-analyzer-go==2.0.0",
        "codira-analyzer-bash==2.0.0",
        "codira-analyzer-markdown==2.0.0",
        "codira-analyzer-text==2.0.0",
        "codira-documentation-audit-numpy==2.0.0",
        "codira-documentation-audit-google==2.0.0",
        "codira-documentation-audit-doxygen==2.0.0",
        "codira-documentation-audit-rustdoc==2.0.0",
        "codira-documentation-audit-jsdoc==2.0.0",
        "codira-documentation-audit-tsdoc==2.0.0",
        "codira-documentation-audit-go-doc-comments==2.0.0",
        "codira-backend-sqlite==2.0.0",
        "codira-backend-duckdb==2.0.0",
        "codira-embedding-sentence-transformers==2.0.0",
        "codira-embedding-onnx==2.0.0",
        "codira-vector-store-sqlite==2.0.0",
        "codira-vector-store-duckdb==2.0.0",
        "codira-similarity-index-qdrant==2.0.0",
        "codira-installer==2.0.0",
    ]
    assert project["project"]["optional-dependencies"]["faiss"] == [
        "codira-similarity-index-faiss==2.0.0"
    ]
