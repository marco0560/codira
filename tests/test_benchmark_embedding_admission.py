"""Verify model admission without corpus measurements or native model downloads.

Parameters
----------
None

Returns
-------
None
    Probe processes are simulated; native readiness has separate retained evidence.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, TextIO
from unittest.mock import Mock

import pytest

from scripts import (
    benchmark_embedding_readiness as probe,
    run_test_material_benchmarks as runner,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any


@pytest.mark.parametrize("ready", [True, False])
def test_admission_deduplicates_models_and_retains_failed_prerequisites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready: bool
) -> None:
    """Verify once across backends and block unavailable models before indexing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned manifest, configurations and admission receipts.
    monkeypatch : pytest.MonkeyPatch
        Simulates child output without loading models or repositories.
    ready : bool
        Native probe outcome to simulate.

    Returns
    -------
    None
        Admission is separate from performance ordinals and stage measurements.
    """
    config = tmp_path / "model.toml"
    config.write_text(
        '[embeddings]\nenabled = true\nengine = "sentence-transformers"\nmodel = "fixture"\ndimension = 2\n'
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "temporary_root": str(tmp_path),
                "profiles": [
                    {"id": "sqlite", "embeddings": True},
                    {"id": "duckdb", "embeddings": True},
                ],
                "repositories": [
                    {
                        "path": str(tmp_path),
                        "label": "fixture",
                        "configs": {"sqlite": "model.toml", "duckdb": "model.toml"},
                    }
                ],
            }
        )
    )
    campaign = runner.Campaign(manifest, tmp_path / "run", False)
    calls: list[list[str]] = []

    def launch(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        """Supply an explicit model prerequisite result and raw child streams.

        Parameters
        ----------
        argv : list[str]
            Exact probe command.
        **kwargs : object
            Native subprocess boundary including files and isolated environment.

        Returns
        -------
        types.SimpleNamespace
            Minimal waiting child.
        """
        calls.append(argv)
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        output: TextIO = kwargs["stdout"]
        output.write(
            json.dumps(
                {
                    "status": "ready" if ready else "unavailable",
                    "engine": "sentence-transformers",
                    "dimension": 2,
                    "logical_model": "fixture",
                    "assets": [{"path": str(config), "sha256": "a" * 64}],
                    "reason": "missing fixture weights",
                }
            )
        )
        output.flush()
        return SimpleNamespace(wait=Mock(return_value=0 if ready else 1))

    monkeypatch.setattr(subprocess, "Popen", launch)
    if ready:
        result = runner.embedding_admission(campaign, 300)
        assert len(result) == 1
        assert result[0]["readiness"]["dimension"] == 2
    else:
        with pytest.raises(ValueError, match="No repository measurements started"):
            runner.embedding_admission(campaign, 300)
    assert len(calls) == 1
    assert campaign.results == []
    assert campaign.progress.completed == 0
    assert not (campaign.root / "stages").exists()
    receipts = list((campaign.root / "admission").rglob("result.json"))
    assert len(receipts) == 1
    retained = json.loads(receipts[0].read_text())
    assert retained["exit_code"] == (0 if ready else 1)
    assert retained["response"]["status"] == ("ready" if ready else "unavailable")


def test_model_bytes_are_part_of_resume_identity(tmp_path: Path) -> None:
    """Reject changed asset digests without changing the original identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned identity receipt.

    Returns
    -------
    None
        Matching controls allow preflight but changed assets reject resume.
    """
    receipt = tmp_path / "identity.json"
    old = {"controls": "same", "model_assets": [{"sha256": "old"}]}
    runner.write(receipt, old)
    runner.guard_resume_identity(receipt, {"controls": "same"}, before_admission=True)
    with pytest.raises(ValueError, match="resume identity differs"):
        runner.guard_resume_identity(
            receipt, {"controls": "same", "model_assets": [{"sha256": "new"}]}
        )
    assert json.loads(receipt.read_text()) == old


def test_probe_rejects_nonfinite_vectors_and_changing_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent invalid or unstable native results from becoming admission success.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned artifact file.
    monkeypatch : pytest.MonkeyPatch
        Replaces only model boundaries and effective configuration.

    Returns
    -------
    None
        Both vector validity and source immutability are required.
    """
    artifact = tmp_path / "weights.bin"
    artifact.write_bytes(b"original")
    monkeypatch.setattr(
        probe,
        "load_effective_config",
        lambda **kwargs: SimpleNamespace(
            embeddings=SimpleNamespace(enabled=True, engine="sentence-transformers")
        ),
    )
    monkeypatch.setattr(
        probe, "selected_artifacts", lambda root: ([artifact], "revision")
    )
    monkeypatch.setattr(
        probe,
        "get_embedding_backend",
        lambda **kwargs: SimpleNamespace(name="fixture", version="1", dim=2),
    )
    monkeypatch.setattr(
        probe, "embed_texts", lambda *args, **kwargs: [[float("nan"), 1.0]]
    )
    with pytest.raises(ValueError, match="non-finite"):
        probe.check_readiness(tmp_path)

    def mutate(*args: object, **kwargs: object) -> list[list[float]]:
        """Change a fixture artifact during an otherwise valid encoding.

        Parameters
        ----------
        *args : object
            Fixed input text ignored by this fixture.
        **kwargs : object
            Context ignored by this fixture.

        Returns
        -------
        list[list[float]]
            Dimension-correct finite vector.
        """
        artifact.write_bytes(b"changed")
        return [[1.0, 0.0]]

    monkeypatch.setattr(probe, "embed_texts", mutate)
    with pytest.raises(ValueError, match="changed during readiness"):
        probe.check_readiness(tmp_path)


def test_onnx_export_cannot_satisfy_sentence_transformers_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject an ONNX-only directory for a Torch-backed model profile.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned incomplete exported model directory.
    monkeypatch : pytest.MonkeyPatch
        Selects the ST engine and that exact local source.

    Returns
    -------
    None
        Engine-specific prerequisites are verified before encoding.
    """
    (tmp_path / "model.onnx").write_bytes(b"export")
    (tmp_path / "tokenizer.json").write_text("{}")
    monkeypatch.setattr(
        probe,
        "load_effective_config",
        lambda **kwargs: SimpleNamespace(
            embeddings=SimpleNamespace(engine="sentence-transformers")
        ),
    )
    monkeypatch.setattr(
        probe, "_sentence_transformer_location", lambda root: (str(tmp_path), tmp_path)
    )
    with pytest.raises(ValueError, match="checkpoint"):
        probe.selected_artifacts(tmp_path)


def test_missing_onnx_artifact_prevents_native_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain a missing required file as unavailability rather than a measurement.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned missing graph location.
    monkeypatch : pytest.MonkeyPatch
        Selects exact artifacts and spies on model invocation.

    Returns
    -------
    None
        Missing artifacts fail before an encoder can be invoked.
    """
    monkeypatch.setattr(
        probe,
        "load_effective_config",
        lambda **kwargs: SimpleNamespace(
            embeddings=SimpleNamespace(enabled=True, engine="onnx")
        ),
    )
    monkeypatch.setattr(
        probe, "selected_artifacts", lambda root: ([tmp_path / "missing.onnx"], None)
    )
    encode = Mock()
    monkeypatch.setattr(probe, "embed_texts", encode)
    with pytest.raises(FileNotFoundError):
        probe.check_readiness(tmp_path)
    encode.assert_not_called()


@pytest.mark.parametrize("dimension", [None, True, 0, 3])
def test_ready_enum_alone_cannot_admit_invalid_model(
    tmp_path: Path, dimension: object
) -> None:
    """Require matching dimensions and real asset provenance, not a status label.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned artifact path used in the simulated receipt.
    dimension : object
        Invalid dimension or mismatch against configured dimensions.

    Returns
    -------
    None
        Native readiness output-contract failures remain unavailable.
    """
    settings = {"embeddings": {"engine": "onnx", "model": "fixture", "dimension": 2}}
    result = {
        "status": "ready",
        "engine": "onnx",
        "logical_model": "fixture",
        "dimension": dimension,
        "assets": [{"path": str(tmp_path / "model.onnx"), "sha256": "a" * 64}],
    }
    assert not runner.valid_model_readiness(result, settings)
