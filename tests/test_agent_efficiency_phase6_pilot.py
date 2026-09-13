"""Test the non-billed Phase 6 pilot launcher contract."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from scripts.run_agent_efficiency_phase6_pilot import build_pilot_plan, main

if TYPE_CHECKING:
    from pathlib import Path


def _manifest() -> dict[str, object]:
    """Build one schema-valid public campaign manifest.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Minimal campaign identity and enforceable execution ceilings.
    """

    return {
        "schema_version": "1.0",
        "campaign_id": "pilot-001",
        "fixture_fingerprint": "a" * 64,
        "task_fingerprints": ["b" * 64, "c" * 64, "d" * 64],
        "budgets": {
            "max_total_tokens": 80000,
            "max_output_tokens": 12000,
            "timeout_seconds": 600,
        },
        "visibility": "public",
    }


def test_build_pilot_plan_has_three_complete_pairs() -> None:
    """Produce six deterministic attempts for the approved pilot cardinality.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover pair completeness and no execution authorization.
    """

    plan = build_pilot_plan(
        _manifest(), ("symbols-001", "patch-001", "documentation-001"), 7
    )
    assert plan["scheduled_execution_count"] == 6
    assert plan["execution_authorized"] is False
    attempts = plan["attempts"]
    assert isinstance(attempts, list)
    assert len(attempts) == 6


def test_pilot_launcher_rejects_execution_before_manifest_approval(
    tmp_path: Path,
) -> None:
    """Fail closed when an operator attempts paid execution prematurely.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary public manifest location.

    Returns
    -------
    None
        The launcher returns its deterministic disallowed-execution status.
    """

    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert (
        main(
            [
                "--campaign-manifest",
                str(manifest),
                "--task-id",
                "symbols-001",
                "--task-id",
                "patch-001",
                "--task-id",
                "documentation-001",
                "--seed",
                "7",
                "--execute",
            ]
        )
        == 2
    )


def test_pilot_launcher_rejects_wrong_task_cardinality(tmp_path: Path) -> None:
    """Reject any requested pilot other than three independent pairs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary public manifest location.

    Returns
    -------
    None
        The launcher returns its deterministic invalid-plan status.
    """

    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert (
        main(
            [
                "--campaign-manifest",
                str(manifest),
                "--task-id",
                "symbols-001",
                "--task-id",
                "patch-001",
                "--seed",
                "7",
            ]
        )
        == 2
    )
