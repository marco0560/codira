"""Protocol-harness tests for generated local MCP client configurations."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

import pytest

from codira.mcp.contract import MCP_CONTRACT_VERSION
from codira.mcp.presets import (
    ClientPreset,
    build_client_configuration,
    merge_client_configuration,
)
from codira.mcp.server import create_server

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("client", ["claude-desktop", "codex", "cursor"])
def test_generated_client_profile_reaches_mcp_server(
    tmp_path: Path, client: ClientPreset
) -> None:
    """Assert every generated profile starts the same local protocol server.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided repository root for the generated configuration.
    client : str
        Supported client profile rendered by the configuration generator.

    Returns
    -------
    None
        The test asserts generated startup arguments and a protocol tool call.
    """
    configuration = build_client_configuration(client, tmp_path)
    if client == "codex":
        assert 'command = "codira-mcp"' in configuration
        assert f'args = ["--root", "{tmp_path}"]' in configuration
    else:
        payload = json.loads(configuration)
        server_key = "mcpServers" if client == "claude-desktop" else "mcp"
        assert payload[server_key]["codira"] == {
            "args": ["--root", str(tmp_path)],
            "command": "codira-mcp",
        }

    _, structured = cast(
        "tuple[object, dict[str, object]]",
        asyncio.run(create_server(tmp_path).call_tool("capabilities", {})),
    )
    assert structured["contract_version"] == MCP_CONTRACT_VERSION


@pytest.mark.parametrize("client", ["claude-desktop", "codex", "cursor"])
def test_generated_workspace_profile_preserves_fixed_workspace_startup(
    client: ClientPreset,
) -> None:
    """Render workspace startup without falling back to a repository path.

    Parameters
    ----------
    client : str
        Supported client profile rendered by the configuration generator.

    Returns
    -------
    None
        The test asserts every client receives one fixed workspace selector.
    """
    configuration = build_client_configuration(client, workspace="sample")
    if client == "codex":
        assert 'args = ["--workspace", "sample"]' in configuration
    else:
        payload = json.loads(configuration)
        server_key = "mcpServers" if client == "claude-desktop" else "mcp"
        assert payload[server_key]["codira"]["args"] == ["--workspace", "sample"]


def test_workspace_presets_reject_ambiguous_startup_and_merge_cleanly(
    tmp_path: Path,
) -> None:
    """Keep workspace presets mutually exclusive with legacy root selection.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Existing temporary repository root used for ambiguity validation.

    Returns
    -------
    None
        The test asserts merge preserves unrelated client configuration.
    """
    with pytest.raises(ValueError, match="cannot be combined"):
        build_client_configuration("codex", tmp_path, workspace="sample")

    merged = merge_client_configuration(
        "cursor",
        None,
        '{"other": true}',
        workspace="sample",
    )

    assert json.loads(merged) == {
        "mcp": {"codira": {"args": ["--workspace", "sample"], "command": "codira-mcp"}},
        "other": True,
    }
