"""Tests for embedding engine matrix planning."""

from __future__ import annotations

import json
import subprocess
import sys

from scripts.embedding_engine_matrix_plan import DEFAULT_MATRIX, build_matrix_plan


def test_embedding_engine_matrix_plan_combines_manifests() -> None:
    """
    Build a deterministic matrix plan from committed manifests.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts every model entry becomes one planned run.
    """
    plan = build_matrix_plan(matrix_manifest=DEFAULT_MATRIX)

    runs = plan["runs"]

    assert plan["schema_version"] == 1
    assert isinstance(runs, list)
    assert len(runs) == 6
    assert {row["engine"] for row in runs} == {"sentence-transformers", "onnx"}
    assert any(row["model_id"] == "bge-small-en-v1.5-onnx" for row in runs)
    assert not any(
        row["model_id"] == "jina-embeddings-v2-base-code-sentence-transformers"
        for row in runs
    )
    assert all("[embeddings]" in row["config_toml"] for row in runs)


def test_embedding_engine_matrix_plan_cli_outputs_json() -> None:
    """
    Keep the matrix-plan CLI machine-readable.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the CLI prints JSON with planned runs.
    """
    result = subprocess.run(
        [sys.executable, "scripts/embedding_engine_matrix_plan.py"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)

    assert payload["schema_version"] == 1
    assert len(payload["runs"]) == 6
