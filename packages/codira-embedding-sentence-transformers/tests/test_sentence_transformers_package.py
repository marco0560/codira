"""Package-local tests for the first-party SentenceTransformers engine."""

from __future__ import annotations

import tomllib
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from codira.contracts import EmbeddingEngine
from codira_embedding_sentence_transformers import (
    SentenceTransformersEmbeddingEngine,
    build_engine,
)


def test_sentence_transformers_package_declares_expected_entry_point() -> None:
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

    assert project["project"]["version"] == "1.0.2"
    assert project["project"]["entry-points"]["codira.embedding_engines"] == {
        "sentence-transformers": "codira_embedding_sentence_transformers:build_engine"
    }


def test_sentence_transformers_package_builds_expected_engine() -> None:
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

    assert isinstance(engine, SentenceTransformersEmbeddingEngine)
    assert isinstance(engine, EmbeddingEngine)
    assert engine.name == "sentence-transformers"


def test_sentence_transformers_engine_exposes_configuration_schema() -> None:
    """
    Expose strict JSON Schema validation for plugin-specific options.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts ``trust_remote_code`` is schema-validated.
    """
    schema = SentenceTransformersEmbeddingEngine().configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)

    assert schema["additionalProperties"] is False
    assert properties["trust_remote_code"]["type"] == "boolean"

    validator = Draft202012Validator(schema)
    assert (
        list(validator.iter_errors({"enabled": True, "trust_remote_code": True})) == []
    )
    assert list(validator.iter_errors({"trust_remote_code": "true"}))
    assert list(validator.iter_errors({"typo": True}))
