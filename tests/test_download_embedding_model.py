"""Tests for the embedding model download helper."""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

from scripts import download_embedding_model

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_read_hf_token_sources_shell_file(tmp_path: Path) -> None:
    """
    Read ``HF_TOKEN`` by sourcing the configured shell file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used for a shell-style token file.

    Returns
    -------
    None
        The test asserts executable shell syntax is honored.
    """
    token_file = tmp_path / ".hf_token"
    token_file.write_text(
        """
        # test token file
        TOKEN_SUFFIX="from-shell"
        export HF_TOKEN="token-${TOKEN_SUFFIX}"
        """,
        encoding="utf-8",
    )

    assert download_embedding_model.read_hf_token(token_file) == "token-from-shell"


def test_download_embedding_model_main_selects_manifest_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Drive selected manifest entries through download and smoke hooks.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace network and runtime operations.
    tmp_path : pathlib.Path
        Temporary directory for manifest and token inputs.

    Returns
    -------
    None
        The test asserts ``main`` uses the sourced token and requested model id.
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
              "version": "1",
              "dimension": 8,
              "precision": "float32",
              "config": {
                "model_path": ".codira/models/demo/model.onnx",
                "tokenizer_path": ".codira/models/demo/tokenizer.json"
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    token_file = tmp_path / ".hf_token"
    token_file.write_text('export HF_TOKEN="secret-token"\n', encoding="utf-8")
    calls: list[tuple[str, str]] = []

    def fake_download_entry(
        entry: download_embedding_model.ModelEntry,
        token: str,
        install_root: Path,
    ) -> None:
        """
        Record one fake download request.

        Parameters
        ----------
        entry : scripts.download_embedding_model.ModelEntry
            Manifest entry being downloaded.
        token : str
            Sourced Hugging Face token.
        install_root : pathlib.Path
            Requested local artifact root.

        Returns
        -------
        None
            The fake records inputs only.
        """
        assert install_root == tmp_path / "models"
        calls.append((entry.model_id, token))

    def fake_smoke_test_entry(entry: download_embedding_model.ModelEntry) -> None:
        """
        Record one fake smoke test.

        Parameters
        ----------
        entry : scripts.download_embedding_model.ModelEntry
            Manifest entry being smoke-tested.

        Returns
        -------
        None
            The fake records inputs only.
        """
        calls.append((f"smoke:{entry.model_id}", ""))

    monkeypatch.setattr(download_embedding_model, "download_entry", fake_download_entry)
    monkeypatch.setattr(
        download_embedding_model,
        "smoke_test_entry",
        fake_smoke_test_entry,
    )

    status = download_embedding_model.main(
        [
            "--manifest",
            str(manifest),
            "--model-id",
            "candidate",
            "--token-file",
            str(token_file),
            "--install-root",
            str(tmp_path / "models"),
        ]
    )

    assert status == 0
    assert calls == [("candidate", "secret-token"), ("smoke:candidate", "")]


def test_download_onnx_entry_keeps_only_manifest_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Install ONNX artifacts without duplicating the upstream HF layout.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the Hugging Face download module.
    tmp_path : pathlib.Path
        Temporary artifact root.

    Returns
    -------
    None
        The test asserts the runtime directory contains only configured files.
    """

    install_root = tmp_path / "models"
    entry = download_embedding_model.ModelEntry(
        model_id="demo-onnx",
        engine="onnx",
        model="demo/model",
        dimension=8,
        config={
            "model_path": str(install_root / "demo" / "model.onnx"),
            "tokenizer_path": str(install_root / "demo" / "tokenizer.json"),
        },
    )
    calls: list[tuple[str, Path]] = []

    def fake_hf_hub_download(
        *,
        repo_id: str,
        filename: str,
        token: str,
        local_dir: Path,
    ) -> str:
        """
        Materialize one fake Hugging Face artifact.

        Parameters
        ----------
        repo_id : str
            Requested model repository.
        filename : str
            Requested artifact path inside the repository.
        token : str
            Hugging Face token.
        local_dir : pathlib.Path
            Download destination root.

        Returns
        -------
        str
            Path to the fake downloaded artifact.
        """

        assert repo_id == "demo/model"
        assert token == "secret-token"
        path = local_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"payload:{filename}".encode())
        calls.append((filename, local_dir))
        return str(path)

    fake_module = types.SimpleNamespace(hf_hub_download=fake_hf_hub_download)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_module)

    download_embedding_model.download_entry(entry, "secret-token", install_root)
    first_model_hash = download_embedding_model._file_sha256(
        install_root / "demo" / "model.onnx"
    )
    download_embedding_model.download_entry(entry, "secret-token", install_root)

    assert [filename for filename, _local_dir in calls] == [
        "onnx/model.onnx",
        "tokenizer.json",
        "onnx/model.onnx",
        "tokenizer.json",
    ]
    assert all(not local_dir.is_relative_to(install_root) for _name, local_dir in calls)
    assert (install_root / "demo" / "model.onnx").is_file()
    assert (install_root / "demo" / "tokenizer.json").is_file()
    assert not (install_root / "demo" / "onnx" / "model.onnx").exists()
    assert not (install_root / ".hf-downloads").exists()
    assert (
        download_embedding_model._file_sha256(install_root / "demo" / "model.onnx")
        == first_model_hash
    )
