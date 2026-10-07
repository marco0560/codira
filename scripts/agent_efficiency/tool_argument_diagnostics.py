"""Compare retained provider calls with native MCP dispatch without inference.

Parameters
----------
None

Returns
-------
None
    Diagnostic reports contain names, argument digests and counts only.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import TYPE_CHECKING, cast

from codira.mcp.contract import build_contract_document
from scripts.agent_efficiency.contracts import canonical_fingerprint

if TYPE_CHECKING:
    from pathlib import Path


def _response_items(body: bytes) -> list[dict[str, object]]:
    """Extract completed output items from exact JSON or SSE response bytes.

    Parameters
    ----------
    body : bytes
        Persisted provider response, never a request or credential.

    Returns
    -------
    list[dict[str, object]]
        Completed output items, counting each streamed item only once.

    Raises
    ------
    ValueError
        If the response has no parseable terminal output.
    """
    text = body.decode("utf-8")
    try:
        documents = [json.loads(text)]
    except json.JSONDecodeError:
        documents = [
            json.loads(line[5:].strip())
            for line in text.splitlines()
            if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}
        ]
    done: list[dict[str, object]] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        response = (
            document.get("response")
            if document.get("type") == "response.completed"
            else document
        )
        if isinstance(response, dict) and isinstance(response.get("output"), list):
            return cast("list[dict[str, object]]", response["output"])
        if document.get("type") == "response.output_item.done":
            item = document.get("item")
            if isinstance(item, dict):
                done.append(item)
    if done:
        return done
    message = "provider response has no completed output items"
    raise ValueError(message)


def compare_tool_arguments(response_root: Path, events: str) -> dict[str, object]:
    """Verify raw-response digests and compare arguments with native dispatch.

    Parameters
    ----------
    response_root : pathlib.Path
        Ignored per-attempt directory containing response bodies and metadata.
    events : str
        Retained native JSONL events including started MCP tool calls.

    Returns
    -------
    dict[str, object]
        Matched, mismatch or incomplete evidence; values remain in raw evidence.
        Call ordering may differ because native tools can execute concurrently.
    """
    try:
        native = _native_calls(events)
        provider, verified = _provider_calls(response_root)
    except (ValueError, KeyError, OSError, TypeError, AttributeError):
        return {"status": "incomplete"}
    return {
        "status": "matched" if provider == native and native else "mismatch",
        "verified_responses": verified,
        "provider_calls": sum(provider.values()),
        "native_calls": sum(native.values()),
        "provider_only": [
            {"tool": name, "arguments_sha256": digest, "count": count}
            for (name, digest), count in sorted((provider - native).items())
        ],
        "native_only": [
            {"tool": name, "arguments_sha256": digest, "count": count}
            for (name, digest), count in sorted((native - provider).items())
        ],
        "scope": "provider-generated arguments versus native MCP dispatch; "
        "does not identify transformations inside OpenRouter or prove task competence",
    }


def _native_calls(events: str) -> Counter[tuple[str, str]]:
    """Extract native calls without retaining argument values.

    Parameters
    ----------
    events : str
        Complete native JSONL events.

    Returns
    -------
    collections.Counter[tuple[str, str]]
        Tool names and canonical argument digests with multiplicity.

    Raises
    ------
    ValueError
        If a started MCP call has no object arguments.
    """
    calls: Counter[tuple[str, str]] = Counter()
    for line in events.splitlines():
        event = json.loads(line)
        item = event.get("item", {})
        if (
            event.get("type") == "item.started"
            and item.get("type") == "mcp_tool_call"
            and item.get("server") == "codira"
        ):
            arguments = item.get("arguments")
            if not isinstance(arguments, dict):
                message = "native tool arguments are missing"
                raise ValueError(message)
            calls[(item["tool"], canonical_fingerprint(arguments))] += 1
    return calls


def _provider_calls(response_root: Path) -> tuple[Counter[tuple[str, str]], int]:
    """Extract Codira calls from verified retained upstream response bodies.

    Parameters
    ----------
    response_root : pathlib.Path
        Per-attempt response bodies and metadata.

    Returns
    -------
    tuple[collections.Counter[tuple[str, str]], int]
        Call digests and number of verified successful upstream responses.

    Raises
    ------
    ValueError
        If a response digest or tool arguments cannot be verified.
    """
    calls: Counter[tuple[str, str]] = Counter()
    verified = 0
    names = {
        str(tool["name"])
        for tool in cast("list[dict[str, object]]", build_contract_document()["tools"])
    }
    for path in sorted(response_root.glob("response-*.body")):
        body = path.read_bytes()
        metadata = json.loads(path.with_suffix(".json").read_text())
        if hashlib.sha256(body).hexdigest() != metadata["body_sha256"]:
            message = "provider response digest mismatch"
            raise ValueError(message)
        if metadata.get("status") != 200:
            continue
        verified += 1
        for item in _response_items(body):
            name = str(item.get("name", "")).removeprefix("mcp__codira__")
            if item.get("type") == "function_call" and name in names:
                arguments = json.loads(str(item["arguments"]))
                if not isinstance(arguments, dict):
                    message = "provider tool arguments are not an object"
                    raise ValueError(message)
                calls[(name, canonical_fingerprint(arguments))] += 1
    return calls, verified
