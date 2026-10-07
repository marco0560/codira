"""Acceptance checks for C1-C5 and H1-H3 without paid provider access.

Parameters
----------
None

Returns
-------
None
    Public fixtures and deterministic quality regressions.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from codira.indexer import index_repo
from codira.mcp.adapter import MCPAdapter
from codira.mcp.contract import build_contract_document
from codira.mcp.server import create_server
from codira.query.classifier import classify_query
from codira.query.exact import find_symbol
from codira.registry import active_index_backend
from scripts.agent_efficiency.instrumentation import (
    paired_distribution,
    request_measurement,
)
from scripts.agent_efficiency.quality import (
    adjudicate_quality,
    grade_quality,
    write_blinded_packet,
)


def _index(root: Path) -> MCPAdapter:
    """Index a caller-provided public fixture.

    Parameters
    ----------
    root : pathlib.Path
        Fixture source directory.

    Returns
    -------
    codira.mcp.adapter.MCPAdapter
        Direct read-only adapter.
    """
    active_index_backend().initialize(root)
    index_repo(root)
    return MCPAdapter(root)


def test_causal_query_keeps_behavior_and_finds_source(tmp_path: Path) -> None:
    """Keep symptom intent and retrieve causal code ahead of generic options.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Public scratch fixture.

    Returns
    -------
    None
        Source and test evidence are recovered for prose and explicit queries.
    """
    (tmp_path / "marker.py").write_text(
        "from enum import Enum\nclass Marker(Enum):\n    UNSET = object()\n    def __reduce_ex__(self, protocol):\n        return self.__class__, (self.value,)\nUNSET = Marker.UNSET\n"
    )
    (tmp_path / "test_marker.py").write_text(
        "import pickle\nfrom marker import UNSET\ndef test_round_trip():\n    assert pickle.loads(pickle.dumps(UNSET)) is UNSET\n"
    )
    (tmp_path / "options.py").write_text(
        "def option_configuration():\n    return 'option default regression test'\n"
    )
    adapter = _index(tmp_path)
    query = "Diagnose pickling failure for unset option defaults and identify the regression test"
    assert classify_query(query).primary_intent == "behavior"
    response = adapter.context_for_task(query, limit=10, explain=True)
    items = cast(
        "list[dict[str, object]]",
        cast("dict[str, object]", response["result"])["items"],
    )
    assert any(item["name"] == "Marker" for item in items)
    assert any(item["name"] == "test_round_trip" for item in items)
    assert all(
        "confidence" not in item
        and item["score_kind"] == "heuristic_rank_not_probability"
        for item in items
    )
    assert "explain" in cast("dict[str, object]", response["result"])
    assert (
        classify_query("Find configuration options").primary_intent == "configuration"
    )
    assert classify_query("Write tests for render").primary_intent == "test"


def test_alias_owner_whole_source_and_stale_rejection(tmp_path: Path) -> None:
    """Resolve aliases and ambiguous owners, then verify expandable evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Scratch repository containing two method owners and an enum alias.

    Returns
    -------
    None
        Canonical targets remain case-sensitive and stale reads fail closed.
    """
    source = "from enum import Enum\nclass Marker(Enum):\n    UNSET = object()\n    def render(self):\n        return 42\nUNSET = Marker.UNSET\nclass Other:\n    def render(self):\n        return 43\n"
    path = tmp_path / "sample.py"
    path.write_text(source)
    adapter = _index(tmp_path)
    assert {row[2] for row in find_symbol(tmp_path, "UNSET")} == {
        "UNSET",
        "Marker.UNSET",
    }
    assert find_symbol(tmp_path, "unset") == []
    assert len(find_symbol(tmp_path, "render")) == 2
    assert len(find_symbol(tmp_path, "Marker.render")) == 1
    row = cast(
        "list[dict[str, object]]",
        cast("dict[str, object]", adapter.symbol("Marker")["result"])["symbols"],
    )[0]
    identity = str(row["identity"])
    expanded = cast("dict[str, object]", adapter.symbol_evidence(identity)["result"])
    assert "UNSET = object()" in str(expanded["source"])
    assert "return 42" in str(expanded["source"])
    assert expanded["start_line"] == 2 and expanded["end_line"] == 5
    assert cast("dict[str, object]", expanded["coverage"])["dynamic_complete"] is False
    path.write_text(source.replace("return 42", "return 44"))
    with pytest.raises(ValueError, match="changed since indexing"):
        adapter.symbol_evidence(identity)
    index_repo(tmp_path)
    with pytest.raises(ValueError, match="stale symbol identity"):
        adapter.symbol_evidence(identity)
    with pytest.raises(ValueError):
        adapter.symbol_evidence("sym:not-json")


def test_actual_schemas_match_caps_and_compact_status(tmp_path: Path) -> None:
    """Check actual model-visible parameters and measured compact output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Indexed public fixture.

    Returns
    -------
    None
        Advertised bounds/values agree and details remain available on demand.
    """
    (tmp_path / "sample.py").write_text("def helper():\n    return 42\n")
    adapter = _index(tmp_path)
    actual = asyncio.run(create_server(tmp_path).list_tools())
    declared = {
        str(tool["name"]): cast("dict[str, object]", tool["request_schema"])
        for tool in cast(
            "list[dict[str, object]]", build_contract_document(root=tmp_path)["tools"]
        )
    }
    assert {tool.name: tool.inputSchema for tool in actual} == declared
    assert all(
        "output_budget" not in cast("dict[str, object]", schema["properties"])
        for schema in declared.values()
    )
    assert len(json.dumps(adapter.index_status())) < len(
        json.dumps(adapter.index_status(detail=True))
    )
    assert len(json.dumps(adapter.capabilities())) < len(
        json.dumps(adapter.capabilities(detail=True))
    )
    assert "analyzer_inventory" not in cast(
        "dict[str, object]", adapter.symbol("helper")["freshness"]
    )


def test_quality_calibration_and_review_binding(tmp_path: Path) -> None:
    """Accept equivalent facts, reject counterclaims and trace review decisions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Destination for a blinded review packet.

    Returns
    -------
    None
        Good, incomplete and subtly wrong examples grade distinctly.
    """
    rubric = {
        "criteria": [
            {
                "id": "cause",
                "dimension": "causality",
                "accepted": [r"value.based enum", r"enum reconstructs.*value"],
                "counterclaims": [r"copy(?:ing)? fails"],
            },
            {
                "id": "successful-copy",
                "dimension": "correctness",
                "accepted": [r"copy(?:ing)? works", r"copies preserve identity"],
            },
            {
                "id": "explanation",
                "dimension": "completeness",
                "semantic": True,
                "requirement": "Explain fresh object equality failure and the requested operation distinctions.",
            },
        ]
    }
    good = "The enum reconstructs its member by value. A fresh object cannot match. Copies preserve identity."
    report = grade_quality(good, rubric)
    assert report["status"] == "review_required"
    assert (
        grade_quality("The value-based enum is responsible.", rubric)["status"]
        == "failed"
    )
    assert (
        grade_quality("Value-based enum; copying fails; copying works.", rubric)[
            "status"
        ]
        == "failed"
    )
    decisions = [
        {
            "id": identifier,
            "status": "supported",
            "evidence": good,
            "reason": "Meets the explicitly requested criterion.",
        }
        for identifier in ("cause", "successful-copy", "explanation")
    ]
    review = {
        "reviewer": "calibration-reference",
        "answer_sha256": report["answer_sha256"],
        "rubric_sha256": report["rubric_sha256"],
        "decisions": decisions,
    }
    judged = adjudicate_quality(good, rubric, review)
    assert judged["status"] == "passed" and judged["original"] == report
    with pytest.raises(ValueError, match="exact answer"):
        adjudicate_quality(good + "changed", rubric, review)
    destination = tmp_path / "blinded.json"
    write_blinded_packet(good, rubric, destination)
    assert set(json.loads(destination.read_text())) == {"answer", "rubric"}
    with pytest.raises(FileExistsError):
        write_blinded_packet(good, rubric, destination)


def test_overhead_measurement_and_paired_uncertainty() -> None:
    """Measure actual wire sizes without inventing token attribution.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Measurements are content-free and small-sample uncertainty is explicit.
    """
    payload = json.dumps(
        {
            "tools": [{"name": "symbol"}],
            "instructions": "private text",
            "input": "hello",
        }
    ).encode()
    measurement = request_measurement(payload)
    assert measurement["wire_bytes"] == len(payload)
    assert "private text" not in json.dumps(measurement)
    assert measurement["attributed_tokens"] is None
    assert paired_distribution([1])["mean_ci95"] is None
    assert paired_distribution([1, 2, 3]) == paired_distribution([1, 2, 3])
