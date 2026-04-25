"""Tests for the ``codira symlist`` symbol inventory command.

Responsibilities
----------------
- Build compact fixtures with call and callable-reference graph data.
- Verify deterministic inventory ordering, filtering, and JSON shape.
- Protect the default test-module exclusion contract.

Design principles
-----------------
Fixtures remain small and explicit so inventory metric failures point to either
graph aggregation or CLI rendering.

Architectural role
------------------
This module belongs to the **CLI verification layer** for exact index
inspection commands.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from codira.cli import main
from codira.indexer import index_repo
from codira.query.exact import symbol_inventory
from codira.storage import init_db

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write_symlist_fixture(root: Path) -> None:
    """
    Write a package with deterministic symbol and graph relationships.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root to populate.

    Returns
    -------
    None
        The fixture files are written under ``root``.
    """
    pkg = root / "pkg"
    tests = root / "tests"
    pkg.mkdir()
    tests.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text(
        '"""Symbol inventory fixture."""\n'
        "\n"
        "def helper():\n"
        '    """Return a constant."""\n'
        "    return 1\n"
        "\n"
        "def dynamic(callback):\n"
        '    """Exercise unresolved call counting."""\n'
        "    callback()\n"
        "    return 1\n"
        "\n"
        "def caller():\n"
        '    """Call local helpers."""\n'
        "    helper()\n"
        "    return dynamic(helper)\n"
        "\n"
        "def registry():\n"
        '    """Return a callable reference."""\n'
        "    return helper\n",
        encoding="utf-8",
    )
    (pkg / "b.py").write_text(
        '"""Second module for ordering and prefix tests."""\n'
        "\n"
        "def alpha():\n"
        '    """Return a constant."""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_sample.py").write_text(
        '"""Test module that is excluded by default."""\n'
        "\n"
        "def test_helper():\n"
        '    """Sample test symbol."""\n'
        "    assert True\n",
        encoding="utf-8",
    )


def _index_fixture(root: Path) -> None:
    """
    Initialize and index the symbol inventory fixture.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root to index.

    Returns
    -------
    None
        The repository-local index is created under ``root``.
    """
    _write_symlist_fixture(root)
    init_db(root)
    index_repo(root)


def test_symbol_inventory_orders_filters_and_limits(tmp_path: Path) -> None:
    """
    Verify default ordering, test exclusion, prefix filtering, and limit.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts public inventory rows.
    """
    _index_fixture(tmp_path)

    rows = symbol_inventory(tmp_path, prefix="pkg/a.py", limit=3)
    identities = [(row.module, row.name) for row in rows]

    assert identities == [
        ("pkg.a", "caller"),
        ("pkg.a", "dynamic"),
        ("pkg.a", "helper"),
    ]
    assert all(not row.module.startswith("tests") for row in rows)
    prefix_rows = symbol_inventory(tmp_path, prefix="pkg/b.py")
    assert [row.module for row in prefix_rows] == ["pkg.b", "pkg.b"]
    assert [row.name for row in prefix_rows] == ["alpha", "pkg.b"]


def test_symbol_inventory_counts_unresolved_and_incoming_edges(
    tmp_path: Path,
) -> None:
    """
    Count call and callable-reference metrics for selected symbols.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts total and unresolved edge metrics.
    """
    _index_fixture(tmp_path)

    rows = {
        (row.module, row.name): row
        for row in symbol_inventory(tmp_path, include_tests=True)
    }

    dynamic = rows[("pkg.a", "dynamic")]
    helper = rows[("pkg.a", "helper")]
    registry = rows[("pkg.a", "registry")]

    assert dynamic.calls_out.total == 1
    assert dynamic.calls_out.unresolved == 1
    assert helper.calls_in.total == 1
    assert helper.calls_in.unresolved == 0
    assert registry.refs_out.total == 1
    assert registry.refs_out.unresolved == 0
    assert helper.refs_in.total == 1


def test_symlist_json_schema_and_include_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Render the stable JSON schema and include test modules on request.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to replace process arguments.
    capsys : pytest.CaptureFixture[str]
        Pytest fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the JSON payload shape and selected metrics.
    """
    _index_fixture(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "symlist",
            "--path",
            str(tmp_path),
            "--include-tests",
            "--json",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    symbols = {symbol["id"]: symbol for symbol in payload["symbols"]}

    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "ok"
    assert "tests.test_sample:test_helper" in symbols
    assert symbols["pkg.a:dynamic"]["calls_out"] == {
        "total": 1,
        "unresolved": 1,
    }
    assert symbols["pkg.a:helper"]["refs_in"] == {"total": 1, "unresolved": 0}


def test_symlist_human_output_is_grouped_by_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Render compact grouped human output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to replace process arguments.
    capsys : pytest.CaptureFixture[str]
        Pytest fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts module grouping and metric text.
    """
    _index_fixture(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "symlist",
            "--path",
            str(tmp_path),
            "--prefix",
            "pkg/a.py",
            "--limit",
            "1",
        ],
    )

    assert main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "pkg.a",
        "  caller  calls_out=2 (0 unresolved) calls_in=0 (0 unresolved) "
        "refs_out=0 (0 unresolved) refs_in=0 (0 unresolved)",
    ]
