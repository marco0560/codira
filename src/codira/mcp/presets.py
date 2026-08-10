"""Generate local MCP client configurations for Codira's stdio server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import tomlkit

if TYPE_CHECKING:
    from collections.abc import Sequence


ClientPreset = Literal["claude-desktop", "codex", "cursor"]
_CLIENT_PRESETS: tuple[ClientPreset, ...] = ("claude-desktop", "codex", "cursor")


def build_client_configuration(client: ClientPreset, root: Path) -> str:
    """Build one deterministic client configuration for a trusted root.

    Parameters
    ----------
    client : {"claude-desktop", "codex", "cursor"}
        Client configuration format to generate.
    root : pathlib.Path
        Existing repository root passed to the stdio server at startup.

    Returns
    -------
    str
        Complete TOML or JSON configuration suitable for the selected client.

    Raises
    ------
    ValueError
        If ``client`` is unsupported or ``root`` is not a directory.
    """
    trusted_root = root.resolve()
    if not trusted_root.is_dir():
        msg = f"MCP repository root is not a directory: {trusted_root}"
        raise ValueError(msg)
    command = {"command": "codira-mcp", "args": ["--root", str(trusted_root)]}
    if client == "codex":
        return (
            "[mcp_servers.codira]\n"
            'command = "codira-mcp"\n'
            f'args = ["--root", "{trusted_root}"]\n'
        )
    if client in {"claude-desktop", "cursor"}:
        key = "mcpServers" if client == "claude-desktop" else "mcp"
        return json.dumps({key: {"codira": command}}, indent=2, sort_keys=True) + "\n"
    msg = f"unsupported MCP client preset: {client}"
    raise ValueError(msg)


def merge_client_configuration(client: ClientPreset, root: Path, existing: str) -> str:
    """Merge Codira's MCP entry while preserving unrelated client settings.

    Parameters
    ----------
    client : {"claude-desktop", "codex", "cursor"}
        Client configuration format to merge.
    root : pathlib.Path
        Trusted repository root for the server entry.
    existing : str
        Existing TOML or JSON configuration text.

    Returns
    -------
    str
        Deterministic merged configuration text.

    Raises
    ------
    json.JSONDecodeError
        If an existing JSON client configuration is invalid.
    tomlkit.exceptions.ParseError
        If an existing Codex TOML configuration is invalid.
    TypeError
        If the selected JSON MCP table is not an object.
    ValueError
        If the trusted repository root is not a directory.
    """
    trusted_root = root.resolve()
    if not trusted_root.is_dir():
        msg = f"MCP repository root is not a directory: {trusted_root}"
        raise ValueError(msg)
    command = {"command": "codira-mcp", "args": ["--root", str(trusted_root)]}
    if client == "codex":
        document = tomlkit.parse(existing) if existing.strip() else tomlkit.document()
        servers = document.get("mcp_servers")
        if servers is None:
            servers = tomlkit.table()
            document["mcp_servers"] = servers
        servers["codira"] = command
        return tomlkit.dumps(document)
    payload = json.loads(existing) if existing.strip() else {}
    key = "mcpServers" if client == "claude-desktop" else "mcp"
    servers = payload.setdefault(key, {})
    if not isinstance(servers, dict):
        msg = f"{key} must be a JSON object"
        raise TypeError(msg)
    servers["codira"] = command
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Write or print a generated local MCP client configuration.

    Parameters
    ----------
    argv : collections.abc.Sequence[str] | None, optional
        Command-line arguments excluding the executable name. ``None`` reads
        them from the process environment.

    Returns
    -------
    int
        Zero after writing a deterministic configuration.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", choices=_CLIENT_PRESETS)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        help="optional file to receive the generated configuration",
    )
    args = parser.parse_args(argv)
    configuration = build_client_configuration(args.client, args.root)
    if args.output is None:
        print(configuration, end="")
    else:
        args.output.write_text(configuration, encoding="utf-8")
    return 0
