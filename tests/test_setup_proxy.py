"""Tests for the optional installer provider boundary."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

from codira.cli import main
from codira.config import ConfigError, preview_config_update, update_config_file
from codira.mcp.presets import merge_client_configuration

if TYPE_CHECKING:
    from pathlib import Path


def test_setup_delegates_without_importing_textual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward setup arguments to the optional provider.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to install a provider double and command arguments.

    Returns
    -------
    None
    """
    provider = ModuleType("codira_installer.cli")
    received: list[str] = []

    def provider_main(arguments: list[str]) -> int:
        """Record provider arguments for the delegation assertion.

        Parameters
        ----------
        arguments : list[str]
            Arguments forwarded from the core command.

        Returns
        -------
        int
            Successful provider exit status.
        """
        received.extend(arguments)
        return 0

    provider.main = provider_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "codira_installer.cli", provider)
    monkeypatch.setattr(sys, "argv", ["codira", "setup", "--plan", "plan.json"])

    assert main() == 0
    assert received == ["--plan", "plan.json"]


def test_python_module_entrypoint_is_available() -> None:
    """Keep a module entry point next to the console-script entry point.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    module = importlib.import_module("codira.__main__")

    assert vars(module)["main"] is main


def test_setup_missing_provider_has_compatible_guidance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Report a stable remediation when no installer provider is installed.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to prevent importer discovery.
    capsys : pytest.CaptureFixture[str]
        Fixture used to inspect user-facing guidance.

    Returns
    -------
    None
    """

    def missing_provider(name: str) -> ModuleType:
        """Raise the provider-specific missing-module error.

        Parameters
        ----------
        name : str
            Requested provider module name.

        Returns
        -------
        types.ModuleType
            Never returned.

        Raises
        ------
        ModuleNotFoundError
            Always, for the installer provider.
        """
        error = ModuleNotFoundError()
        error.name = "codira_installer"
        raise error

    monkeypatch.setattr(importlib, "import_module", missing_provider)
    monkeypatch.setattr(sys, "argv", ["codira", "setup"])

    assert main() == 2
    assert "codira-installer" in capsys.readouterr().err


def test_config_preview_preserves_comments_and_invalid_write_is_safe(
    tmp_path: Path,
) -> None:
    """Preview a TOML merge without changing the original configuration.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary configuration directory.

    Returns
    -------
    None
    """
    path = tmp_path / "config.toml"
    original = '# keep me\n[backend]\nname = "sqlite"\n'
    path.write_text(original, encoding="utf-8")

    preview = preview_config_update(path, {"backend": {"name": "duckdb"}})

    assert "# keep me" in preview
    assert path.read_text(encoding="utf-8") == original
    result = update_config_file(path, {"backend": {"name": "duckdb"}})
    assert result.changed
    assert result.backup_path is not None
    assert result.backup_path.read_text(encoding="utf-8") == original
    assert "# keep me" in path.read_text(encoding="utf-8")
    assert not update_config_file(path, {"backend": {"name": "duckdb"}}).changed

    before_invalid = path.read_bytes()
    with pytest.raises(ConfigError):
        update_config_file(path, {"embeddings": {"batch_size": 0}})
    assert path.read_bytes() == before_invalid


def test_mcp_merges_preserve_unrelated_entries(tmp_path: Path) -> None:
    """Merge Codira without removing existing MCP clients.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary trusted repository root.

    Returns
    -------
    None
    """
    merged = merge_client_configuration(
        "claude-desktop",
        tmp_path,
        '{"mcpServers": {"other": {"command": "other"}}}\n',
    )

    assert '"other"' in merged
    assert '"codira"' in merged
    assert merge_client_configuration("claude-desktop", tmp_path, merged) == merged

    codex = merge_client_configuration(
        "codex", tmp_path, '[mcp_servers.other]\ncommand = "other"\n'
    )
    assert "[mcp_servers.other]" in codex
    assert merge_client_configuration("codex", tmp_path, codex) == codex
