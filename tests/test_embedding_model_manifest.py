"""Tests for embedding model manifest tooling."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts.embedding_model_manifest import (
    DEFAULT_MANIFEST,
    entry_by_id,
    load_manifest,
    render_config,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_default_embedding_model_manifest_covers_campaign_models() -> None:
    """
    Keep the model manifest aligned with the accepted campaign set.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the manifest covers the current and candidate models.
    """
    entries = load_manifest(DEFAULT_MANIFEST)

    models = {entry.model for entry in entries}
    engines = {entry.engine for entry in entries}

    assert {
        "sentence-transformers/all-MiniLM-L6-v2",
        "BAAI/bge-small-en-v1.5",
        "nomic-ai/nomic-embed-text-v1.5",
        "jinaai/jina-embeddings-v2-code-en",
    } <= models
    assert {"sentence-transformers", "onnx"} <= engines
    assert all(entry.dimension > 0 for entry in entries)


def test_embedding_model_manifest_renders_onnx_config() -> None:
    """
    Render an ONNX model entry as a repository config snippet.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts engine-specific plugin options are preserved.
    """
    entry = entry_by_id(load_manifest(DEFAULT_MANIFEST), "bge-small-en-v1.5-onnx")

    snippet = render_config(entry)

    assert 'engine = "onnx"' in snippet
    assert 'model = "BAAI/bge-small-en-v1.5"' in snippet
    assert "dimension = 384" in snippet
    assert 'model_path = ".codira/models/bge-small-en-v1.5/model.onnx"' in snippet
    assert (
        'tokenizer_path = ".codira/models/bge-small-en-v1.5/tokenizer.json"' in snippet
    )


def test_embedding_model_manifest_rejects_duplicate_ids(tmp_path: Path) -> None:
    """
    Reject ambiguous model identifiers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts duplicate IDs fail validation.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        """
        {
          "schema_version": 1,
          "models": [
            {
              "id": "duplicate",
              "engine": "sentence-transformers",
              "model": "demo/a",
              "version": "1",
              "dimension": 8,
              "precision": "float32",
              "config": {}
            },
            {
              "id": "duplicate",
              "engine": "onnx",
              "model": "demo/b",
              "version": "1",
              "dimension": 8,
              "precision": "float32",
              "config": {}
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate embedding model manifest id"):
        load_manifest(manifest)
