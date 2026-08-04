"""Tests for the initial local read-only MCP server adapter."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

import pytest

from codira.indexer import index_repo
from codira.mcp.adapter import MCPAdapter
from codira.mcp.contract import MCP_CONTRACT_VERSION
from codira.mcp.server import create_server
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from pathlib import Path


def _indexed_repository(root: Path) -> None:
    """Create and index a minimal repository for direct MCP query tests.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root to populate and index.

    Returns
    -------
    None
        The repository is prepared in place.
    """
    (root / "sample.py").write_text(
        "def helper() -> int:\n    return 42\n\n\ndef answer() -> int:\n    return helper()\n",
        encoding="utf-8",
    )
    active_index_backend().initialize(root)
    index_repo(root)


def test_adapter_returns_direct_core_symbol_result(tmp_path: Path) -> None:
    """Assert the symbol tool returns a normalized direct-core result.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided temporary repository root.

    Returns
    -------
    None
        The test asserts the MCP envelope and structural payload.
    """
    _indexed_repository(tmp_path)

    result = MCPAdapter(tmp_path).symbol("answer")

    assert result["contract_version"] == MCP_CONTRACT_VERSION
    assert result["provenance"] == {
        "source": "codira-core",
        "repository": tmp_path.name,
        "trusted_root": ".",
    }
    assert result["result"] == {
        "symbols": [
            {
                "module": "sample",
                "name": "answer",
                "kind": "function",
                "file": "sample.py",
                "line": 5,
            }
        ]
    }


def test_server_exposes_initial_approved_tools(tmp_path: Path) -> None:
    """Assert the stdio server registers the initial contract tools.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided trusted repository root.

    Returns
    -------
    None
        The test asserts protocol-visible tool registration.
    """
    tools = asyncio.run(create_server(tmp_path).list_tools())

    assert {tool.name for tool in tools} == {
        "callees",
        "callers",
        "capabilities",
        "documentation_findings",
        "context_for_task",
        "impact_analysis",
        "index_status",
        "references",
        "symbol",
        "symbols",
        "repository_map",
    }


def test_adapter_exposes_structural_query_tools(tmp_path: Path) -> None:
    """Assert direct structural MCP tools preserve their bounded result shape.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided temporary repository root.

    Returns
    -------
    None
        The test asserts direct index, inventory, and call-query payloads.
    """
    _indexed_repository(tmp_path)
    adapter = MCPAdapter(tmp_path)

    status = adapter.index_status()
    inventory = adapter.symbols(limit=2)
    callees = adapter.callees("answer")
    callers = adapter.callers("helper")
    references = adapter.references("helper", direction="incoming")
    findings = adapter.documentation_findings()
    context = adapter.context_for_task("answer")
    impact = adapter.impact_analysis("helper")
    repository_map = adapter.repository_map()
    truncated_map = adapter.repository_map(output_budget=1)

    assert status["result"] == {
        "indexed": True,
        "metadata": {"schema_version": "23"},
        "coverage": {"status": "complete", "issues": []},
    }
    assert inventory["result"] == {
        "symbols": [
            {
                "type": "function",
                "module": "sample",
                "name": "answer",
                "file": "sample.py",
                "line": 5,
                "calls_out": {"total": 1, "unresolved": 0},
                "calls_in": {"total": 0, "unresolved": 0},
                "references_out": {"total": 0, "unresolved": 0},
                "references_in": {"total": 0, "unresolved": 0},
            },
            {
                "type": "function",
                "module": "sample",
                "name": "helper",
                "file": "sample.py",
                "line": 1,
                "calls_out": {"total": 0, "unresolved": 0},
                "calls_in": {"total": 1, "unresolved": 0},
                "references_out": {"total": 0, "unresolved": 0},
                "references_in": {"total": 0, "unresolved": 0},
            },
        ]
    }
    expected_call = {
        "caller_module": "sample",
        "caller_name": "answer",
        "callee_module": "sample",
        "callee_name": "helper",
        "resolved": True,
    }
    assert callees["result"] == {"calls": [expected_call]}
    assert callers["result"] == {"calls": [expected_call]}
    assert references["result"] == {"references": []}
    assert findings["result"] == {"findings": []}
    context_result = cast("dict[str, object]", context["result"])
    context_payload = cast("dict[str, object]", context_result["context"])
    top_matches = cast("list[dict[str, object]]", context_payload["top_matches"])
    assert context_payload["status"] == "ok"
    assert top_matches[0]["name"] == "answer"
    assert impact["result"] == {
        "symbols": [
            {
                "module": "sample",
                "name": "helper",
                "kind": "function",
                "file": "sample.py",
                "line": 1,
            }
        ],
        "incoming_calls": [expected_call],
        "incoming_references": [],
    }
    repository_map_result = cast("dict[str, object]", repository_map["result"])
    repository_map_truncation = cast("dict[str, object]", repository_map["truncation"])
    truncated_map_result = cast("dict[str, object]", truncated_map["result"])
    truncated_map_truncation = cast("dict[str, object]", truncated_map["truncation"])
    assert repository_map_result == {
        "modules": [
            {
                "module": "sample",
                "files": ["sample.py"],
                "symbol_count": 3,
                "symbol_kinds": {"function": 2, "module": 1},
            }
        ]
    }
    assert repository_map_truncation["truncated"] is False
    assert repository_map_truncation["reasons"] == []
    assert repository_map_truncation["output_budget"] == 4_000
    assert repository_map_truncation["estimated_output_size"] == len(
        json.dumps(repository_map_result, sort_keys=True)
    )
    assert truncated_map_result == {"modules": []}
    assert truncated_map_truncation["truncated"] is True
    assert truncated_map_truncation["reasons"] == ["output_budget"]


def test_adapter_paginates_and_rejects_path_like_cursors(tmp_path: Path) -> None:
    """Assert cursors paginate deterministic rows without becoming path inputs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided temporary repository root.

    Returns
    -------
    None
        The test asserts bounded continuation and trusted relative paths.
    """
    _indexed_repository(tmp_path)
    adapter = MCPAdapter(tmp_path)

    first_page = adapter.symbols(limit=1)
    second_page = adapter.symbols(cursor="offset:1", limit=1)

    assert first_page["page"] == {"limit": 1, "next_cursor": "offset:1"}
    assert second_page["page"] == {"limit": 1, "next_cursor": "offset:2"}
    first_result = cast("dict[str, object]", first_page["result"])
    first_symbols = cast("list[dict[str, object]]", first_result["symbols"])
    assert first_symbols[0]["file"] == "sample.py"
    with pytest.raises(ValueError, match="continuation cursor"):
        adapter.symbols(cursor="/etc/passwd")


def test_server_symbol_tool_invokes_the_direct_adapter(tmp_path: Path) -> None:
    """Assert the protocol-visible symbol tool forwards to the core adapter.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided temporary repository root.

    Returns
    -------
    None
        The test asserts structured MCP tool output without a CLI subprocess.
    """
    _indexed_repository(tmp_path)

    _, structured = cast(
        "tuple[object, dict[str, object]]",
        asyncio.run(create_server(tmp_path).call_tool("symbol", {"name": "answer"})),
    )

    assert structured["contract_version"] == MCP_CONTRACT_VERSION
    assert structured["result"] == {
        "symbols": [
            {
                "module": "sample",
                "name": "answer",
                "kind": "function",
                "file": "sample.py",
                "line": 5,
            }
        ]
    }
    assert structured["provenance"] == {
        "source": "codira-core",
        "repository": tmp_path.name,
        "trusted_root": ".",
    }
    assert structured["freshness"] == {"schema_version": "23"}
    assert structured["page"] == {"limit": 100, "next_cursor": None}
    truncation = cast("dict[str, object]", structured["truncation"])
    assert truncation["truncated"] is False
