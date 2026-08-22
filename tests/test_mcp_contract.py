"""Tests for the transport-independent MCP contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema  # type: ignore[import-untyped]
import pytest

from codira.mcp.contract import (
    MAX_OUTPUT_BUDGET,
    MCP_CONTRACT_VERSION,
    build_contract_document,
)


def test_contract_exposes_approved_local_read_only_surface() -> None:
    """Assert the v1 contract exposes the approved local tool inventory.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts contract metadata and tool names.
    """
    document = build_contract_document()

    assert document["contract_version"] == MCP_CONTRACT_VERSION
    assert document["transport"] == "stdio"
    assert document["read_only"] is True
    assert document["repository_model"] == {
        "selection": "startup_trusted_root",
        "path_inputs": False,
    }
    tools = {
        tool["name"]: tool for tool in cast("list[dict[str, Any]]", document["tools"])
    }
    assert {
        "capabilities",
        "symbol",
        "context_for_task",
        "repository_map",
        "arch",
        "emb",
        "docs",
    } <= set(tools)
    assert "repository_path" not in tools["symbol"]["request_schema"]["properties"]


def test_contract_manifest_matches_published_schema() -> None:
    """Validate the contract manifest against its distributed JSON Schema.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that the public artifact matches the Python source.
    """
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "codira"
        / "schema"
        / "mcp"
        / "contract.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.validate(build_contract_document(), schema)


def test_every_tool_request_and_response_schema_is_valid() -> None:
    """Validate representative payloads against every published tool schema.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts strict request and common response schema behavior.
    """
    document = build_contract_document()
    response = {
        "contract_version": MCP_CONTRACT_VERSION,
        "result": {},
        "provenance": {
            "source": "codira-core",
            "repository": "repo",
            "trusted_root": ".",
            "execution_mode": "direct",
            "generation": None,
        },
        "freshness": {},
        "page": {},
        "truncation": {},
    }
    tools = cast("list[dict[str, Any]]", document["tools"])
    for tool in tools:
        request = {name: "value" for name in tool["request_schema"]["required"]}
        jsonschema.validate(request, tool["request_schema"])
        jsonschema.validate(response, tool["response_schema"])

    symbol = next(tool for tool in tools if tool["name"] == "symbol")
    invalid = {
        "name": "value",
        "repository_path": "/tmp/repo",
        "output_budget": MAX_OUTPUT_BUDGET + 1,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, symbol["request_schema"])
