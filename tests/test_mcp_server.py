"""Tests for the initial local read-only MCP server adapter."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import cast

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from codira.indexer import index_repo
from codira.mcp.adapter import MCPAdapter
from codira.mcp.contract import MCP_CONTRACT_VERSION
from codira.mcp.proxy import QueryDaemonMCPProxy, build_mcp_operations
from codira.mcp.server import create_server, resolve_startup_binding
from codira.query_daemon import QueryDaemonIdentity, QueryRuntime, WarmQuerySession
from codira.query_daemon_ipc import QueryDaemonIpcServer
from codira.registry import active_index_backend
from codira.storage import override_storage_root
from codira.workspace_registry import WorkspaceRegistry


async def _subprocess_tool_names(root: Path) -> set[str]:
    """Initialize the installed stdio entry point and return its tool names.

    Parameters
    ----------
    root : pathlib.Path
        Trusted repository root passed to the child server process.

    Returns
    -------
    set[str]
        MCP tool names reported after a completed JSON-RPC initialization.
    """
    entry_point = Path(sys.executable).with_name("codira-mcp")
    parameters = StdioServerParameters(
        command=str(entry_point),
        args=["--root", str(root)],
    )
    async with stdio_client(parameters) as streams, ClientSession(*streams) as session:
        await session.initialize()
        tools = await session.list_tools()
    return {tool.name for tool in tools.tools}


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


def _workspace_registry(root: Path) -> WorkspaceRegistry:
    """Build an isolated registry for MCP workspace-startup tests.

    Parameters
    ----------
    root : pathlib.Path
        Temporary root containing descriptor and workspace state directories.

    Returns
    -------
    codira.workspace_registry.WorkspaceRegistry
        Isolated workspace registry.
    """
    return WorkspaceRegistry(root / "descriptors", root / "state")


def test_workspace_startup_binding_is_fixed_and_provenance_safe(
    tmp_path: Path,
) -> None:
    """Resolve workspace routing once and expose only safe identity metadata.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository, state, and descriptor roots.

    Returns
    -------
    None
        The test asserts descriptor changes cannot retarget an existing binding.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    config_file = tmp_path / "workspace.toml"
    config_file.write_text("[embeddings]\nbatch_size = 8\n", encoding="utf-8")
    registry = _workspace_registry(tmp_path)
    registry.add(
        registry.with_defaults(
            name="sample",
            repository_root=repository,
            config_file=config_file,
        )
    )

    binding = resolve_startup_binding(workspace="sample", registry=registry)
    expected_fingerprint = hashlib.sha256(
        registry.descriptor_path("sample").read_bytes()
    ).hexdigest()
    _, structured = cast(
        "tuple[object, dict[str, object]]",
        asyncio.run(
            create_server(
                binding.root,
                startup_provenance=binding.provenance(),
            ).call_tool("capabilities", {})
        ),
    )

    registry.update(registry.with_defaults(name="sample", repository_root=alternate))
    replacement = resolve_startup_binding(workspace="sample", registry=registry)

    provenance = cast("dict[str, object]", structured["provenance"])
    assert binding.root == repository
    assert binding.output_root == registry.state_root / "sample"
    assert binding.config_file == config_file
    assert provenance["workspace"] == "sample"
    assert provenance["workspace_descriptor_sha256"] == expected_fingerprint
    assert replacement.root == alternate
    assert replacement.descriptor_fingerprint != binding.descriptor_fingerprint


def test_workspace_startup_rejects_direct_root_ambiguity(tmp_path: Path) -> None:
    """Reject startup choices that could change a live MCP target.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Existing temporary repository root.

    Returns
    -------
    None
        The test asserts workspace and root selection are mutually exclusive.
    """
    with pytest.raises(ValueError, match="cannot be combined"):
        resolve_startup_binding(root=tmp_path, workspace="sample")


def test_workspace_and_direct_servers_share_read_only_behavior(
    tmp_path: Path,
) -> None:
    """Keep server tools equivalent after startup paths have been resolved.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository, state, and descriptor roots.

    Returns
    -------
    None
        The test asserts only workspace provenance differs between bindings.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    registry = _workspace_registry(tmp_path)
    registry.add(registry.with_defaults(name="sample", repository_root=repository))
    binding = resolve_startup_binding(workspace="sample", registry=registry)
    with override_storage_root(repository, binding.output_root):
        _indexed_repository(repository)
        direct_result = cast(
            "tuple[object, dict[str, object]]",
            asyncio.run(
                create_server(repository).call_tool("symbol", {"name": "answer"})
            ),
        )[1]
        workspace_result = cast(
            "tuple[object, dict[str, object]]",
            asyncio.run(
                create_server(
                    binding.root,
                    startup_provenance=binding.provenance(),
                ).call_tool("symbol", {"name": "answer"})
            ),
        )[1]

    assert direct_result["result"] == workspace_result["result"]
    assert direct_result["page"] == workspace_result["page"]
    assert direct_result["truncation"] == workspace_result["truncation"]
    workspace_provenance = cast("dict[str, object]", workspace_result["provenance"])
    assert workspace_provenance["workspace"] == "sample"


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
        "execution_mode": "direct",
        "generation": 1,
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


def test_adapter_uses_supplied_warm_query_executor(tmp_path: Path) -> None:
    """Execute structural MCP reads through a supplied warm session.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided temporary repository root.

    Returns
    -------
    None
        The test asserts the warm and direct result envelopes are identical.
    """
    _indexed_repository(tmp_path)
    identity = QueryDaemonIdentity.from_paths(tmp_path, tmp_path)
    runtime = QueryRuntime(
        identity,
        lambda generation: WarmQuerySession(
            lambda: active_index_backend(root=tmp_path),
            tmp_path,
            generation,
        ),
    )
    runtime.refresh(1)
    try:
        direct = MCPAdapter(tmp_path).symbol("answer")
        warm = MCPAdapter(tmp_path, query_executor=runtime).symbol("answer")
    finally:
        runtime.close()

    assert warm == direct


def test_proxy_routes_every_approved_tool_through_warm_daemon(tmp_path: Path) -> None:
    """Route the complete MCP surface through a real local warm IPC server.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided temporary repository root.

    Returns
    -------
    None
        The test asserts warm output and pagination retain direct parity.
    """
    _indexed_repository(tmp_path)
    identity = QueryDaemonIdentity.from_paths(tmp_path, tmp_path)
    runtime = QueryRuntime(
        identity,
        lambda generation: WarmQuerySession(
            lambda: active_index_backend(root=tmp_path), tmp_path, generation
        ),
    )
    runtime.refresh_from_generation_store()
    daemon = QueryDaemonIpcServer(identity, runtime, build_mcp_operations(tmp_path))
    daemon.start()
    try:
        direct = MCPAdapter(tmp_path)
        proxy = QueryDaemonMCPProxy(tmp_path)
        calls = {
            "capabilities": lambda adapter: adapter.capabilities(),
            "index_status": lambda adapter: adapter.index_status(),
            "symbol": lambda adapter: adapter.symbol("answer", limit=1),
            "symbols": lambda adapter: adapter.symbols(limit=1),
            "references": lambda adapter: adapter.references("helper", limit=1),
            "callers": lambda adapter: adapter.callers("helper", limit=1),
            "callees": lambda adapter: adapter.callees("answer", limit=1),
            "documentation_findings": lambda adapter: adapter.documentation_findings(
                limit=1
            ),
            "context_for_task": lambda adapter: adapter.context_for_task("answer"),
            "impact_analysis": lambda adapter: adapter.impact_analysis(
                "helper", limit=1
            ),
            "repository_map": lambda adapter: adapter.repository_map(limit=1),
        }
        for name, call in calls.items():
            warm = call(proxy)  # type: ignore[no-untyped-call]
            direct_result = call(direct)  # type: ignore[no-untyped-call]
            assert warm["result"] == direct_result["result"], name
            assert warm["page"] == direct_result["page"], name
            provenance = cast("dict[str, object]", warm["provenance"])
            assert provenance["execution_mode"] == "warm", name
            assert provenance["generation"] == 1, name
    finally:
        daemon.close()
        runtime.close()


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


def test_stdio_entry_point_completes_mcp_initialization(tmp_path: Path) -> None:
    """Assert the installed stdio server completes a real MCP handshake.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided trusted repository root.

    Returns
    -------
    None
        The test asserts the external process advertises every approved tool.
    """
    assert asyncio.run(_subprocess_tool_names(tmp_path)) == {
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

    capabilities = adapter.capabilities()
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

    status_result = cast("dict[str, object]", status["result"])
    assert status_result["indexed"] is True
    assert status_result["coverage"] == {"status": "complete", "issues": []}
    status_metadata = cast("dict[str, str]", status_result["metadata"])
    assert status_metadata["schema_version"] == "24"
    assert status_metadata["backend_name"] == "sqlite"
    codira_capabilities = cast(
        "dict[str, object]", cast("dict[str, object]", capabilities["result"])["codira"]
    )
    plugins = cast("list[dict[str, object]]", codira_capabilities["plugins"])
    python_plugin = next(
        plugin
        for plugin in plugins
        if plugin["family"] == "analyzer" and plugin["name"] == "python"
    )
    assert python_plugin["version"] == "10"
    assert python_plugin["distribution_version"] == "1.60.0"
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
        "execution_mode": "direct",
        "generation": 1,
    }
    freshness = cast("dict[str, str]", structured["freshness"])
    assert freshness["schema_version"] == "24"
    assert freshness["backend_name"] == "sqlite"
    assert structured["page"] == {"limit": 100, "next_cursor": None}
    truncation = cast("dict[str, object]", structured["truncation"])
    assert truncation["truncated"] is False
