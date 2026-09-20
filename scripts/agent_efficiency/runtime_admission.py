"""Prove a benchmark image can serve one indexed Codira MCP query.

This program runs inside the candidate runner image against a writable public
fixture mount.  It deliberately has no provider connection and never invokes a
benchmark agent.
"""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

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


async def _call_context(root: Path, query: str, mcp_command: str) -> None:
    """Initialize the installed stdio server and require a usable context call.

    Parameters
    ----------
    root : pathlib.Path
        Indexed fixture root trusted by the server.
    query : str
        Non-empty fixture-local retrieval request.

    Raises
    ------
    RuntimeAdmissionError
        If initialization or the context tool fails.
    """

    parameters = StdioServerParameters(command=mcp_command, args=["--root", str(root)])
    try:
        async with (
            stdio_client(parameters) as streams,
            ClientSession(*streams) as session,
            asyncio.timeout(30),
        ):
            await session.initialize()
            status_response = await session.call_tool("index_status", arguments={})
            status_document = _tool_document(status_response)
            status_result = status_document.get("result")
            if not isinstance(status_result, Mapping):
                raise RuntimeAdmissionError("Codira MCP index status is malformed")
            metadata = status_result.get("metadata")
            generation = status_result.get("generation")
            indexed_file_count = (
                metadata.get("indexed_file_count")
                if isinstance(metadata, Mapping)
                else None
            )
            if (
                status_result.get("usable") is not True
                or not isinstance(metadata, Mapping)
                or not isinstance(indexed_file_count, str | int)
                or isinstance(indexed_file_count, bool)
                or not str(indexed_file_count).isdecimal()
                or int(indexed_file_count) < 1
                or not isinstance(generation, Mapping)
                or generation.get("state") != "ready"
                or generation.get("partial") is not False
                or generation.get("failed_file_count") != 0
            ):
                raise RuntimeAdmissionError("Codira MCP index is not usable")
            response = await session.call_tool(
                "context_for_task", arguments={"query": query, "output_budget": 512}
            )
    except TimeoutError as error:
        detail = "Codira MCP context query exceeded the admission timeout"
        raise RuntimeAdmissionError(detail) from error
    if response.isError or not response.content:
        detail = repr(response.content)[:500]
        message = f"Codira MCP context query was not usable: {detail}"
        raise RuntimeAdmissionError(message)
    document = _tool_document(response)
    result = document.get("result")
    context = result.get("context") if isinstance(result, Mapping) else None
    if not isinstance(context, Mapping) or context.get("status") != "ok":
        raise RuntimeAdmissionError("Codira MCP context query found no fixture context")


def admit_runtime(root: Path, query: str, config_path: str | None = None) -> None:
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
    None
        The function returns only after index and MCP admission succeed.

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
    asyncio.run(_call_context(root, query, mcp_command))


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
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--config-path", default="/opt/codira/benchmark-codira.toml")
    parsed = parser.parse_args(arguments)
    try:
        admit_runtime(parsed.root, parsed.query, parsed.config_path)
    except RuntimeAdmissionError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
