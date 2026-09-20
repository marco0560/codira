"""Test the one-request Phase 6 calibration launcher contract."""

from __future__ import annotations

import pytest

from scripts.run_agent_efficiency_phase6_calibration import calibration_attempt
from scripts.run_agent_efficiency_phase6_pilot import (
    PilotLauncherError,
    execution_controls,
)


def _calibration_manifest() -> dict[str, object]:
    """Build the smallest valid one-request calibration manifest.

    Returns
    -------
    dict[str, object]
        Immutable task, route, and single-attempt accounting controls.
    """

    return {
        "campaign_id": "calibration-001",
        "fixture_fingerprints": {"codira-public": "a" * 64},
        "task_fingerprints": {"symbols-001": "b" * 64},
        "task_fixture_ids": {"symbols-001": "codira-public"},
        "budgets": {
            "max_total_tokens": 200000,
            "max_output_tokens": 32000,
            "timeout_seconds": 900,
        },
        "provider": {
            "model": "deepseek/deepseek-v4.1-flash",
            "reasoning_effort": "none",
            "max_prompt_usd_per_million": 0.15,
            "max_completion_usd_per_million": 0.6,
        },
        "accounting": {
            "max_daily_spend_usd": 6,
            "max_estimated_attempt_spend_usd": 0.15,
            "max_estimated_pilot_spend_usd": 0.15,
            "max_response_requests_per_attempt": 1,
        },
    }


def test_calibration_builds_one_assisted_attempt() -> None:
    """Bind calibration to one Codira-MCP request, never a paired schedule."""

    attempt = calibration_attempt(_calibration_manifest())

    assert attempt.task_id == "symbols-001"
    assert attempt.assistance_mode == "codira-mcp"
    assert attempt.attempt_id == "symbols-001-calibration-codira-mcp"


def test_calibration_allows_one_attempt_accounting() -> None:
    """Accept the one-request cap while the pilot default remains six requests."""

    controls = execution_controls(_calibration_manifest(), scheduled_attempts=1)

    assert controls.max_pilot_spend == 0.15
    with pytest.raises(PilotLauncherError, match="accounting"):
        execution_controls(_calibration_manifest())


def test_calibration_rejects_multiple_task_bindings() -> None:
    """Reject a manifest that could turn calibration into a campaign."""

    manifest = _calibration_manifest()
    task_hashes = manifest["task_fingerprints"]
    assert isinstance(task_hashes, dict)
    task_hashes["patch-001"] = "c" * 64

    with pytest.raises(PilotLauncherError, match="exactly one bound task"):
        calibration_attempt(manifest)
