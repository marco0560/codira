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
from typing import cast

from jsonschema import validate  # type: ignore[import-untyped]

from codira.indexer import index_repo
from codira.query.context import context_for
from codira.storage import init_db


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


def test_context_output_matches_schema(tmp_path: Path) -> None:
    """
    Validate that JSON output of context_for conforms to the JSON schema.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest. The fixture is unused but
        retained for symmetry with the companion schema test.

    Returns
    -------
    None
        The test asserts schema conformance for the populated case.

    Notes
    -----
    This is a structural contract test that keeps the schema and renderer in
    sync and prevents silent drift in the JSON output shape.
    """
    root = Path.cwd()

    schema = _load_schema(root)
    init_db(root)
    index_repo(root)

    # Use a stable query that always produces results
    output = context_for(
        root,
        "validate docstring",
        as_json=True,
        explain=True,
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
    assert "include_graph" in expansion


def test_context_no_matches_schema(tmp_path: Path) -> None:
    """
    Validate schema compliance for the 'no_matches' case.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest. The fixture is unused but
        retained for interface consistency with the companion test.

    Returns
    -------
    None
        The test asserts schema conformance for the no-match case.
    """
    root = Path.cwd()
    schema = _load_schema(root)
    init_db(root)
    index_repo(root)

    output = context_for(
        root,
        "zzzzzzzzzzzzzzzzzzzzzz",  # unlikely to match anything
        as_json=True,
        explain=True,
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
    assert "include_graph" in expansion
