"""Generate the versioned public schemas for issue #53 benchmark records."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmarks" / "agent-efficiency" / "schemas"
VERSION = "1.0"
BASE = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
}
VISIBILITY = {"enum": ["public", "private"]}
IDENTITY = {
    "schema_version": {"const": VERSION},
    "visibility": VISIBILITY,
}
USAGE_PROPERTIES = {
    key: {"type": "integer", "minimum": 0}
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
}
USAGE = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ],
    "properties": USAGE_PROPERTIES,
}


def schema(required: list[str], properties: Mapping[str, object]) -> dict[str, object]:
    """Build one strict schema with common contract identity fields.

    Parameters
    ----------
    required : list[str]
        Required property names.
    properties : collections.abc.Mapping[str, object]
        Kind-specific JSON Schema properties.

    Returns
    -------
    dict[str, object]
        Complete Draft 2020-12 schema.
    """

    result = dict(BASE)
    result["required"] = ["schema_version", *required]
    result["properties"] = {**IDENTITY, **properties}
    return result


SCHEMAS = {
    "fixture": schema(
        ["fixture_id", "revision", "source_url", "license", "visibility"],
        {
            "fixture_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,63}$"},
            "revision": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "source_url": {"type": "string", "format": "uri"},
            "license": {"type": "string", "minLength": 1},
            "visibility": VISIBILITY,
            "private_locator": {"type": "string", "minLength": 1},
            "tree_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "license_path": {"type": "string", "format": "safe-relative-path"},
            "license_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "setup_files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path", "sha256"],
                    "properties": {
                        "path": {"type": "string", "format": "safe-relative-path"},
                        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    },
                },
            },
            "transport": {"const": "git-archive"},
        },
    ),
    "task": schema(
        ["task_id", "fixture_id", "prompt", "result_path", "oracle_id", "visibility"],
        {
            "task_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,63}$"},
            "fixture_id": {"type": "string"},
            "prompt": {"type": "string", "minLength": 1},
            "result_path": {"type": "string", "format": "safe-relative-path"},
            "result_format": {"enum": ["json", "text", "workspace-diff"]},
            "oracle_id": {"type": "string"},
            "visibility": VISIBILITY,
        },
    ),
    "campaign": schema(
        [
            "campaign_id",
            "fixture_fingerprints",
            "task_fingerprints",
            "task_fixture_ids",
            "budgets",
            "provider",
            "accounting",
            "resource_controls",
            "visibility",
        ],
        {
            "campaign_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,63}$"},
            "fixture_fingerprints": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
            "task_fingerprints": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
            "task_fixture_ids": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "string",
                    "pattern": "^[a-z0-9][a-z0-9-]{2,63}$",
                },
            },
            "budgets": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "max_total_tokens",
                    "max_output_tokens",
                    "timeout_seconds",
                ],
                "properties": {
                    "max_total_tokens": {"type": "integer", "minimum": 1},
                    "max_output_tokens": {"type": "integer", "minimum": 1},
                    "timeout_seconds": {"type": "integer", "minimum": 1},
                },
            },
            "visibility": VISIBILITY,
            "provider": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "name",
                    "model",
                    "reasoning_effort",
                    "wire_api",
                    "max_prompt_usd_per_million",
                    "max_completion_usd_per_million",
                ],
                "properties": {
                    "name": {"const": "openrouter"},
                    "model": {"type": "string", "minLength": 1},
                    "reasoning_effort": {
                        "enum": ["none", "low", "medium", "high", "xhigh"]
                    },
                    "wire_api": {"const": "responses"},
                    "max_prompt_usd_per_million": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                    },
                    "max_completion_usd_per_million": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                    },
                },
            },
            "accounting": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "max_daily_spend_usd",
                    "max_estimated_attempt_spend_usd",
                    "max_estimated_pilot_spend_usd",
                    "max_response_requests_per_attempt",
                ],
                "properties": {
                    "max_daily_spend_usd": {"type": "number", "exclusiveMinimum": 0},
                    "max_estimated_attempt_spend_usd": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                    },
                    "max_estimated_pilot_spend_usd": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                    },
                    "max_response_requests_per_attempt": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "max_transport_attempts_per_response": {
                        "type": "integer",
                        "minimum": 1,
                    },
                },
            },
            "resource_controls": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "network",
                    "read_only_rootfs",
                    "pids_limit",
                    "tmpfs_size_mib",
                ],
                "properties": {
                    "network": {"const": "none"},
                    "read_only_rootfs": {"const": True},
                    "pids_limit": {"type": "integer", "minimum": 1},
                    "tmpfs_size_mib": {"type": "integer", "minimum": 1},
                },
            },
            "runtime_image": {"type": "string", "pattern": "^.+@sha256:[0-9a-f]{64}$"},
            "runtime_profile_fingerprint": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "treatment_protocol": {
                "type": "object",
                "additionalProperties": False,
                "required": ["version", "codira_mcp_instruction"],
                "properties": {
                    "version": {
                        "type": "string",
                        "pattern": "^[a-z0-9][a-z0-9.-]{0,63}$",
                    },
                    "codira_mcp_instruction": {"type": "string", "minLength": 1},
                },
            },
        },
    ),
    "usage": schema(
        [
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        ],
        USAGE_PROPERTIES,
    ),
    "run-result": schema(
        [
            "campaign_id",
            "task_id",
            "attempt_id",
            "assistance_mode",
            "outcome",
            "usage_complete",
            "usage",
            "provenance",
        ],
        {
            "campaign_id": {"type": "string"},
            "task_id": {"type": "string"},
            "attempt_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,127}$"},
            "assistance_mode": {"enum": ["baseline", "codira-mcp"]},
            "outcome": {
                "enum": [
                    "success",
                    "oracle_failure",
                    "infrastructure_failure",
                    "cancelled",
                ]
            },
            "failure_class": {"type": ["string", "null"]},
            "usage_complete": {"type": "boolean"},
            "usage": USAGE,
            "provenance": {
                "type": "object",
                "additionalProperties": False,
                "required": ["runner", "runner_version"],
                "properties": {
                    "runner": {"type": "string"},
                    "runner_version": {"type": "string"},
                },
            },
        },
    ),
    "oracle": schema(
        ["oracle_id", "task_id", "definition", "visibility"],
        {
            "oracle_id": {"type": "string"},
            "task_id": {"type": "string"},
            "definition": {"type": "object"},
            "visibility": VISIBILITY,
        },
    ),
}

_CAMPAIGN_PROPERTIES = cast(
    "Mapping[str, object]",
    cast("Mapping[str, object]", SCHEMAS["campaign"])["properties"],
)
_CAMPAIGN_SPEC_PROPERTIES = dict(_CAMPAIGN_PROPERTIES)
_CAMPAIGN_SPEC_PROPERTIES.pop("fixture_fingerprints")
_CAMPAIGN_SPEC_PROPERTIES.pop("task_fingerprints")
_CAMPAIGN_SPEC_PROPERTIES.pop("task_fixture_ids")
_CAMPAIGN_SPEC_PROPERTIES.update(
    {
        "stage": {"enum": ["calibration", "pilot"]},
        "task_ids": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,63}$"},
            "uniqueItems": True,
        },
        "seed": {"type": "integer", "minimum": 0},
    }
)
SCHEMAS["campaign-spec"] = schema(
    [
        "campaign_id",
        "stage",
        "task_ids",
        "budgets",
        "provider",
        "accounting",
        "resource_controls",
        "visibility",
    ],
    _CAMPAIGN_SPEC_PROPERTIES,
)


def main(argv: list[str] | None = None) -> int:
    """Write canonical schema files.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments. ``--check`` verifies tracked output without
        rewriting it.

    Returns
    -------
    int
        Zero after all schemas have been written.

    Raises
    ------
    SystemExit
        If arguments other than the optional ``--check`` flag are supplied.
    """

    arguments = argv if argv is not None else sys.argv[1:]
    if set(arguments) - {"--check"}:
        detail = "usage: generate_agent_efficiency_schemas.py [--check]"
        raise SystemExit(detail)
    check = "--check" in arguments
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, value in SCHEMAS.items():
        path = OUTPUT / f"{name}.schema.json"
        rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
                print(
                    f"schema output is stale: {path.relative_to(ROOT)}", file=sys.stderr
                )
                return 1
        else:
            path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
