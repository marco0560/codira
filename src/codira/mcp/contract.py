"""Define the versioned, transport-independent local MCP contract.

The module deliberately contains no server implementation. It describes the
read-only interface that #63 adapts to Codira core APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from codira.config import load_effective_config

if TYPE_CHECKING:
    from pathlib import Path

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
        Optional request properties accepted by this specific tool.
    """

    name: str
    description: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


_TOOLS: Final = (
    ToolContract("capabilities", "Discover supported contract tools and capabilities."),
    ToolContract("index_status", "Inspect index identity, freshness, and coverage."),
    ToolContract(
        "symbol",
        "Look up one exact symbol name.",
        ("name",),
        ("cursor", "limit", "output_budget"),
    ),
    ToolContract(
        "symbols",
        "List symbols using bounded deterministic pagination.",
        (),
        ("cursor", "limit", "output_budget"),
    ),
    ToolContract(
        "references",
        "Traverse callable references.",
        ("name",),
        ("direction", "cursor", "limit", "output_budget"),
    ),
    ToolContract(
        "callers",
        "List incoming static call edges.",
        ("name",),
        ("cursor", "limit", "output_budget"),
    ),
    ToolContract(
        "callees",
        "List outgoing static call edges.",
        ("name",),
        ("cursor", "limit", "output_budget"),
    ),
    ToolContract(
        "documentation_findings",
        "List documentation audit findings.",
        (),
        ("cursor", "limit", "output_budget"),
    ),
    ToolContract(
        "context_for_task",
        "Build paginated provenance-rich task context.",
        ("query",),
        ("cursor", "limit", "search_profile"),
    ),
    ToolContract(
        "impact_analysis",
        "Inspect structural impact for a symbol.",
        ("name",),
        ("cursor", "limit", "output_budget"),
    ),
    ToolContract(
        "repository_map",
        "Return a compact agent-oriented repository map.",
        (),
        ("cursor", "limit", "output_budget"),
    ),
    ToolContract(
        "arch",
        "Return a bounded read-only repository architecture model.",
        (),
        ("cursor", "limit", "output_budget"),
    ),
    ToolContract(
        "emb",
        "Search stored symbol embeddings without maintenance operations.",
        ("query",),
        ("prefix", "search_profile", "limit", "output_budget"),
    ),
    ToolContract(
        "docs",
        "Search stored documentation embeddings.",
        ("query",),
        ("prefix", "search_profile", "limit", "output_budget"),
    ),
)


def _request_schema(
    tool: ToolContract, *, profile_names: tuple[str, ...]
) -> dict[str, object]:
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
    properties: dict[str, object] = {}
    for name in (*tool.required, *tool.optional):
        properties[name] = {"type": "string", "minLength": 1}
    if "cursor" in tool.optional:
        properties["cursor"] = {
            "anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}],
            "default": None,
        }
    if "prefix" in tool.optional:
        properties["prefix"] = {
            "anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}],
            "default": None,
        }
    if "limit" in tool.optional:
        properties["limit"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 10 if tool.name == "context_for_task" else 100,
        }
    if "output_budget" in tool.optional:
        properties["output_budget"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_OUTPUT_BUDGET,
            "default": DEFAULT_OUTPUT_BUDGET,
        }
    if "search_profile" in tool.optional:
        properties["search_profile"] = {
            "anyOf": [
                {"type": "string", "minLength": 1, "enum": list(profile_names)},
                {"type": "null"},
            ],
            "default": None,
        }
    if "direction" in tool.optional:
        properties["direction"] = {
            "type": "string",
            "enum": ["incoming", "outgoing"],
            "default": "outgoing",
        }
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
                    "partial_index_warning": {
                        "type": "object",
                        "required": ["failed_file_count", "message"],
                        "properties": {
                            "failed_file_count": {"type": "integer", "minimum": 1},
                            "message": {"type": "string", "minLength": 1},
                        },
                        "additionalProperties": False,
                    },
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


def build_contract_document(*, root: Path | None = None) -> dict[str, object]:
    """Build the public, JSON-compatible MCP contract document.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose effective similarity profiles are published.

    Returns
    -------
    dict[str, object]
        Versioned contract manifest containing tool and envelope schemas.
    """
    profile_names = tuple(
        profile.name
        for profile in load_effective_config(root=root).embeddings.similarity_profiles
    )
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
                "request_schema": _request_schema(tool, profile_names=profile_names),
                "response_schema": response,
            }
            for tool in _TOOLS
        ],
    }
