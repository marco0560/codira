"""Tests for the embedding engine compatibility helper script."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts import compare_embedding_engines

if TYPE_CHECKING:
    from pathlib import Path


def _entry(
    model_id: str,
    *,
    engine: str = "onnx",
    model: str = "demo/model",
    dimension: int = 2,
) -> compare_embedding_engines.ModelEntry:
    """
    Build a small manifest entry fixture.

    Parameters
    ----------
    model_id : str
        Fixture model id.
    engine : str, optional
        Fixture engine name.
    model : str, optional
        Fixture model identity.
    dimension : int, optional
        Fixture vector dimension.

    Returns
    -------
    scripts.compare_embedding_engines.ModelEntry
        Manifest entry fixture.
    """

    return compare_embedding_engines.ModelEntry(
        model_id=model_id,
        engine=engine,
        model=model,
        version="1",
        dimension=dimension,
        precision="float32",
        config={},
    )


def test_load_manifest_entries_reads_model_metadata(tmp_path: Path) -> None:
    """
    Load model comparison metadata from a benchmark manifest.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used for the manifest.

    Returns
    -------
    None
        The test asserts manifest fields are preserved.
    """

    manifest = tmp_path / "models.json"
    manifest.write_text(
        """
        {
          "schema_version": 1,
          "models": [
            {
              "id": "candidate",
              "engine": "onnx",
              "model": "demo/model",
              "version": "2",
              "dimension": 3,
              "precision": "float32",
              "config": {"provider": "CPUExecutionProvider"}
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    entries = compare_embedding_engines.load_manifest_entries(manifest)

    assert entries["candidate"].engine == "onnx"
    assert entries["candidate"].model == "demo/model"
    assert entries["candidate"].version == "2"
    assert entries["candidate"].dimension == 3
    assert entries["candidate"].config == {"provider": "CPUExecutionProvider"}


def test_compare_vectors_accepts_matching_vectors() -> None:
    """
    Accept compatible vectors above the cosine threshold.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts matching identity and vectors pass.
    """

    result = compare_embedding_engines.compare_vectors(
        _entry("left"),
        _entry("right"),
        [[1.0, 0.0], [0.0, 1.0]],
        [[1.0, 0.0], [0.0, 1.0]],
        threshold=0.99,
    )

    assert result.passed is True
    assert result.dimensions_match is True
    assert result.identity_matches is True
    assert result.min_cosine == 1.0


def test_compare_vectors_rejects_identity_mismatch() -> None:
    """
    Reject vectors when model identity differs.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts vector similarity cannot override model mismatch.
    """

    result = compare_embedding_engines.compare_vectors(
        _entry("left", model="demo/a"),
        _entry("right", model="demo/b"),
        [[1.0, 0.0]],
        [[1.0, 0.0]],
        threshold=0.99,
    )

    assert result.passed is False
    assert result.identity_matches is False
    assert result.min_cosine == 1.0


def test_compare_vectors_rejects_low_similarity() -> None:
    """
    Reject matching identities when vector similarity is too low.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts cosine threshold enforcement.
    """

    result = compare_embedding_engines.compare_vectors(
        _entry("left"),
        _entry("right"),
        [[1.0, 0.0]],
        [[0.0, 1.0]],
        threshold=0.99,
    )

    assert result.passed is False
    assert result.identity_matches is True
    assert result.min_cosine == 0.0


def test_result_payload_is_json_compatible() -> None:
    """
    Render comparison results as JSON-compatible data.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts stable payload fields.
    """

    result = compare_embedding_engines.compare_vectors(
        _entry("left", engine="sentence-transformers"),
        _entry("right", engine="onnx"),
        [[1.0, 0.0]],
        [[1.0, 0.0]],
        threshold=0.99,
    )

    payload = compare_embedding_engines.result_payload(result)

    assert payload["left"]["id"] == "left"
    assert payload["left"]["engine"] == "sentence-transformers"
    assert payload["right"]["engine"] == "onnx"
    assert payload["passed"] is True
