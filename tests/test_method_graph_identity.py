"""Protect canonical method identities across inventory and relation queries.

Parameters
----------
None

Returns
-------
None
    Defines SQLite and DuckDB behavioural regressions.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from codira.cli import main
from codira.indexer import index_repo
from codira.mcp.adapter import MCPAdapter
from codira.query.exact import (
    EdgeQueryRequest,
    find_call_edges,
    find_callable_refs,
    symbol_inventory,
)


@pytest.fixture(params=["sqlite", "duckdb"])
def method_repository(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """Index methods sharing short names and receiver declaration lines.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and state directory.
    request : pytest.FixtureRequest
        Selected structural backend.

    Returns
    -------
    pathlib.Path
        Indexed fixture repository.
    """
    state = tmp_path / ".codira"
    state.mkdir()
    (state / "config.toml").write_text(
        f'config_version = 2\n[backend]\nname = "{request.param}"\n[embeddings]\nenabled = false\nsimilarity_index = "exact"\n',
        encoding="utf-8",
    )
    (tmp_path / "sample.py").write_text(
        "def helper():\n    return 1\n\n"
        "class Alpha:\n"
        "    def run(self):\n        helper()\n        return helper\n"
        "    def invoke(self):\n        return self.run()\n\n"
        "class Beta:\n"
        "    def run(self):\n        return helper()\n\n"
        "def registry():\n    return Alpha.run\n",
        encoding="utf-8",
    )
    for receiver in ("A", "B"):
        (tmp_path / f"{receiver.lower()}.go").write_text(
            f"package chi\ntype {receiver} struct {{ Values []int }}\n"
            f"func (s *{receiver}) Add() {{ s.Values = append(s.Values, 1) }}\n",
            encoding="utf-8",
        )
    result = index_repo(tmp_path)
    assert result.failed == 0
    return tmp_path


def test_inventory_keeps_same_named_methods_and_graph_counts(
    method_repository: Path,
) -> None:
    """Keep receiver-qualified methods distinct and expose stored edge counts.

    Parameters
    ----------
    method_repository : pathlib.Path
        Indexed mixed-language fixture.

    Returns
    -------
    None
        Canonical identities and metric assertions pass.
    """
    rows = {(x.module, x.name): x for x in symbol_inventory(method_repository)}
    alpha = rows[("sample", "Alpha.run")]
    beta = rows[("sample", "Beta.run")]
    assert alpha.calls_out.total == beta.calls_out.total == 1
    assert alpha.calls_in.total == 1
    assert alpha.refs_out.total == alpha.refs_in.total == 1
    assert rows[("chi", "(s *A).Add")].calls_out.total == 1
    assert rows[("chi", "(s *B).Add")].calls_out.total == 1


def test_relation_aliases_keep_qualified_owners_and_filters(
    method_repository: Path,
) -> None:
    """Resolve short names without dropping methods, modules or prefixes.

    Parameters
    ----------
    method_repository : pathlib.Path
        Indexed mixed-language fixture.

    Returns
    -------
    None
        Qualified and short-name query assertions pass.
    """
    rows = find_call_edges(EdgeQueryRequest(method_repository, "run", module="sample"))
    assert {x[1] for x in rows} == {"Alpha.run", "Beta.run"}
    assert len(find_call_edges(EdgeQueryRequest(method_repository, "Alpha.run"))) == 1
    assert not find_call_edges(EdgeQueryRequest(method_repository, "run", module="chi"))
    assert not find_call_edges(
        EdgeQueryRequest(method_repository, "run", prefix="a.go")
    )
    incoming = find_call_edges(
        EdgeQueryRequest(method_repository, "run", incoming=True)
    )
    assert {(x[1], x[3]) for x in incoming} == {("Alpha.invoke", "Alpha.run")}
    refs = find_callable_refs(EdgeQueryRequest(method_repository, "run"))
    assert {(x[1], x[3]) for x in refs} == {("Alpha.run", "helper")}
    incoming_refs = find_callable_refs(
        EdgeQueryRequest(method_repository, "run", incoming=True)
    )
    assert {(x[1], x[3]) for x in incoming_refs} == {("registry", "Alpha.run")}
    go_rows = find_call_edges(EdgeQueryRequest(method_repository, "Add", module="chi"))
    assert {x[1] for x in go_rows} == {"(s *A).Add", "(s *B).Add"}
    filtered = find_call_edges(
        EdgeQueryRequest(method_repository, "Add", prefix="b.go")
    )
    assert {x[1] for x in filtered} == {"(s *B).Add"}


def test_cli_and_mcp_use_the_same_method_identities(
    method_repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose canonical inventory names and alias lookup through both APIs.

    Parameters
    ----------
    method_repository : pathlib.Path
        Indexed mixed-language fixture.
    capsys : pytest.CaptureFixture[str]
        CLI output capture.
    monkeypatch : pytest.MonkeyPatch
        Installed CLI argument selection.

    Returns
    -------
    None
        CLI and direct MCP adapter regressions pass.
    """
    monkeypatch.setattr(
        sys, "argv", ["codira", "symlist", "--path", str(method_repository), "--json"]
    )
    assert main() == 0
    inventory = json.loads(capsys.readouterr().out)
    assert {"sample:Alpha.run", "sample:Beta.run"} <= {
        x["id"] for x in inventory["symbols"]
    }
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "calls", "run", "--path", str(method_repository), "--json"],
    )
    assert main() == 0
    calls = json.loads(capsys.readouterr().out)
    assert {x["caller_name"] for x in calls["results"]} == {"Alpha.run", "Beta.run"}
    adapter = MCPAdapter(method_repository)
    result = cast("dict[str, object]", adapter.callees("run")["result"])
    callees = cast("list[dict[str, object]]", result["calls"])
    assert {x["caller_name"] for x in callees} == {"Alpha.run", "Beta.run"}
    references = cast(
        "dict[str, object]", adapter.references("run", direction="incoming")["result"]
    )
    assert len(cast("list[object]", references["references"])) == 1
