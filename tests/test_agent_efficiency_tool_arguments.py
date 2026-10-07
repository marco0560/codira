"""Check model tool arguments at offline and retained-provider boundaries.

Parameters
----------
None

Returns
-------
None
    Definitions are consumed by the local MCP or qualification workflow.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from codira.mcp.contract import build_contract_document
from scripts.agent_efficiency import provider_proxy
from scripts.agent_efficiency.tool_argument_diagnostics import compare_tool_arguments

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("optional", [{}, {"cursor": None, "search_profile": None}])
def test_provider_mapping_preserves_schema_and_null_arguments(
    optional: dict[str, object],
) -> None:
    """Keep optional omissions, nulls and tool schemas through request mapping.

    Parameters
    ----------
    optional : dict[str, object]
        Omitted or explicit-null first-page parameters.

    Returns
    -------
    None
        Provider controls do not rewrite model-visible tools or prior calls.
    """
    tools = cast("list[dict[str, object]]", build_contract_document()["tools"])
    context = next(tool for tool in tools if tool["name"] == "context_for_task")
    request = {
        "model": "stealth/space-bunny-alpha",
        "reasoning": {"effort": "max"},
        "tools": [
            {
                "type": "function",
                "name": "context_for_task",
                "parameters": context["request_schema"],
            }
        ],
        "input": [
            {
                "type": "function_call",
                "name": "context_for_task",
                "arguments": json.dumps({"query": "probe", "limit": 1, **optional}),
            }
        ],
    }
    result = json.loads(
        provider_proxy.constrain_response_request(
            json.dumps(request).encode(),
            64000,
            provider_proxy.ResponseConstraints(
                "stealth/space-bunny-alpha", "max", 0.16, 0.6
            ),
        )
    )
    assert result["tools"] == request["tools"]
    assert result["input"] == request["input"]


@pytest.mark.parametrize("wire_format", ["json", "sse"])
@pytest.mark.parametrize("change", ["none", "null-to-dot", "tampered-body"])
def test_retained_provider_arguments_match_native_dispatch(
    tmp_path: Path, wire_format: str, change: str
) -> None:
    """Detect argument rewriting and tampered evidence across JSON and SSE.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated response evidence directory.
    wire_format : str
        JSON or streamed terminal response.
    change : str
        Matching call, transformed argument or corrupted body.

    Returns
    -------
    None
        Diagnostics identify mismatches without publishing argument values.
    """
    arguments = {"query": "probe", "cursor": None, "search_profile": None}
    output = [
        {
            "type": "function_call",
            "name": "context_for_task",
            "arguments": json.dumps(arguments),
        }
    ]
    response = {
        "output": output,
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        },
    }
    body = json.dumps(response).encode()
    if wire_format == "sse":
        body = (
            "data: "
            + json.dumps({"type": "response.output_item.done", "item": output[0]})
            + "\n\ndata: "
            + json.dumps({"type": "response.completed", "response": response})
            + "\n\ndata: [DONE]\n\n"
        ).encode()
    response_root = tmp_path / "provider-responses"
    settings = provider_proxy.ProxySettings(
        "public-client",
        "public-provider",
        0,
        response_artifact_root=response_root,
    )
    settings.record_response(200, [], body=body)
    if change == "null-to-dot":
        arguments["cursor"] = "."
    if change == "tampered-body":
        (response_root / "response-001.body").write_bytes(body + b" ")
    events = json.dumps(
        {
            "type": "item.started",
            "item": {
                "type": "mcp_tool_call",
                "server": "codira",
                "tool": "context_for_task",
                "arguments": arguments,
            },
        }
    )
    report = compare_tool_arguments(response_root, events)
    assert (
        report["status"]
        == {
            "none": "matched",
            "null-to-dot": "mismatch",
            "tampered-body": "incomplete",
        }[change]
    )
    assert "query" not in json.dumps(report)
