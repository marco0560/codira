"""Retain native acceleration and MCP logs without misclassifying INFO.

Parameters
----------
None

Returns
-------
None
    Transport tests simulate the SDK; they do not launch corpus processes.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, TextIO
from unittest.mock import AsyncMock

import mcp
import mcp.client.stdio
import pytest

from scripts import run_test_material_benchmarks as runner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.mark.parametrize("tool_error", [False, True, "timeout"])
def test_mcp_stderr_is_retained_and_tool_errors_remain_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tool_error: bool | str,
) -> None:
    """Capture routine SDK logs while preserving explicit tool-error evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned fixture manifest and receipts.
    monkeypatch : pytest.MonkeyPatch
        Replaces SDK transport and session with deterministic test boundaries.
    capsys : pytest.CaptureFixture[str]
        Captures terminal output.
    tool_error : bool or str
        Actual simulated MCP error flag rather than a log substring.

    Returns
    -------
    None
        Raw logs survive and successful fallback prose is not a command failure.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    campaign = runner.Campaign(manifest, tmp_path / "run", False)
    campaign.progress = runner.StageProgress(
        {"primary/fixture/mcp", "primary/fixture/mcp/cli-evidence"},
        campaign.root,
        False,
    )
    campaign.member_coverage["fixture"] = {
        "usable": True,
        "partial": False,
        "complete": False,
    }

    @asynccontextmanager
    async def transport(
        server: object, *, errlog: TextIO
    ) -> AsyncIterator[tuple[None, None]]:
        """Retain fake routine stderr without launching an SDK child.

        Parameters
        ----------
        server : object
            Unused launch descriptor.
        errlog : typing.TextIO
            Runner-owned raw stderr file.

        Returns
        -------
        collections.abc.AsyncIterator[tuple[None, None]]
            Simulated read/write streams.
        """
        errlog.write(
            "INFO Loading faiss; optional module unavailable; successfully loaded faiss\n"
        )
        yield None, None

    @asynccontextmanager
    async def session(
        *args: object, **kwargs: object
    ) -> AsyncIterator[SimpleNamespace]:
        """Supply a minimal deterministic tool session.

        Parameters
        ----------
        *args : object
            Unused stream descriptors.
        **kwargs : object
            Unused timeout options.

        Returns
        -------
        collections.abc.AsyncIterator[types.SimpleNamespace]
            Minimal simulated initialized SDK session.
        """
        yield SimpleNamespace(
            initialize=AsyncMock(),
            list_tools=AsyncMock(
                return_value=SimpleNamespace(
                    tools=[SimpleNamespace(name="capabilities")]
                )
            ),
            call_tool=AsyncMock(
                side_effect=ExceptionGroup(
                    "transport", [TimeoutError("request deadline")]
                )
                if tool_error == "timeout"
                else None,
                return_value=SimpleNamespace(
                    isError=tool_error,
                    structuredContent={"result": {"error": "simulated"}},
                ),
            ),
        )

    monkeypatch.setattr(mcp.client.stdio, "stdio_client", transport)
    monkeypatch.setattr(mcp, "ClientSession", session)
    result = asyncio.run(
        campaign.mcp("primary/fixture/mcp", ["--workspace", "fixture"], "query")
    )
    assert result["status"] == ("failed" if tool_error else "partial")
    if tool_error == "timeout":
        assert result["failed_tool"] == "capabilities"
        assert "TimeoutError: request deadline" in Path(result["exception"]).read_text()
        assert result["seconds"] >= 0

    assert "successfully loaded faiss" in Path(result["stderr"]).read_text()
    terminal = capsys.readouterr()
    assert "Loading faiss" not in terminal.err
    lines = terminal.out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[skip; 1; ")
    assert "primary/fixture/mcp/cli-evidence excluded:" in lines[0]
    assert ("MCP probe failed" if tool_error else "no MCP symbol identity") in lines[0]
    assert lines[1].startswith("[1; 0; ")
    assert campaign.progress.completed == 1
    assert not (
        campaign.root / "stages/primary/fixture/mcp/cli-evidence/result.json"
    ).exists()
    resumed = asyncio.run(
        campaign.mcp("primary/fixture/mcp", ["--workspace", "fixture"], "query")
    )
    assert resumed == result
    assert capsys.readouterr().out == ""
    if tool_error is True:
        assert result["reason"] == "MCP tool errors: capabilities"
        assert result["responses"][0]["is_error"]
    elif tool_error is False:
        assert result["comparison_group"] == "partial_coverage"
