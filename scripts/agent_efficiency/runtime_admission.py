"""Prove a benchmark image can serve one indexed Codira MCP query.

This program runs inside the candidate runner image against a writable public
fixture mount.  It deliberately has no provider connection and never invokes a
benchmark agent.
"""
# ruff: noqa: EM101, TRY003, TRY301

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

GIT_EXECUTABLE = shutil.which("git")


class RuntimeAdmissionError(RuntimeError):
    """Report a stable runtime-admission failure.

    Parameters
    ----------
    detail : str
        Public-safe description of the failed local capability.
    """


def _tool_document(response: object) -> Mapping[str, object]:
    """Decode one MCP tool response into its structured document.

    Parameters
    ----------
    response : object
        MCP SDK call result carrying structured or text JSON content.

    Returns
    -------
    collections.abc.Mapping[str, object]
        Parsed tool document.

    Raises
    ------
    RuntimeAdmissionError
        If no structured object can be recovered.
    """

    structured = getattr(response, "structuredContent", None)
    if isinstance(structured, Mapping):
        return structured
    for item in getattr(response, "content", ()):
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            continue
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(document, Mapping):
            return document
    raise RuntimeAdmissionError("Codira MCP response is not structured JSON")


def _require_history_free_staged_fixture(root: Path) -> int:
    """Require the exact staged, history-free representation used by agents.

    Parameters
    ----------
    root : pathlib.Path
        Candidate exported fixture mount.

    Returns
    -------
    int
        Positive count of paths in the synthetic Git index.

    Raises
    ------
    RuntimeAdmissionError
        If the fixture has history or no staged baseline paths.
    """

    if GIT_EXECUTABLE is None:
        raise RuntimeAdmissionError("runtime admission Git executable is unavailable")
    history = subprocess.run(
        (GIT_EXECUTABLE, "rev-parse", "--verify", "HEAD"),
        cwd=root,
        check=False,
        capture_output=True,
    )
    try:
        tracked = subprocess.run(
            (GIT_EXECUTABLE, "ls-files", "--cached", "-z"),
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise RuntimeAdmissionError(
            "runtime admission requires a synthetic Git fixture"
        ) from error
    count = len([item for item in tracked.split(b"\0") if item])
    if history.returncode == 0 or count < 1:
        raise RuntimeAdmissionError(
            "runtime admission requires a staged history-free fixture"
        )
    return count


async def _call_context(root: Path, query: str, mcp_command: str) -> dict[str, object]:
    """Qualify the actual registered server and whole-item protocol offline.

    Parameters
    ----------
    root : pathlib.Path
        Indexed fixture trusted by the server.
    query : str
        Retrieval request matching at least two discovery items.
    mcp_command : str
        Installed image-local server entry point.

    Returns
    -------
    dict[str, object]
        Installed runtime, actual schemas, status and behavioral probe receipt.

    Raises
    ------
    RuntimeAdmissionError
        If the installed protocol is legacy, incomplete or unusable.
    """
    parameters = StdioServerParameters(command=mcp_command, args=["--root", str(root)])
    async with (
        stdio_client(parameters) as streams,
        ClientSession(*streams) as session,
        asyncio.timeout(60),
    ):
        await session.initialize()
        tools = await session.list_tools()
        schemas = {tool.name: tool.inputSchema for tool in tools.tools}
        context_schema = schemas.get("context_for_task", {}).get("properties", {})
        if (
            "limit" not in context_schema
            or "cursor" not in context_schema
            or "output_budget" in context_schema
        ):
            raise RuntimeAdmissionError(
                "installed runtime does not serve the whole-item protocol"
            )
        discovery = _tool_document(
            await session.call_tool("capabilities", arguments={})
        )
        capability_result = discovery.get("result")
        advertised = (
            capability_result.get("mcp")
            if isinstance(capability_result, Mapping)
            else None
        )
        declared_tools = (
            advertised.get("tools") if isinstance(advertised, Mapping) else None
        )
        if (
            not isinstance(declared_tools, list)
            or {item["name"]: item["request_schema"] for item in declared_tools}
            != schemas
        ):
            raise RuntimeAdmissionError("registered schemas differ from discovery")
        status = _tool_document(await session.call_tool("index_status", arguments={}))
        status_result = status.get("result")
        if (
            not isinstance(status_result, Mapping)
            or status_result.get("usable") is not True
        ):
            raise RuntimeAdmissionError("installed runtime index is not usable")
        first = _tool_document(
            await session.call_tool(
                "context_for_task", arguments={"query": query, "limit": 1}
            )
        )
        first_result, page = first.get("result"), first.get("page")
        if not isinstance(first_result, Mapping) or not isinstance(page, Mapping):
            raise RuntimeAdmissionError("installed runtime context is malformed")
        items = first_result.get("items")
        cursor = page.get("next_cursor")
        if (
            not isinstance(items, list)
            or len(items) != 1
            or not isinstance(cursor, str)
        ):
            raise RuntimeAdmissionError(
                "qualification requires one whole item and a continuation"
            )
        second = _tool_document(
            await session.call_tool(
                "context_for_task",
                arguments={"query": query, "limit": 1, "cursor": cursor},
            )
        )
        second_result = second.get("result")
        if (
            not isinstance(second_result, Mapping)
            or second_result.get("items") == items
        ):
            raise RuntimeAdmissionError(
                "cursor did not advance to the next complete item"
            )
        wrong = await session.call_tool(
            "context_for_task",
            arguments={"query": query + " different", "limit": 1, "cursor": cursor},
        )
        payload = json.loads(base64.urlsafe_b64decode(cursor.split(":", 1)[1] + "=="))
        payload["generation"] = -1
        stale_cursor = (
            "ctx:" + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        )
        stale = await session.call_tool(
            "context_for_task",
            arguments={"query": query, "limit": 1, "cursor": stale_cursor},
        )
        if not wrong.isError or not stale.isError:
            raise RuntimeAdmissionError("runtime accepts wrong-query or stale cursors")
        inventory = _tool_document(
            await session.call_tool("symbol", arguments={"name": "probe", "limit": 10})
        )
        result = inventory.get("result")
        symbols = result.get("symbols") if isinstance(result, Mapping) else None
        if (
            not isinstance(symbols, list)
            or not symbols
            or symbols[0].get("owner") != "Qualification"
        ):
            raise RuntimeAdmissionError(
                "runtime does not preserve qualified method ownership"
            )
        expanded = _tool_document(
            await session.call_tool(
                "symbol_evidence", arguments={"identity": symbols[0]["identity"]}
            )
        )
        evidence = expanded.get("result")
        if (
            not isinstance(evidence, Mapping)
            or "return 42" not in str(evidence.get("source"))
            or not isinstance(evidence.get("coverage"), Mapping)
        ):
            raise RuntimeAdmissionError("runtime cannot expand whole verified evidence")
        caps = discovery.get("result")
        runtime = caps.get("runtime") if isinstance(caps, Mapping) else None
        if not isinstance(runtime, Mapping) or not isinstance(
            runtime.get("source_sha256"), str
        ):
            raise RuntimeAdmissionError(
                "runtime does not identify the installed source"
            )
        return {
            "qualification_version": 3,
            "runtime": dict(runtime),
            "tool_schemas": schemas,
            "tool_schemas_sha256": hashlib.sha256(
                json.dumps(schemas, sort_keys=True).encode()
            ).hexdigest(),
            "index": dict(status_result),
            "probes": [
                "limit-one",
                "continuation",
                "wrong-query",
                "stale-cursor",
                "owner",
                "whole-source",
                "coverage",
            ],
        }


def admit_runtime(
    root: Path, query: str, config_path: str | None = None
) -> dict[str, object]:
    """Index one fixture and validate its installed Codira MCP service.

    Parameters
    ----------
    root : pathlib.Path
        Writable public fixture mount.
    query : str
        Non-empty fixture-local context request.
    config_path : str or None, optional
        Image-local structural profile. ``None`` retains ordinary host commands
        for the local regression test.

    Returns
    -------
    dict[str, object]
        Exact registered schemas, installed source identity and probe receipt.

    Raises
    ------
    RuntimeAdmissionError
        If the fixture, backend, index, or MCP query is unavailable.
    """

    if not root.is_dir() or not query.strip():
        raise RuntimeAdmissionError("runtime admission needs a fixture root and query")
    executable = shutil.which("codira")
    if executable is None:
        detail = "codira index executable is unavailable in the runner image"
        raise RuntimeAdmissionError(detail)
    if config_path is not None:
        _require_history_free_staged_fixture(root)
        profile = Path(config_path)
        if not profile.is_file():
            raise RuntimeAdmissionError("benchmark Codira profile is unavailable")
        fixture_config = root / ".codira" / "config.toml"
        fixture_config.parent.mkdir(exist_ok=True)
        shutil.copyfile(profile, fixture_config)
    try:
        index_command = (executable, "index") + (
            ("--config-file", config_path) if config_path is not None else ()
        )
        indexed = subprocess.run(
            index_command,
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as error:
        detail = "codira index exceeded the runtime-admission timeout"
        raise RuntimeAdmissionError(detail) from error
    if indexed.returncode != 0:
        detail = "codira index failed during runtime admission"
        raise RuntimeAdmissionError(detail)
    mcp_command = "/opt/codira/codira-mcp-benchmark" if config_path else "codira-mcp"
    try:
        return asyncio.run(_call_context(root, query, mcp_command))
    except (TimeoutError, ExceptionGroup) as error:
        raise RuntimeAdmissionError(
            "MCP qualification failed; retained exception chain identifies the probe"
        ) from error


def main(arguments: list[str] | None = None) -> int:
    """Run the bounded no-provider runtime-admission check.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the program name.

    Returns
    -------
    int
        Zero only after an indexed MCP context query succeeds.

    Raises
    ------
    SystemExit
        If argument parsing or runtime admission fails.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--config-path", default="/opt/codira/benchmark-codira.toml")
    parser.add_argument("--expected-core-sha256", required=True)
    parsed = parser.parse_args(arguments)
    try:
        receipt = admit_runtime(parsed.root, parsed.query, parsed.config_path)
        runtime = cast("Mapping[str, object]", receipt["runtime"])
        if runtime["source_sha256"] != parsed.expected_core_sha256:
            raise RuntimeAdmissionError(
                "installed core source differs from approved serving product"
            )
        receipt["profile_sha256"] = hashlib.sha256(
            Path(parsed.config_path).read_bytes()
        ).hexdigest()
        print(json.dumps(receipt, sort_keys=True))
    except RuntimeAdmissionError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
