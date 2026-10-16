"""Verify explicit benchmark configuration selection before model admission.

Parameters
----------
None

Returns
-------
None
    Regression coverage for the native readiness command's config boundary.
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from codira.config import load_effective_config
from scripts import benchmark_embedding_readiness as READINESS


def test_readiness_uses_explicit_configuration_before_loading_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Honor the requested profile and restore normal repository configuration.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Independent corpus and campaign configuration paths.
    monkeypatch : pytest.MonkeyPatch
        Prevents a wrong profile from reaching native asset loading.
    capsys : pytest.CaptureFixture[str]
        Captures the terminal admission receipt.

    Returns
    -------
    None
        Disabled explicit profiles fail before any model probe is attempted.
    """
    root = tmp_path / "corpus"
    (root / ".codira").mkdir(parents=True)
    (root / ".codira/config.toml").write_text(
        'config_version = 2\n[embeddings]\nenabled = true\nsimilarity_index = "exact"\n'
    )
    requested = tmp_path / "requested.toml"
    requested.write_text(
        'config_version = 2\n[embeddings]\nenabled = false\nsimilarity_index = "exact"\n'
    )
    assets = Mock(side_effect=AssertionError("Wrong profile reached model loading"))
    monkeypatch.setattr(READINESS, "selected_artifacts", assets)
    for name in ("CODIRA_CONFIG_FILE", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.setenv(name, "")

    assert READINESS.main([str(requested), "--root", str(root)]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == (
        "Selected embedding profile has embeddings disabled."
    )
    assets.assert_not_called()
    assert load_effective_config(root=root).embeddings.enabled
