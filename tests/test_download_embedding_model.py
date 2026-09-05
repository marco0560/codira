"""Tests for the embedding model download helper."""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from scripts import download_embedding_model


def test_read_hf_token_reads_sops_scoped_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Read ``HF_TOKEN`` supplied by the SOPS-scoped child environment.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to supply the scoped environment variable.

    Returns
    -------
    None
        The test asserts the downloader does not source a plaintext token file.
    """
    monkeypatch.setenv("HF_TOKEN", "token-from-sops")

    assert download_embedding_model.read_hf_token() == "token-from-sops"


def test_read_hf_token_allows_anonymous_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Allow public model downloads without a configured Hugging Face token.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to remove the scoped environment variable.

    Returns
    -------
    None
        The test asserts missing credentials produce an anonymous request.
    """
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert download_embedding_model.read_hf_token() is None


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
    install_root = tmp_path / "models"
    manifest.write_text(
        json.dumps(
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
                            "model_path": str(install_root / "demo" / "model.onnx"),
                            "tokenizer_path": str(
                                install_root / "demo" / "tokenizer.json"
                            ),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HF_TOKEN", "secret-token")
    calls: list[tuple[str, str | None]] = []

    def fake_download_entry(
        entry: download_embedding_model.ModelEntry,
        token: str | None,
        install_root: Path,
    ) -> None:
        """
        Record one fake download request.

        Parameters
        ----------
        entry : scripts.download_embedding_model.ModelEntry
            Manifest entry being downloaded.
        token : str | None
            Sourced Hugging Face token, if configured.
        install_root : pathlib.Path
            Requested local artifact root.

        Returns
        -------
        None
            The fake records inputs only.
        """
        assert install_root == tmp_path / "models"
        calls.append((entry.model_id, token))

    def fake_smoke_test_entry(
        entry: download_embedding_model.ModelEntry,
        *,
        allow_remote_code: bool = False,
    ) -> None:
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
        assert not allow_remote_code
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
            "--install-root",
            str(install_root),
            "--sops-exec",
        ]
    )

    assert status == 0
    assert calls == [("candidate", "secret-token"), ("smoke:candidate", "")]


def test_download_embedding_model_main_allows_anonymous_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Pass no token to downloads when public credentials are absent.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace network and runtime operations.
    tmp_path : pathlib.Path
        Temporary directory for manifest and token inputs.

    Returns
    -------
    None
        The test asserts a public model can be downloaded anonymously.
    """
    manifest = tmp_path / "models.json"
    manifest.write_text(
        """
        {
          "schema_version": 1,
          "models": [{
            "id": "candidate", "engine": "onnx", "model": "demo/model",
            "version": "1", "dimension": 8, "precision": "float32",
            "config": {
              "model_path": ".codira/models/demo/model.onnx",
              "tokenizer_path": ".codira/models/demo/tokenizer.json"
            }
          }]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("HF_TOKEN", raising=False)
    calls: list[str | None] = []

    def fake_download_entry(
        entry: download_embedding_model.ModelEntry,
        token: str | None,
        install_root: Path,
    ) -> None:
        """
        Record the anonymous download token.

        Parameters
        ----------
        entry : scripts.download_embedding_model.ModelEntry
            Manifest entry being downloaded.
        token : str | None
            Optional Hugging Face access token.
        install_root : pathlib.Path
            Requested local artifact root.

        Returns
        -------
        None
            The fake records the optional token only.
        """
        del entry, install_root
        calls.append(token)

    def fake_smoke_test_entry(
        entry: download_embedding_model.ModelEntry,
        *,
        allow_remote_code: bool = False,
    ) -> None:
        """
        Accept the fake public model smoke test.

        Parameters
        ----------
        entry : scripts.download_embedding_model.ModelEntry
            Manifest entry being smoke-tested.

        Returns
        -------
        None
            The fake performs no runtime work.
        """
        del entry, allow_remote_code

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
            "--anonymous",
        ]
    )

    assert status == 0
    assert calls == [None]


def test_download_embedding_model_main_scopes_huggingface_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Re-execute authenticated downloads through the Hugging Face SOPS file.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the SOPS subprocess boundary.

    Returns
    -------
    None
        The test asserts the downloader itself does not receive ``HF_TOKEN``.
    """
    observed: dict[str, object] = {}

    def fake_run(
        command: tuple[str, ...], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """
        Record the scoped child command.

        Parameters
        ----------
        command : tuple[str, ...]
            Requested subprocess argument vector.
        _kwargs : object
            Ignored subprocess keyword arguments.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Controlled non-zero child result.
        """
        observed["command"] = command
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr("scripts.download_embedding_model.subprocess.run", fake_run)

    assert (
        download_embedding_model.main(
            ["--skip-smoke", "--model-id", "bge-small-en-v1.5-onnx"]
        )
        == 7
    )
    command = observed["command"]
    assert isinstance(command, tuple)
    assert command[:3] == (
        "sops",
        "exec-env",
        str(
            Path.home() / ".config" / "personal-secrets" / "secrets" / "huggingface.env"
        ),
    )
    assert "--sops-exec --skip-smoke --model-id bge-small-en-v1.5-onnx" in command[3]


def test_download_embedding_model_rejects_manifest_target_outside_install_root(
    tmp_path: Path,
) -> None:
    """
    Refuse ONNX artifact paths that escape the declared installation root.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used to construct containment boundaries.

    Returns
    -------
    None
        The test asserts an external manifest cannot direct an artifact write
        outside ``--install-root``.
    """
    entry = download_embedding_model.ModelEntry(
        model_id="unsafe",
        engine="onnx",
        model="demo/model",
        dimension=8,
        config={"model_path": str(tmp_path / "outside.onnx")},
    )

    with pytest.raises(ValueError, match="must be under"):
        download_embedding_model._artifact_target(
            entry,
            "model_path",
            tmp_path / "models",
        )


def test_download_embedding_model_requires_anonymous_remote_code_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Reject credentialed manifest-selected remote model code before re-exec.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to assert no credentialed subprocess is launched.
    tmp_path : pathlib.Path
        Temporary directory for the untrusted manifest.

    Returns
    -------
    None
        The test asserts remote code needs both explicit acknowledgement and
        anonymous execution.
    """
    manifest = tmp_path / "models.json"
    manifest.write_text(
        """
        {
          "schema_version": 1,
          "models": [{
            "id": "remote", "engine": "sentence-transformers",
            "model": "demo/model", "version": "1", "dimension": 8,
            "precision": "float32", "config": {"trust_remote_code": true}
          }]
        }
        """,
        encoding="utf-8",
    )

    def fail_if_credentialed(*_args: object, **_kwargs: object) -> None:
        """Fail if unsafe input reaches the credentialed child boundary."""
        msg = "credentialed child must not start"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "scripts.download_embedding_model.subprocess.run",
        fail_if_credentialed,
    )

    assert download_embedding_model.main(["--manifest", str(manifest)]) == 1


def test_download_embedding_model_rejects_unsupported_manifest_config(
    tmp_path: Path,
) -> None:
    """
    Reject manifest configuration that the downloader does not understand.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for the malformed manifest.

    Returns
    -------
    None
        The test asserts unreviewed configuration cannot change downloader
        behavior outside its defined schema.
    """
    manifest = tmp_path / "models.json"
    manifest.write_text(
        """
        {
          "schema_version": 1,
          "models": [{
            "id": "unexpected", "engine": "sentence-transformers",
            "model": "demo/model", "version": "1", "dimension": 8,
            "precision": "float32", "config": {"execute": true}
          }]
        }
        """,
        encoding="utf-8",
    )

    assert (
        download_embedding_model.main(["--manifest", str(manifest), "--anonymous"]) == 1
    )


def test_download_embedding_model_allows_acknowledged_anonymous_remote_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Permit reviewed remote model code only for an anonymous invocation.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace download and smoke-test operations.
    tmp_path : pathlib.Path
        Temporary directory for the reviewed manifest.

    Returns
    -------
    None
        The test asserts the opt-in reaches smoke testing without credentials.
    """
    manifest = tmp_path / "models.json"
    manifest.write_text(
        """
        {
          "schema_version": 1,
          "models": [{
            "id": "remote", "engine": "sentence-transformers",
            "model": "demo/model", "version": "1", "dimension": 8,
            "precision": "float32", "config": {"trust_remote_code": true}
          }]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("HF_TOKEN", "parent-token-must-not-be-forwarded")
    observed: list[object] = []

    def fake_download_entry(
        entry: download_embedding_model.ModelEntry,
        token: str | None,
        install_root: Path,
    ) -> None:
        """Record the anonymous download arguments."""
        del entry, install_root
        observed.append(token)

    def fake_smoke_test_entry(
        entry: download_embedding_model.ModelEntry,
        *,
        allow_remote_code: bool = False,
    ) -> None:
        """Record the explicit remote-code acknowledgement."""
        del entry
        observed.append(allow_remote_code)

    monkeypatch.setattr(download_embedding_model, "download_entry", fake_download_entry)
    monkeypatch.setattr(
        download_embedding_model, "smoke_test_entry", fake_smoke_test_entry
    )

    assert (
        download_embedding_model.main(
            [
                "--manifest",
                str(manifest),
                "--anonymous",
                "--allow-remote-code",
            ]
        )
        == 0
    )
    assert observed == [None, True]


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
        token: str | None,
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
