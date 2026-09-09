"""Verify Phase 3 public corpus admission and source-leak controls."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.agent_efficiency.contracts import ContractError
from scripts.agent_efficiency.corpus import (
    load_admitted_documents,
    load_task_oracles,
    verify_source_fix_excluded,
)

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "benchmarks" / "agent-efficiency"


def test_public_phase3_records_are_complete_and_cross_referenced() -> None:
    """Load exactly the admitted fixtures and six coherent task/oracle pairs.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The public records identify all required fixture/task/oracle relationships.
    """

    fixtures = load_admitted_documents(BENCHMARK_ROOT / "fixtures")
    pairs = load_task_oracles(
        BENCHMARK_ROOT / "tasks", BENCHMARK_ROOT / "oracles", fixtures
    )
    assert {item["fixture_id"] for item in fixtures} == {
        "codira-public",
        "click-public",
        "picomatch-public",
    }
    assert {task["task_id"] for task, _ in pairs} == {
        "symbols-001",
        "impact-001",
        "localize-001",
        "patch-001",
        "architecture-001",
        "documentation-001",
    }


def test_source_fix_exclusion_rejects_git_metadata_and_commit_marker(
    tmp_path: Path,
) -> None:
    """Reject fixture exports exposing Git history or a protected commit identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary agent-visible fixture root.

    Returns
    -------
    None
        Both prohibited leak channels raise deterministic contract errors.
    """

    source_fix = "f58ca3e81424a35626c8a475eb59ab95589008ce"
    (tmp_path / ".git").mkdir()
    with pytest.raises(ContractError, match="Git metadata"):
        verify_source_fix_excluded(tmp_path, source_fix)
    (tmp_path / ".git").rmdir()
    (tmp_path / "README.md").write_text(source_fix, encoding="utf-8")
    with pytest.raises(ContractError, match="source-fix identity"):
        verify_source_fix_excluded(tmp_path, source_fix)
