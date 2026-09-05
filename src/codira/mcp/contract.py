"""Define the versioned, transport-independent local MCP contract.

The module deliberately contains no server implementation. It describes the
read-only interface that #63 adapts to Codira core APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

MCP_CONTRACT_VERSION: Final = "2.0.0"
MAX_OUTPUT_BUDGET: Final = 16_000
DEFAULT_OUTPUT_BUDGET: Final = 4_000


@dataclass(frozen=True)
class ToolContract:
    """Describe one MCP tool and its bounded input shape.

    Parameters
    ----------
    name : str
        Stable MCP tool name.
    description : str
        Client-facing operation description.
    required : tuple[str, ...]
        Required request properties.
    optional : tuple[str, ...]
        Optional request properties in addition to common pagination fields.
    """

    name: str
    description: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


_TOOLS: Final = (
    ToolContract("capabilities", "Discover supported contract tools and capabilities."),
    ToolContract("index_status", "Inspect index identity, freshness, and coverage."),
    ToolContract("symbol", "Look up one exact symbol name.", ("name",)),
    ToolContract("symbols", "List symbols using bounded deterministic pagination."),
    ToolContract(
        "references", "Traverse callable references.", ("name",), ("direction",)
    ),
    ToolContract("callers", "List incoming static call edges.", ("name",)),
    ToolContract("callees", "List outgoing static call edges.", ("name",)),
    ToolContract("documentation_findings", "List documentation audit findings."),
    ToolContract(
        "context_for_task", "Build bounded provenance-rich task context.", ("query",)
    ),
    ToolContract(
        "impact_analysis", "Inspect structural impact for a symbol.", ("name",)
    ),
    ToolContract("repository_map", "Return a compact agent-oriented repository map."),
    ToolContract(
        "arch",
        "Return a bounded read-only repository architecture model.",
    ),
    ToolContract(
        "emb",
        "Search stored symbol embeddings without maintenance operations.",
        ("query",),
        ("prefix", "search_profile"),
    ),
    ToolContract(
        "docs",
        "Search stored documentation embeddings.",
        ("query",),
        ("prefix", "search_profile"),
    ),
)


def _request_schema(tool: ToolContract) -> dict[str, object]:
    """Build the JSON Schema request definition for one tool.

    Parameters
    ----------
    tool : ToolContract
        Tool metadata used to construct the request schema.

    Returns
    -------
    dict[str, object]
        Strict Draft 2020-12 JSON Schema for the tool request.
    """
    properties: dict[str, object] = {
        "cursor": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "output_budget": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_OUTPUT_BUDGET,
            "default": DEFAULT_OUTPUT_BUDGET,
        },
    }
    for name in (*tool.required, *tool.optional):
        properties[name] = {"type": "string", "minLength": 1}
    if "direction" in tool.optional:
        properties["direction"] = {"enum": ["incoming", "outgoing"]}
    return {
        "type": "object",
        "required": list(tool.required),
        "properties": properties,
        "additionalProperties": False,
    }


def _response_schema() -> dict[str, object]:
    """Build the common JSON Schema response envelope.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Strict schema for successful MCP tool responses.
    """
    return {
        "type": "object",
        "required": [
            "contract_version",
            "result",
            "provenance",
            "freshness",
            "page",
            "truncation",
        ],
        "properties": {
            "contract_version": {"const": MCP_CONTRACT_VERSION},
            "result": {},
            "provenance": {
                "type": "object",
                "required": [
                    "source",
                    "repository",
                    "trusted_root",
                    "execution_mode",
                    "generation",
                ],
                "properties": {
                    "source": {"type": "string"},
                    "repository": {"type": "string"},
                    "trusted_root": {"const": "."},
                    "execution_mode": {"enum": ["warm", "direct", "fallback"]},
                    "generation": {"type": ["integer", "null"]},
                    "fallback_reason": {"type": "string"},
                    "workspace": {"type": "string", "minLength": 1},
                    "workspace_descriptor_sha256": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                },
                "additionalProperties": False,
            },
            "freshness": {"type": "object"},
            "page": {"type": "object"},
            "truncation": {"type": "object"},
        },
        "additionalProperties": False,
    }


def build_contract_document() -> dict[str, object]:
    """Build the public, JSON-compatible MCP contract document.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Versioned contract manifest containing tool and envelope schemas.
    """
    response = _response_schema()
    return {
        "contract_version": MCP_CONTRACT_VERSION,
        "transport": "stdio",
        "repository_model": {"selection": "startup_trusted_root", "path_inputs": False},
        "read_only": True,
        "compatibility": {"policy": "semantic_versioning", "additive_changes": "minor"},
        "errors": [
            "invalid_request",
            "unsupported_capability",
            "index_unavailable",
            "stale_index",
            "result_budget_exceeded",
            "internal_error",
        ],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "request_schema": _request_schema(tool),
                "response_schema": response,
            }
            for tool in _TOOLS
        ],
    }
