"""Verify terminal explanations without changing retained machine outcomes.

Parameters
----------
None

Returns
-------
None
    Uses only offline receipts and simulated child output.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, TextIO
from unittest.mock import Mock

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from scripts import run_test_material_benchmarks as runner


@pytest.mark.parametrize(
    ("status", "evidence", "expected"),
    [
        (
            "partial",
            {
                "index_coverage": {
                    "complete": False,
                    "failed_file_count": 0,
                    "issue_count": 7,
                }
            },
            "partial (failed files=0; coverage issues=7; coverage incomplete)",
        ),
        (
            "partial_empty",
            {"index_coverage": {"complete": False, "failed_file_count": 1}},
            "partial_empty (no matches; failed files=1; coverage incomplete)",
        ),
        (
            "partial",
            {"index_coverage": {"complete": True}},
            "partial (analysis limited)",
        ),
        ("empty", {}, "empty (no matches)"),
        (
            "failed",
            {"stderr_diagnostic": "ValueError: bad config"},
            "failed (ValueError: bad config)",
        ),
        (
            "timeout",
            {"reason": "outer process budget exceeded"},
            "timeout (outer process budget exceeded)",
        ),
        (
            "excluded",
            {"reason": "failed files unchanged"},
            "excluded (failed files unchanged)",
        ),
        (
            "passed",
            {
                "optional_artifacts": {
                    "svg": {
                        "available": False,
                        "warning": "SVG timed out after 180 seconds",
                    }
                }
            },
            "passed (SVG timed out after 180 seconds)",
        ),
    ],
)
def test_outcome_explanation_keeps_machine_status_and_actual_reason(
    status: str, evidence: dict[str, Any], expected: str
) -> None:
    """Distinguish coverage, no matches, command failure and optional rendering.

    Parameters
    ----------
    status : str
        Stored status enum.
    evidence : dict
        Coverage and error details without inventing unknown counts.
    expected : str
        Human-readable terminal outcome.

    Returns
    -------
    None
        Formatting leaves the input receipt unchanged.
    """
    original = json.dumps(evidence, sort_keys=True)
    assert runner.outcome_description(status, evidence) == expected
    assert json.dumps(evidence, sort_keys=True) == original


def test_plain_workspace_read_is_annotated_before_progress_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Print actual partial coverage even when a command emits plain text.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned simulated campaign directory.
    monkeypatch : pytest.MonkeyPatch
        Replaces child execution with successful retained plain text.
    capsys : pytest.CaptureFixture[str]
        Terminal progress capture.

    Returns
    -------
    None
        Progress and persisted outcomes agree before a caller inspects the result.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    campaign = runner.Campaign(manifest, tmp_path / "run", False)
    campaign.member_coverage["fixture"] = {
        "usable": True,
        "partial": False,
        "complete": False,
        "failed_file_count": 0,
    }

    def simulate(
        argv: list[str], *, stdout: TextIO, **options: object
    ) -> SimpleNamespace:
        """Retain plain output without launching a process.

        Parameters
        ----------
        argv : list of str
            Unused command descriptor.
        stdout : typing.TextIO
            Retained output destination.
        **options : object
            Unused process options.

        Returns
        -------
        types.SimpleNamespace
            Successful simulated process.
        """
        stdout.write("Generated context prompt\n")
        return SimpleNamespace(returncode=0, wait=Mock(return_value=0))

    monkeypatch.setattr(subprocess, "Popen", simulate)
    result = campaign.cli(
        "primary/fixture/ctx-prompt", "fixture", ["ctx", "query", "--prompt"]
    )
    output = capsys.readouterr().out
    assert "partial (failed files=0; coverage incomplete)" in output
    assert "remaining" not in output
    assert result["status"] == "partial"
    assert (
        json.loads(
            (campaign.root / "stages" / result["key"] / "result.json").read_text()
        )["status"]
        == "partial"
    )


def test_reported_coverage_count_is_not_invented_during_embeddings_only() -> None:
    """Preserve known scope counts without replacing structural gaps by zero.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Coverage scans expose counts; embedding-only outputs do not erase them.
    """
    coverage = {"usable": True, "partial": False, "complete": False}
    scan = runner.classify_sample(
        ["codira", "cov", "--json"],
        json.dumps(
            {
                "status": "ok",
                "results": [{"reason": "unsupported"}],
                "index_coverage": coverage,
            }
        ),
        "",
        0,
    )
    assert scan["index_coverage"]["issue_count"] == 1
    embeddings = runner.classify_sample(
        ["codira", "index", "--embeddings-only", "--json"],
        json.dumps(
            {
                "status": "ok",
                "summary": {"failed": 0},
                "coverage_issues": [],
                "index_coverage": coverage,
            }
        ),
        "",
        0,
    )
    assert "issue_count" not in embeddings["index_coverage"]
