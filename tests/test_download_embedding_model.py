"""Tests for the embedding model download helper."""

from __future__ import annotations

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
