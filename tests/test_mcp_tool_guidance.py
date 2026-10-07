"""Validate first-page guidance and actionable MCP rejection behavior.

Parameters
----------
None

Returns
-------
None
    Definitions are consumed by the local MCP or qualification workflow.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from jsonschema import ValidationError  # type: ignore[import-untyped]

from codira.mcp.adapter import MCPAdapter
from codira.mcp.contract import CURSOR_GUIDANCE, PROFILE_GUIDANCE
from codira.mcp.server import create_server

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("arguments", "hint"),
    [
        ({"cursor": ""}, CURSOR_GUIDANCE),
        ({"search_profile": "."}, PROFILE_GUIDANCE),
    ],
)
def test_invalid_mcp_arguments_explain_first_page_correction(
    tmp_path: Path, arguments: dict[str, object], hint: str
) -> None:
    """Preserve strict rejection while exposing a usable correction.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated trusted repository.
    arguments : dict[str, object]
        Invalid optional arguments observed in the failed canary.
    hint : str
        Expected correction visible to the caller.

    Returns
    -------
    None
        Invalid inputs remain rejected by the advertised contract.
    """
    server = create_server(tmp_path)
    with pytest.raises(ValidationError) as error:
        asyncio.run(
            server.call_tool("context_for_task", {"query": "probe", **arguments})
        )
    assert hint in str(error.value)


def test_list_tools_publishes_first_page_guidance(tmp_path: Path) -> None:
    """Expose guidance through actual list-tools rather than discovery alone.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated trusted repository.

    Returns
    -------
    None
        Native clients receive nullable cursors and supported-profile guidance.
    """
    tools = asyncio.run(create_server(tmp_path).list_tools())
    context = next(tool for tool in tools if tool.name == "context_for_task")
    properties = context.inputSchema["properties"]
    assert properties["cursor"]["description"] == CURSOR_GUIDANCE
    assert properties["search_profile"]["description"] == PROFILE_GUIDANCE
    assert context.description is not None and "first page" in context.description


def test_invented_context_cursor_explains_correction(tmp_path: Path) -> None:
    """Reject path-like cursors with explicit first-page instructions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated trusted repository.

    Returns
    -------
    None
        Cursor semantics remain strict and their errors explain recovery.
    """
    with pytest.raises(ValueError, match="omit cursor or use null"):
        MCPAdapter(tmp_path).context_for_task("probe", cursor=".")
