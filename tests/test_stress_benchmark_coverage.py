"""Protect coverage cohorts across local benchmark CLI, MCP and daemon probes.

Parameters
----------
None

Returns
-------
None
    Offline fixtures retain failures and never launch a corpus campaign.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts import run_test_material_benchmarks as runner


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [
        ({"usable": True, "partial": False, "complete": False}, True),
        ({"usable": True, "partial": True, "complete": False}, True),
        ({"usable": True, "partial": False, "complete": True}, False),
        ({"usable": False, "partial": True, "complete": False}, False),
        ({"state": "ready", "partial": False, "coverage_complete": False}, True),
        ({"state": "ready", "partial": True, "coverage_complete": True}, True),
        ({"state": "ready", "partial": False, "coverage_complete": True}, False),
        ({}, False),
    ],
)
def test_coverage_gaps_include_failure_free_and_daemon_generations(
    coverage: dict[str, Any], expected: bool
) -> None:
    """Treat known coverage gaps independently of failed selected files.

    Parameters
    ----------
    coverage : dict
        Real CLI or generation-record field shapes.
    expected : bool
        Whether a usable measurement belongs to the partial cohort.

    Returns
    -------
    None
        CLI and daemon predicates preserve the same completeness meaning.
    """
    assert runner.coverage_is_partial(coverage) is expected


@pytest.mark.parametrize(
    ("usable", "complete", "tool_error", "status", "cohort"),
    [
        (True, True, False, "passed", "complete_index"),
        (True, False, False, "partial", "partial_coverage"),
        (True, False, True, "failed", "partial_coverage"),
        (False, False, False, "unusable", "unusable_index"),
        (False, False, True, "failed", "unusable_index"),
    ],
)
def test_mcp_coverage_cohort_preserves_errors_and_index_usability(
    usable: bool, complete: bool, tool_error: bool, status: str, cohort: str
) -> None:
    """Keep protocol errors distinct from incomplete source coverage.

    Parameters
    ----------
    usable : bool
        Availability of queryable indexed content.
    complete : bool
        Repository coverage flag independent of selected-file failures.
    tool_error : bool
        Actual MCP error flag.
    status : str
        Expected operational classification.
    cohort : str
        Expected measurement cohort.

    Returns
    -------
    None
        Timing eligibility and failure precedence match the source contracts.
    """
    coverage = {
        "usable": usable,
        "partial": False,
        "complete": complete,
        "failed_file_count": 0,
    }
    responses = [{"tool": "symbols", "is_error": tool_error, "response": {}}]
    result = runner.classify_mcp_outcome(responses, coverage)
    assert result["status"] == status
    assert result["comparison_group"] == cohort
    assert result["timing_valid"] is (status == "passed")
    assert result["partial_timing_valid"] is (status == "partial")
    assert result["index_coverage"] == coverage


def test_mcp_family_retains_earlier_incomplete_member_coverage() -> None:
    """Retain a family member's gaps when later tools report complete coverage.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The final response cannot erase previously observed partial coverage.
    """
    complete = {"usable": True, "partial": False, "complete": True}
    incomplete = {"usable": True, "partial": False, "complete": False}
    responses: list[dict[str, Any]] = [
        {"tool": "symbols", "response": {"provenance": {"index_coverage": incomplete}}},
        {"tool": "arch", "response": {"provenance": {"index_coverage": complete}}},
        {"tool": "docs", "excluded": "embedding prerequisites unavailable"},
    ]
    result = runner.classify_mcp_outcome(responses, complete)
    assert result["status"] == "partial"
    assert result["comparison_group"] == "partial_coverage"
    assert not result["timing_valid"]


def test_mcp_semantic_partial_and_cli_empty_results_remain_partial() -> None:
    """Retain semantic limits and successful no-match results as separate facts.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Empty results and semantic restrictions never imply complete coverage.
    """
    complete = {"usable": True, "partial": False, "complete": True}
    result = runner.classify_mcp_outcome(
        [{"tool": "references", "response": {"result": {"status": "partial"}}}],
        complete,
    )
    assert result["status"] == "partial"
    empty = runner.classify_sample(
        ["codira", "refs", "leaf", "--json"],
        json.dumps(
            {
                "status": "no_matches",
                "index_coverage": {"usable": True, "partial": False, "complete": False},
            }
        ),
        "",
        1,
    )
    assert empty["status"] == "partial_empty"
    assert empty["partial_timing_valid"]


def test_unusable_cli_metadata_never_enters_complete_comparisons() -> None:
    """Reject unusable content even if a process reports an operational success.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Query usability takes precedence over its successful exit code.
    """
    result = runner.classify_sample(
        ["codira", "refs", "name", "--json"],
        json.dumps(
            {"status": "ok", "index_coverage": {"usable": False, "partial": True}}
        ),
        "",
        0,
    )
    assert result["status"] == "unusable"
    assert result["comparison_group"] == "unusable_index"
    assert not result["timing_valid"]
    assert not result["partial_timing_valid"]
