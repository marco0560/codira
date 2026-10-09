"""Behavioral checks for independent indexes and local family federation.

Parameters
----------
None

Returns
-------
None
    Tests covering provenance, configuration isolation, and continuation safety.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import jsonschema  # type: ignore[import-untyped]
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from codira.cli import main
from codira.config import load_effective_config
from codira.family import FamilyDefinition, FamilyError, load_family
from codira.family_runtime import FamilyRuntime, member_scope
from codira.index_generation import IndexGenerationStore
from codira.indexer import index_repo
from codira.mcp.family_server import create_family_server
from codira.registry import active_index_backend
from codira.workspace_registry import WorkspaceRegistry

if TYPE_CHECKING:
    from codira.mcp.server import ContractMCP


@pytest.fixture
def family_setup(tmp_path: Path) -> tuple[Path, WorkspaceRegistry, FamilyDefinition]:
    """Build two independent mixed-backend workspace indexes and a manifest.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary test root.

    Returns
    -------
    tuple[Path, WorkspaceRegistry, FamilyDefinition]
        Manifest, registry, and pinned indexed family.
    """
    registry = WorkspaceRegistry(tmp_path / "registry", tmp_path / "state")
    for name, backend in (("core", "sqlite"), ("plugin", "duckdb")):
        root = tmp_path / name
        root.mkdir()
        (root / "sample.py").write_text(
            "def helper() -> int:\n    return 42\n\ndef caller() -> int:\n    return helper()\n",
            encoding="utf-8",
        )
        config = tmp_path / f"{name}-config.toml"
        config.write_text(
            f'[backend]\nname = "{backend}"\n[embeddings]\nenabled = false\nbatch_size = {8 if name == "core" else 16}\n',
            encoding="utf-8",
        )
        registry.add(
            registry.with_defaults(name=name, repository_root=root, config_file=config)
        )
    manifest = tmp_path / "family.toml"
    manifest.write_text(
        'schema_version = 1\nname = "sample"\n[[members]]\nworkspace = "plugin"\nrole = "plugin"\n[[members]]\nworkspace = "core"\nrole = "core"\n[[links]]\nsource = {workspace = "plugin", name = "caller", file = "sample.py", lineno = 4}\ntarget = {workspace = "core", name = "helper", file = "sample.py", lineno = 1}\n',
        encoding="utf-8",
    )
    family = load_family(manifest, registry=registry)
    for member in family.members:
        with member_scope(member) as adapter:
            active_index_backend(root=adapter.root).initialize(adapter.root)
            assert index_repo(adapter.root).failed == 0
    return manifest, registry, family


def _items(response: dict[str, object]) -> list[dict[str, object]]:
    """Read complete result items from a family contract envelope.

    Parameters
    ----------
    response : dict[str, object]
        Family response.

    Returns
    -------
    list[dict[str, object]]
        Selected items.
    """
    return cast(
        "list[dict[str, object]]",
        cast("dict[str, object]", response["result"])["items"],
    )


def test_family_origins_collisions_and_independent_queries(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition],
) -> None:
    """Keep colliding definitions distinct and independent queries functional.

    Parameters
    ----------
    family_setup : tuple
        Independent indexed workspace fixture.

    Returns
    -------
    None
        Origin, identity, backend, and configuration assertions pass.
    """
    family = family_setup[2]
    runtime = FamilyRuntime(family)
    items = _items(runtime.query("symbol", "helper"))
    assert [item["repository"] for item in items] == ["core", "plugin"]
    assert items[0]["identity"] != items[1]["identity"]
    assert all(item["file"] == "sample.py" for item in items)
    for member, item in zip(family.members, items, strict=True):
        with member_scope(member) as adapter:
            local = cast("dict[str, object]", adapter.symbol("helper")["result"])
            assert len(cast("list[object]", local["symbols"])) == 1
            assert load_effective_config(root=adapter.root).embeddings.batch_size == (
                8 if item["repository"] == "core" else 16
            )
        evidence = cast(
            "dict[str, object]", runtime.evidence(str(item["identity"]))["result"]
        )
        assert evidence["repository"] == item["repository"]
        assert "return 42" in str(evidence["source"])


def test_family_context_pagination_and_order_invariance(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition],
) -> None:
    """Rank globally before pagination, regardless of membership iteration order.

    Parameters
    ----------
    family_setup : tuple
        Independent indexed workspace fixture.

    Returns
    -------
    None
        All global pages equal the complete ordered candidate set.
    """
    family = family_setup[2]
    runtime = FamilyRuntime(family)
    expected = _items(runtime.query("context", "helper", limit=100))
    assert {item["repository"] for item in expected} == {"core", "plugin"}
    assert all(item["score_kind"] == "family_reciprocal_rank" for item in expected)
    assert (
        _items(
            FamilyRuntime(
                replace(family, members=tuple(reversed(family.members)))
            ).query("context", "helper", limit=100)
        )
        == expected
    )
    collected: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        response = runtime.query("context", "helper", limit=1, cursor=cursor)
        collected.extend(_items(response))
        cursor = cast(
            "str | None", cast("dict[str, object]", response["page"])["next_cursor"]
        )
        if cursor is None:
            break
    assert collected == expected


def test_family_cursor_binds_all_members_and_query(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition],
) -> None:
    """Reject changed queries, filters, manifests, configuration, and generations.

    Parameters
    ----------
    family_setup : tuple
        Independent indexed workspace fixture.

    Returns
    -------
    None
        Continuation never silently crosses a changed family snapshot.
    """
    family = family_setup[2]
    runtime = FamilyRuntime(family)
    response = runtime.query("symbol", "helper", limit=1)
    cursor = cast("str", cast("dict[str, object]", response["page"])["next_cursor"])
    for kwargs in (
        {"query": "caller"},
        {"query": "helper", "repositories": ("core",)},
        {"query": "helper", "allow_partial": True},
    ):
        with pytest.raises(FamilyError, match="cursor does not match"):
            runtime.query("symbol", cursor=cursor, limit=1, **kwargs)
    with pytest.raises(FamilyError, match="cursor does not match"):
        FamilyRuntime(replace(family, descriptor_sha256="changed")).query(
            "symbol", "helper", cursor=cursor, limit=1
        )
    member = family.members[1]
    assert member.workspace is not None
    with member_scope(member):
        store = IndexGenerationStore(member.workspace.repository_root)
        record = store.read()
        assert record is not None
        store.write(replace(record, generation=record.generation + 1))
    with pytest.raises(FamilyError, match="cursor does not match"):
        runtime.query("symbol", "helper", cursor=cursor, limit=1)
    # Even a filtered query binds the generation of the other family member.
    with member_scope(family.members[0]) as adapter:
        (adapter.root / "extra.py").write_text(
            "def helper() -> int:\n    return 1\n", encoding="utf-8"
        )
        index_repo(adapter.root)
    filtered = runtime.query("symbol", "helper", repositories=("core",), limit=1)
    filtered_cursor = cast(
        "str", cast("dict[str, object]", filtered["page"])["next_cursor"]
    )
    with member_scope(member):
        record = store.read()
        assert record is not None
        store.write(replace(record, generation=record.generation + 1))
    with pytest.raises(FamilyError, match="cursor does not match"):
        runtime.query(
            "symbol", "helper", repositories=("core",), cursor=filtered_cursor, limit=1
        )


def test_family_strict_partial_stale_and_filtered_members(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition],
) -> None:
    """Reject stale members strictly and label explicit partial retrieval.

    Parameters
    ----------
    family_setup : tuple
        Independent indexed workspace fixture.

    Returns
    -------
    None
        Strict, partial, and declared-member filter policies are enforced.
    """
    family = family_setup[2]
    member = family.members[1]
    assert member.workspace is not None
    (member.workspace.repository_root / "sample.py").write_text(
        "def changed() -> int:\n    return 0\n", encoding="utf-8"
    )
    runtime = FamilyRuntime(family)
    with pytest.raises(FamilyError, match="source files changed"):
        runtime.query("symbol", "helper")
    partial = runtime.query("symbol", "helper", allow_partial=True)
    assert [item["repository"] for item in _items(partial)] == ["core"]
    result = cast("dict[str, object]", partial["result"])
    assert result["status"] == "partial"
    assert cast("list[dict[str, str]]", result["excluded"])[0]["repository"] == "plugin"
    assert len(_items(runtime.query("symbol", "helper", repositories=("core",)))) == 1
    with pytest.raises(FamilyError, match="member filter"):
        runtime.query("symbol", "helper", repositories=("undeclared",))


def test_family_explicit_references_and_missing_endpoints(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition],
) -> None:
    """Traverse only manifest links and validate exact endpoint locations.

    Parameters
    ----------
    family_setup : tuple
        Indexed family with one directed declared link.

    Returns
    -------
    None
        Direction, provenance, location validation, and partial link reporting pass.
    """
    family = family_setup[2]
    runtime = FamilyRuntime(family)
    edge = _items(runtime.query("references", "caller"))[0]
    assert edge["provenance"] == "family_manifest"
    assert cast("dict[str, object]", edge["source"])["repository"] == "plugin"
    assert cast("dict[str, object]", edge["target"])["repository"] == "core"
    assert _items(runtime.query("references", "helper", direction="incoming")) == [edge]
    assert _items(runtime.query("references", "helper")) == []
    broken = replace(family.links[0], target=replace(family.links[0].target, lineno=99))
    invalid = FamilyRuntime(replace(family, links=(broken,)))
    with pytest.raises(FamilyError, match="does not resolve uniquely"):
        invalid.query("references", "caller")
    result = cast(
        "dict[str, object]",
        invalid.query("references", "caller", allow_partial=True)["result"],
    )
    assert result["status"] == "partial"
    assert result["items"] == []


@pytest.mark.parametrize(
    "content",
    [
        'schema_version = 2\nname = "f"\n',
        'schema_version = true\nname = "f"\n',
        'schema_version = 1\nname = "f"\nmembers = []\n',
        'schema_version = 1\nname = "f"\n[[members]]\nworkspace = "../outside"\n',
        'schema_version = 1\nname = "f"\n[[members]]\nworkspace = "x"\n[[members]]\nworkspace = "x"\n',
        'schema_version = 1\nname = "f"\nunknown = 1\n[[members]]\nworkspace = "x"\n',
    ],
)
def test_family_rejects_invalid_manifests(tmp_path: Path, content: str) -> None:
    """Reject unknown fields, unsupported versions, unsafe names, and duplicates.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary descriptor directory.
    content : str
        Invalid TOML manifest variant.

    Returns
    -------
    None
        Invalid declarations never become query routing.
    """
    manifest = tmp_path / "family.toml"
    manifest.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_family(manifest)


def test_family_cli_queries_and_indexing_continue_after_failure(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise the real CLI and retain successful indexes after member failure.

    Parameters
    ----------
    family_setup : tuple
        Independent workspace fixture.
    monkeypatch : pytest.MonkeyPatch
        Isolated default registry and CLI arguments.
    capsys : pytest.CaptureFixture[str]
        CLI output capture.

    Returns
    -------
    None
        Family commands query real indexes and attempt members after failure.
    """
    manifest, registry, family = family_setup
    monkeypatch.setattr(WorkspaceRegistry, "default", classmethod(lambda cls: registry))
    monkeypatch.setattr(
        sys, "argv", ["codira", "family", "sym", str(manifest), "helper", "--json"]
    )
    assert main() == 0
    assert len(_items(json.loads(capsys.readouterr().out))) == 2
    assert family.members[0].workspace is not None
    (family.members[0].workspace.repository_root / "broken.py").write_text(
        'print "legacy"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "family", "index", str(manifest), "--json"],
    )
    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert [item["repository"] for item in report["members"]] == ["core", "plugin"]
    assert report["members"][0]["exit_status"] == 2
    assert report["members"][1]["exit_status"] == 0, json.dumps(report["members"][1])
    assert report["members"][1]["freshness"]["backend"][0] == "duckdb"


def test_family_mcp_contract_filters_and_query(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition],
) -> None:
    """Enforce family-only routing and report identical discovery schemas.

    Parameters
    ----------
    family_setup : tuple
        Independent indexed family fixture.

    Returns
    -------
    None
        Tool schemas reject undeclared members, paths, and invalid limits.
    """
    server = cast("ContractMCP", create_family_server(family_setup[2]))
    tool = server._tool_manager.get_tool("symbol")
    assert tool is not None
    assert tool.parameters["additionalProperties"] is False
    for arguments in (
        {"name": "helper", "root": "/outside"},
        {"name": "helper", "repositories": ["unknown"]},
        {"name": "helper", "limit": 0},
        {"name": "helper", "limit": True},
    ):
        with pytest.raises(jsonschema.ValidationError):
            asyncio.run(server.call_tool("symbol", arguments))
    response = asyncio.run(
        server.call_tool("symbol", {"name": "helper", "repositories": ["plugin"]})
    )
    assert "plugin" in str(response)
    assert "family-sym:" in str(response)


def test_family_stdio_end_to_end(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition], tmp_path: Path
) -> None:
    """Exercise family startup and retrieval through a real MCP stdio session.

    Parameters
    ----------
    family_setup : tuple
        Independent indexed workspace fixture.
    tmp_path : pathlib.Path
        Isolated child registry configuration root.

    Returns
    -------
    None
        Client initialization, schemas, origin, links, and source evidence pass.
    """
    manifest, registry, _ = family_setup
    child_registry = WorkspaceRegistry(
        tmp_path / "xdg" / "codira" / "workspaces", tmp_path / "child-state"
    )
    for definition in registry.list_definitions():
        child_registry.add(definition)

    async def exercise() -> None:
        """Assert deterministic family facts across the actual MCP transport.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Child process closes after the client session completes.
        """
        parameters = StdioServerParameters(
            command=str(Path(sys.executable).with_name("codira-mcp")),
            args=["--family", str(manifest)],
            env={"XDG_CONFIG_HOME": str(tmp_path / "xdg")},
        )
        async with (
            stdio_client(parameters) as streams,
            ClientSession(*streams) as session,
        ):
            async with asyncio.timeout(20):
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {
                    "capabilities",
                    "index_status",
                    "context_for_task",
                    "symbol",
                    "references",
                    "symbol_evidence",
                }
                symbols = await session.call_tool("symbol", {"name": "helper"})
                assert not symbols.isError
                assert symbols.structuredContent is not None
                items = _items(symbols.structuredContent)
                assert {item["repository"] for item in items} == {"core", "plugin"}
                evidence = await session.call_tool(
                    "symbol_evidence", {"identity": items[0]["identity"]}
                )
                assert not evidence.isError
                assert evidence.structuredContent is not None
                assert "return 42" in str(evidence.structuredContent)
                links = await session.call_tool("references", {"name": "caller"})
                assert not links.isError
                assert links.structuredContent is not None
                assert len(_items(links.structuredContent)) == 1
                context = await session.call_tool(
                    "context_for_task", {"query": "helper"}
                )
                assert not context.isError
                assert context.structuredContent is not None
                assert {
                    item["repository"] for item in _items(context.structuredContent)
                } == {"core", "plugin"}

    asyncio.run(exercise())


def test_family_configuration_and_startup_routing_are_bound(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition],
) -> None:
    """Bind continuations to configuration and keep startup routing immutable.

    Parameters
    ----------
    family_setup : tuple
        Independent indexed workspace fixture.

    Returns
    -------
    None
        Config edits invalidate cursors; unregistering does not retarget a server.
    """
    manifest, registry, family = family_setup
    runtime = FamilyRuntime(family)
    response = runtime.query("symbol", "helper", limit=1)
    cursor = cast("str", cast("dict[str, object]", response["page"])["next_cursor"])
    member = family.members[0]
    assert member.workspace is not None and member.workspace.config_file is not None
    config_file = member.workspace.config_file
    config_file.write_text(
        config_file.read_text(encoding="utf-8").replace(
            "batch_size = 8", "batch_size = 12"
        ),
        encoding="utf-8",
    )
    with pytest.raises(FamilyError, match="cursor does not match"):
        runtime.query("symbol", "helper", cursor=cursor, limit=1)
    registry.remove("plugin")
    assert len(_items(runtime.query("symbol", "helper"))) == 2
    reloaded = FamilyRuntime(load_family(manifest, registry=registry))
    with pytest.raises(FamilyError, match="not registered"):
        reloaded.query("symbol", "helper")
    assert len(_items(reloaded.query("symbol", "helper", allow_partial=True))) == 1


@pytest.mark.parametrize("state", ["updating", "failed", "partial", "empty"])
def test_family_unusable_generations_fail_explicitly(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition], state: str
) -> None:
    """Exclude every unusable publication state under explicit partial mode.

    Parameters
    ----------
    family_setup : tuple
        Indexed workspace fixture.
    state : str
        Unusable generation variant.

    Returns
    -------
    None
        Strict reads fail; partial reads preserve the other member's results.
    """
    family = family_setup[2]
    member = family.members[0]
    with member_scope(member) as adapter:
        store = IndexGenerationStore(adapter.root)
        record = store.read()
        assert record is not None
        if state == "partial":
            record = replace(record, partial=True)
        elif state == "empty":
            record = replace(record, indexed_file_count=0)
        else:
            from codira.index_generation import IndexGenerationState

            record = replace(record, state=cast("IndexGenerationState", state))
        store.write(record)
    runtime = FamilyRuntime(family)
    with pytest.raises(FamilyError, match="incomplete"):
        runtime.query("symbol", "helper")
    assert [
        item["repository"]
        for item in _items(runtime.query("symbol", "helper", allow_partial=True))
    ] == ["plugin"]


def test_family_rejects_shared_index_state(
    family_setup: tuple[Path, WorkspaceRegistry, FamilyDefinition],
) -> None:
    """Reject workspace aliases that would overwrite another member's index.

    Parameters
    ----------
    family_setup : tuple
        Independent registered workspace fixture.

    Returns
    -------
    None
        Unsafe shared state is rejected before family indexing can write.
    """
    manifest, registry, family = family_setup
    assert family.members[0].workspace is not None
    plugin = registry.show("plugin")
    registry.update(replace(plugin, state_root=family.members[0].workspace.state_root))
    with pytest.raises(FamilyError, match="distinct repository and index-state roots"):
        load_family(manifest, registry=registry)


def test_family_is_discoverable_in_cli_capabilities() -> None:
    """Advertise family operations in the existing CLI capability contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Machine-readable discovery and human CLI help include the family surface.
    """
    from codira.capabilities import COMMAND_CONTRACTS
    from codira.cli_parser import build_parser

    contract = COMMAND_CONTRACTS["family"]
    assert contract["intent"] == "local_multi_repository_index_federation"
    operations = cast(
        "dict[str, object]",
        cast("dict[str, object]", contract["subcommands"])["operations"],
    )
    assert set(cast("list[str]", operations["modes"])) == {
        "index",
        "status",
        "validate",
        "ctx",
        "sym",
        "refs",
        "evidence",
    }
    assert "family" in build_parser().format_help()
