"""Schema contract tests for JSON context rendering.

Responsibilities
----------------
- Load the stored JSON schema and compare `context_for` output in both populated and no-match scenarios.
- Assert schema properties such as planner metadata, merge diagnostics, and diversity/explain payloads.

Design principles
-----------------
Contract tests keep the schema usage deterministic so renderer changes must intentionally update the schema.

Architectural role
------------------
This module belongs to the **contract verification layer** supporting context rendering semantics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira_backend_sqlite.sqlite_storage import init_db
from jsonschema import validate  # type: ignore[import-untyped]

from codira import config as config_module
from codira.indexer import index_repo
from codira.query.context import ContextRequest, context_for
from codira.registry import reset_plugin_registry_caches

if TYPE_CHECKING:
    import pytest


def _load_schema(root: Path) -> dict[str, object]:
    """
    Load the JSON schema used for context output validation.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the schema file.

    Returns
    -------
    dict[str, object]
        Parsed JSON schema document.
    """
    schema_path = root / "src" / "codira" / "schema" / "context.schema.json"
    return cast(
        "dict[str, object]",
        json.loads(schema_path.read_text(encoding="utf-8")),
    )


def _write_context_fixture(root: Path) -> None:
    """
    Write a small repository fixture for context schema validation.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root to populate.

    Returns
    -------
    None
        The fixture files and repo-local Codira config are written.
    """
    config_path = root / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[embeddings]\nenabled = false\n", encoding="utf-8")
    package_dir = root / "pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "sample.py").write_text(
        '"""Fixture module for context schema tests."""\n\n'
        "def validate_docstring(value: str) -> str:\n"
        '    """Return the provided value for schema context retrieval."""\n'
        "    return value\n",
        encoding="utf-8",
    )


def _isolate_config_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Redirect host-level Codira config paths into the pytest sandbox.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch path providers.
    tmp_path : pathlib.Path
        Temporary directory for test-owned config paths.

    Returns
    -------
    None
        Platform config path providers are patched in place.
    """
    monkeypatch.setattr(
        config_module,
        "user_config_path",
        lambda: tmp_path / "user-config" / "config.toml",
    )
    monkeypatch.setattr(
        config_module,
        "system_config_path",
        lambda: tmp_path / "system-config" / "config.toml",
    )
    reset_plugin_registry_caches()


def test_context_output_matches_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Validate that JSON output of context_for conforms to the JSON schema.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used as the indexed repository fixture.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate host config and pin the storage backend.

    Returns
    -------
    None
        The test asserts schema conformance for the populated case.

    Notes
    -----
    This is a structural contract test that keeps the schema and renderer in
    sync and prevents silent drift in the JSON output shape.
    """
    schema_root = Path.cwd()
    root = tmp_path

    _isolate_config_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("CODIRA_INDEX_BACKEND", "sqlite")
    schema = _load_schema(schema_root)
    _write_context_fixture(root)
    init_db(root)
    index_repo(root)

    # Use a stable query that always produces results
    output = context_for(
        ContextRequest(
            root=root,
            query="validate docstring",
            as_json=True,
            explain=True,
        )
    )

    data = json.loads(output)

    validate(instance=data, schema=schema)
    explain = cast("dict[str, object]", data["explain"])
    planner = cast("dict[str, object]", explain["planner"])
    assert "primary_intent" in planner
    assert "channels" in planner
    assert "include_doc_issues" in planner
    merge = cast("list[dict[str, object]]", explain["merge"])
    assert "channels" in merge[0]
    assert "families" in merge[0]
    assert "rrf_score" in merge[0]
    assert "evidence_bonus" in merge[0]
    assert "role_bonus" in merge[0]
    assert "merge_score" in merge[0]
    diversity = cast("dict[str, object]", explain["diversity"])
    assert "selected" in diversity
    assert "deferred" in diversity
    expansion = cast("dict[str, object]", explain["expansion"])
    assert "graph_budget" in expansion
    assert "include_graph" in expansion


def test_context_no_matches_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Validate schema compliance for the 'no_matches' case.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used as the indexed repository fixture.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate host config and pin the storage backend.

    Returns
    -------
    None
        The test asserts schema conformance for the no-match case.
    """
    schema_root = Path.cwd()
    root = tmp_path
    _isolate_config_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("CODIRA_INDEX_BACKEND", "sqlite")
    schema = _load_schema(schema_root)
    _write_context_fixture(root)
    init_db(root)
    index_repo(root)

    output = context_for(
        ContextRequest(
            root=root,
            query="zzzzzzzzzzzzzzzzzzzzzz",  # unlikely to match anything
            as_json=True,
            explain=True,
        )
    )

    data = json.loads(output)

    validate(instance=data, schema=schema)
    explain = cast("dict[str, object]", data["explain"])
    planner = cast("dict[str, object]", explain["planner"])
    assert "primary_intent" in planner
    assert "channels" in planner
    if "merge" in explain:
        merge = cast("list[dict[str, object]]", explain["merge"])
        if merge:
            assert "channels" in merge[0]
            assert "families" in merge[0]
            assert "rrf_score" in merge[0]
            assert "evidence_bonus" in merge[0]
            assert "role_bonus" in merge[0]
            assert "merge_score" in merge[0]
    diversity = cast("dict[str, object]", explain["diversity"])
    assert "selected" in diversity
    assert "deferred" in diversity
    expansion = cast("dict[str, object]", explain["expansion"])
    assert "graph_budget" in expansion
    assert "include_graph" in expansion
