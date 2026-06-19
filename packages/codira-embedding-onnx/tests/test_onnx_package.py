"""Package-local tests for the first-party ONNX embedding engine."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from codira.contracts import EmbeddingEngine, EmbeddingEngineError
from codira_embedding_onnx import OnnxEmbeddingEngine, build_engine


def test_onnx_package_declares_expected_entry_point() -> None:
    """
    Keep package metadata aligned to the embedding engine entry-point contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the package advertises the expected engine factory.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "1.0.0"
    assert project["project"]["entry-points"]["codira.embedding_engines"] == {
        "onnx": "codira_embedding_onnx:build_engine"
    }


def test_onnx_package_builds_expected_engine() -> None:
    """
    Keep the package-local factory aligned to the published engine name.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the factory returns the expected engine type and name.
    """
    engine = build_engine()

    assert isinstance(engine, OnnxEmbeddingEngine)
    assert isinstance(engine, EmbeddingEngine)
    assert engine.name == "onnx"


def test_onnx_engine_requires_explicit_artifact_paths() -> None:
    """
    Reject native ONNX runtime use without explicit local artifacts.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts hidden downloads are not attempted.
    """
    engine = OnnxEmbeddingEngine()

    with pytest.raises(EmbeddingEngineError, match="model_path"):
        engine.provision({})
