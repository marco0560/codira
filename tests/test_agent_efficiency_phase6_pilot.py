"""Test the non-billed Phase 6 pilot launcher contract."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_efficiency.contracts import load_document
from scripts.run_agent_efficiency_phase6_pilot import build_pilot_plan, main


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
        "fixture_fingerprints": {
            "codira-public": "a" * 64,
            "click-public": "b" * 64,
            "picomatch-public": "c" * 64,
        },
        "task_fingerprints": {
            "symbols-001": "d" * 64,
            "patch-001": "e" * 64,
            "documentation-001": "f" * 64,
        },
        "task_fixture_ids": {
            "symbols-001": "codira-public",
            "patch-001": "click-public",
            "documentation-001": "picomatch-public",
        },
        "budgets": {
            "max_total_tokens": 80000,
            "max_output_tokens": 12000,
            "timeout_seconds": 600,
        },
        "provider": {
            "name": "openrouter",
            "model": "openai/gpt-5.6-terra",
            "reasoning_effort": "medium",
            "wire_api": "responses",
            "max_prompt_usd_per_million": 2,
            "max_completion_usd_per_million": 12,
        },
        "accounting": {
            "max_daily_spend_usd": 2,
            "max_estimated_attempt_spend_usd": 0.3,
            "max_estimated_pilot_spend_usd": 1.8,
            "max_response_requests_per_attempt": 1,
        },
        "resource_controls": {
            "network": "none",
            "read_only_rootfs": True,
            "pids_limit": 512,
            "tmpfs_size_mib": 128,
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


def test_checked_in_pilot_manifest_has_three_frozen_fixture_bindings() -> None:
    """Load the approved pilot manifest and verify its complete dry-run plan.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The checked-in public manifest produces the six planned executions.
    """

    manifest = load_document(
        Path("benchmarks/agent-efficiency/phase6-pilot.json"), "campaign"
    )
    plan = build_pilot_plan(
        manifest, ("symbols-001", "patch-001", "documentation-001"), 7
    )
    assert plan["scheduled_execution_count"] == 6


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


def test_pilot_launcher_rejects_tasks_that_drift_from_manifest(tmp_path: Path) -> None:
    """Reject a three-task pilot whose identities differ from the manifest.

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
                "--task-id",
                "architecture-001",
                "--seed",
                "7",
            ]
        )
        == 2
    )
