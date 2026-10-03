"""Exercise native tool permissions without authentication or a model turn.

Parameters
----------
None

Returns
-------
None
    Qualification uses the native app-server and the actual container profile.
"""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import json
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from scripts.agent_efficiency.codex_subscription import (
    _request,
    write_subscription_config,
)
from scripts.agent_efficiency.runner import (
    PROJECT_TEMP_ROOT,
    ContainerAttemptRequest,
    build_container_argv,
    remove_timed_out_container,
)

TOOL_SMOKE = """from pathlib import Path
import subprocess
import json
import stat
assert stat.S_IMODE(Path('/tmp').stat().st_mode) == 0o1777, 'temporary directory permissions differ'
home = Path.home()
(home / '.cache').mkdir(parents=True, exist_ok=True)
(home / '.config').mkdir(exist_ok=True)
(home / 'readiness-write').write_text('public canary')
try:
    Path('/codex-state/auth.json').read_bytes()
except (PermissionError, FileNotFoundError):
    pass
else:
    raise AssertionError('credential state was readable')
for command in (['git', 'status', '--short'], ['uv', 'cache', 'dir'],
                ['codira', 'caps', '--json']):
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, (command, completed.stderr)
print(json.dumps({'tool_home':'writable','credential_read':'denied','shell_git_uv_cli':'passed'}))
"""


def probe_native_client(
    command: tuple[str, ...], *, require_mcp: bool, diagnostic_path: Path
) -> dict[str, object]:
    """Call native configuration, shell and MCP handlers with no model turn.

    Parameters
    ----------
    command : tuple[str, ...]
        Isolated native app-server command.
    require_mcp : bool
        Require effective approval and actual indexed MCP tool execution.
    diagnostic_path : pathlib.Path
        Durable native stderr destination, including unsuccessful probes.

    Returns
    -------
    dict[str, object]
        Observations from native dispatch rather than direct server calls.

    Raises
    ------
    ValueError
        If effective policy, shell execution or MCP dispatch is unavailable.
    """
    with (
        diagnostic_path.open("x") as diagnostics,
        subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=diagnostics,
            text=True,
        ) as process,
    ):
        try:
            _request(
                process,
                "initialize",
                1,
                {
                    "clientInfo": {"name": "codira-readiness", "version": "1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            assert process.stdin is not None
            process.stdin.write('{"method":"initialized"}\n')
            process.stdin.flush()
            effective = _request(
                process,
                "config/read",
                2,
                {
                    "includeLayers": False,
                    "cwd": "/workspace",
                },
            )
            config = effective.get("config")
            if not isinstance(config, dict) or config.get("approval_policy") != "never":
                raise ValueError("native effective approval policy differs")
            shell = _request(
                process,
                "command/exec",
                3,
                {
                    "command": ["python", "-c", TOOL_SMOKE],
                    "cwd": "/workspace",
                    "timeoutMs": 20000,
                },
            )
            if shell.get("exitCode") != 0:
                raise ValueError("native tool shell contract failed")
            observations: dict[str, object] = {
                "status": "passed",
                "model_turn_count": 0,
                "shell": json.loads(str(shell["stdout"])),
                "mcp": "absent",
            }
            servers = config.get("mcp_servers")
            if require_mcp:
                if not isinstance(servers, dict) or not isinstance(
                    servers.get("codira"), dict
                ):
                    raise ValueError("native effective Codira MCP is missing")
                server = servers["codira"]
                if server.get("default_tools_approval_mode") != "approve":
                    raise ValueError("native Codira MCP is not preapproved")
                thread = _request(
                    process,
                    "thread/start",
                    4,
                    {
                        "cwd": "/workspace",
                        "ephemeral": True,
                    },
                )
                thread_body = cast("dict[str, object]", thread["thread"])
                calls = []
                for identifier, tool, arguments in (
                    (5, "index_status", {}),
                    (
                        6,
                        "context_for_task",
                        {"query": "Qualification probe helper", "limit": 1},
                    ),
                ):
                    result = _request(
                        process,
                        "mcpServer/tool/call",
                        identifier,
                        {
                            "threadId": thread_body["id"],
                            "server": "codira",
                            "tool": tool,
                            "arguments": arguments,
                        },
                    )
                    if result.get("isError") is True or not result.get("content"):
                        raise ValueError("native Codira MCP dispatch failed")
                    structured = result.get("structuredContent")
                    if not isinstance(structured, dict) or not isinstance(
                        structured.get("result"), dict
                    ):
                        raise TypeError("native Codira MCP result contract failed")
                    body = structured["result"]
                    if tool == "index_status":
                        generation = body.get("generation", {})
                        metadata = body.get("metadata", {})
                        if (
                            body.get("usable") is not True
                            or generation.get("state") != "ready"
                            or generation.get("partial") is not False
                            or generation.get("failed_file_count") != 0
                            or int(metadata.get("indexed_file_count", 0)) < 1
                        ):
                            raise ValueError("native Codira MCP index is not usable")
                    elif body.get("status") != "ok" or not body.get("items"):
                        raise ValueError(
                            "native Codira MCP returned no canary evidence"
                        )
                    calls.append({"tool": tool, "status": "passed", "result": result})
                observations["mcp"] = {"approval_mode": "approve", "calls": calls}
            elif servers:
                raise ValueError("baseline unexpectedly exposes MCP")
            return observations
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def qualify_native_tools(  # noqa: PLR0913 - frozen container and provider bindings
    runtime: str,
    image: str,
    fixture_root: Path,
    evidence_root: Path,
    model: str,
    effort: str,
    *,
    require_mcp: bool,
    provider_transport: str = "codex-subscription",
) -> dict[str, object]:
    """Run native tool qualification in the campaign container permissions.

    Parameters
    ----------
    runtime : str
        Host runtime.
    image : str
        Exact digest-pinned image.
    fixture_root : pathlib.Path
        Prepared indexed canary workspace.
    evidence_root : pathlib.Path
        Fresh durable result directory.
    model : str
        Frozen native model; no inference request is made.
    effort : str
        Frozen reasoning effort.
    require_mcp : bool
        Whether to expose and dispatch Codira MCP.
    provider_transport : str, optional
        Native or proxy route whose tool configuration is exercised.

    Returns
    -------
    dict[str, object]
        Native effective policy and successful tool execution observations.
    """
    evidence_root.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(
        prefix="ae-native-", dir=PROJECT_TEMP_ROOT
    ) as temporary:
        scratch = Path(temporary)
        state = scratch / "state"
        if provider_transport == "codex-subscription":
            write_subscription_config(
                state,
                model,
                effort,
                "/opt/codira/codira-mcp-benchmark" if require_mcp else None,
            )
        else:
            from scripts.agent_efficiency.phase0 import build_isolated_codex_config

            state.mkdir()
            config = build_isolated_codex_config(
                codira_root="/workspace",
                mcp_command="/opt/codira/codira-mcp-benchmark" if require_mcp else None,
            )
            (state / "config.toml").write_text(config)
        auth = scratch / "public-auth.json"
        auth.write_text('{"canary":"public-nonsecret-qualification"}')
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(scratch / "p.sock"))
            request = ContainerAttemptRequest(
                runtime,
                image,
                fixture_root,
                state,
                "offline readiness",
                60,
                temporary_root=scratch,
                proxy_socket=scratch / "p.sock",
                provider_transport=provider_transport,
                subscription_auth=auth
                if provider_transport == "codex-subscription"
                else None,
                proxy_client_token="public-qualification"
                if provider_transport != "codex-subscription"
                else None,
            )
            argv = build_container_argv(request)
            prefix = argv[: argv.index(image)]
            command = (
                *prefix,
                "--interactive",
                image,
                "codex",
                "--no-daemon",
                "app-server",
            )
            try:
                receipt = probe_native_client(
                    command,
                    require_mcp=require_mcp,
                    diagnostic_path=evidence_root / "native.stderr",
                )
            finally:
                remove_timed_out_container(request)
    receipt["image"] = image
    (evidence_root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
