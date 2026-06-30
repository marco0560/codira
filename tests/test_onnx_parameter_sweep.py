"""Tests for ONNX parameter sweep helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts import run_onnx_parameter_sweep as onnx_sweep
from scripts.run_final_embedding_model_campaign import ModelEntry

if TYPE_CHECKING:
    from pathlib import Path


def _onnx_model() -> ModelEntry:
    """
    Build an ONNX model fixture.

    Parameters
    ----------
    None

    Returns
    -------
    scripts.run_final_embedding_model_campaign.ModelEntry
        ONNX model fixture.
    """

    return ModelEntry(
        id="demo-onnx",
        engine="onnx",
        model="demo/model",
        version="1",
        dimension=384,
        precision="float32",
        config={
            "model_path": ".codira/models/demo/model.onnx",
            "tokenizer_path": ".codira/models/demo/tokenizer.json",
            "provider": "CPUExecutionProvider",
        },
    )


def test_load_sweeps_reads_manifest(tmp_path: Path) -> None:
    """
    Read ONNX parameter sweeps from manifest JSON.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory.

    Returns
    -------
    None
        The test asserts sweep and variant fields are preserved.
    """

    manifest = tmp_path / "sweep.json"
    manifest.write_text(
        """
        {
          "schema_version": 1,
          "sweeps": [
            {
              "id": "demo",
              "model": "demo-onnx",
              "queries": ["schema"],
              "variants": [
                {
                  "id": "batch2",
                  "batch_size": 2,
                  "max_tokens": 256,
                  "intra_op_num_threads": 4,
                  "inter_op_num_threads": 1,
                  "max_text_chars": 2000
                }
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    sweeps = onnx_sweep.load_sweeps(manifest)

    assert sweeps == (
        onnx_sweep.OnnxSweep(
            sweep_id="demo",
            model_id="demo-onnx",
            queries=("schema",),
            variants=(
                onnx_sweep.OnnxVariant(
                    variant_id="batch2",
                    batch_size=2,
                    max_tokens=256,
                    intra_op_num_threads=4,
                    inter_op_num_threads=1,
                    max_text_chars=2000,
                ),
            ),
        ),
    )


def test_model_for_variant_applies_onnx_overrides() -> None:
    """
    Apply ONNX runtime knob overrides to a model entry.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts variant-specific config fields override the base
        manifest entry.
    """

    variant = onnx_sweep.OnnxVariant(
        variant_id="batch2",
        batch_size=2,
        max_tokens=256,
        intra_op_num_threads=4,
        inter_op_num_threads=1,
    )

    model = onnx_sweep.model_for_variant(_onnx_model(), variant)

    assert model.id == "demo-onnx-batch2"
    assert model.config["max_tokens"] == 256
    assert model.config["intra_op_num_threads"] == 4
    assert model.config["inter_op_num_threads"] == 1


def test_render_variant_config_includes_runtime_knobs() -> None:
    """
    Render a Codira config carrying ONNX sweep parameters.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts generated TOML exposes the selected ONNX knobs.
    """

    variant = onnx_sweep.OnnxVariant(
        variant_id="batch2",
        batch_size=2,
        max_tokens=256,
        intra_op_num_threads=4,
        inter_op_num_threads=1,
        max_text_chars=2000,
    )

    rendered = onnx_sweep.render_variant_config(_onnx_model(), variant, "sqlite")

    assert 'engine = "onnx"' in rendered
    assert 'vector_store = "sqlite"' in rendered
    assert "batch_size = 2" in rendered
    assert "max_tokens = 256" in rendered
    assert "intra_op_num_threads = 4" in rendered
    assert "inter_op_num_threads = 1" in rendered
    assert "max_text_chars = 2000" in rendered
