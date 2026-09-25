"""Test deterministic, credential-free campaign construction."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.agent_efficiency.campaign_factory import (
    CampaignFactoryError,
    build_campaign,
    write_campaign_artifacts,
)


def _spec(stage: str, task_ids: list[str]) -> dict[str, object]:
    """Build one valid factory specification for frozen public fixtures."""

    result: dict[str, object] = {
        "schema_version": "1.0",
        "campaign_id": f"factory-{stage}-001",
        "stage": stage,
        "task_ids": task_ids,
        "budgets": {
            "max_total_tokens": 200000,
            "max_output_tokens": 32000,
            "timeout_seconds": 900,
        },
        "provider": {
            "name": "openrouter",
            "model": "deepseek/deepseek-v4.1-flash",
            "reasoning_effort": "none",
            "wire_api": "responses",
            "max_prompt_usd_per_million": 0.15,
            "max_completion_usd_per_million": 0.6,
        },
        "accounting": {
            "max_daily_spend_usd": 6,
            "max_estimated_attempt_spend_usd": 0.15,
            "max_estimated_pilot_spend_usd": 0.15 if stage == "calibration" else 0.9,
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
    if stage == "pilot":
        result["seed"] = 20260919
    return result


def test_factory_builds_one_assisted_calibration_attempt() -> None:
    """Generate frozen calibration bindings and exactly one request.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover calibration identity, bindings, and cardinality.
    """

    manifest, plan = build_campaign(
        _spec("calibration", ["symbols-001"]), Path("benchmarks/agent-efficiency")
    )

    task_fingerprints = manifest["task_fingerprints"]
    assert isinstance(task_fingerprints, dict)
    assert set(task_fingerprints) == {"symbols-001"}
    assert plan["scheduled_attempt_count"] == 1
    assert plan["attempts"] == [
        {
            "task_id": "symbols-001",
            "repetition": 1,
            "assistance_mode": "codira-mcp",
            "attempt_id": "symbols-001-calibration-codira-mcp",
            "pair_id": "symbols-001-calibration",
        }
    ]


def test_factory_builds_a_deterministic_six_request_pilot() -> None:
    """Require exactly three tasks and preserve paired schedule determinism.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover deterministic paired pilot construction.
    """

    specification = _spec("pilot", ["symbols-001", "patch-001", "documentation-001"])
    first = build_campaign(specification, Path("benchmarks/agent-efficiency"))
    second = build_campaign(specification, Path("benchmarks/agent-efficiency"))

    assert first == second
    assert first[1]["scheduled_attempt_count"] == 6


def test_factory_accounts_whole_session_tokens_once_per_attempt() -> None:
    """Bound a multi-continuation pilot by its whole-session token ceiling.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions distinguish session accounting from legacy multiplication.
    """

    specification = _spec("pilot", ["symbols-001", "patch-001", "documentation-001"])
    budgets = specification["budgets"]
    accounting = specification["accounting"]
    assert isinstance(budgets, dict)
    assert isinstance(accounting, dict)
    budgets["max_total_tokens"] = 240000
    accounting.update(
        {
            "max_total_tokens_scope": "whole-session",
            "max_response_requests_per_attempt": 10,
            "max_transport_attempts_per_response": 2,
            "max_estimated_attempt_spend_usd": 0.18,
            "max_estimated_pilot_spend_usd": 1.08,
        }
    )

    manifest, plan = build_campaign(specification, Path("benchmarks/agent-efficiency"))

    assert manifest["accounting"] == accounting
    assert plan["scheduled_attempt_count"] == 6


def test_factory_rejects_an_invalid_stage_cardinality() -> None:
    """Prevent a calibration from becoming an unreviewed campaign.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover fail-closed calibration cardinality.
    """

    with pytest.raises(CampaignFactoryError, match="calibration requires exactly 1"):
        build_campaign(
            _spec("calibration", ["symbols-001", "patch-001"]),
            Path("benchmarks/agent-efficiency"),
        )


def test_factory_rejects_a_fingerprint_for_the_wrong_runtime_profile() -> None:
    """Reject the image fingerprint when the campaign field means Codira profile.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The factory must fail before producing paid-stage artifacts.
    """

    specification = _spec("pilot", ["symbols-001", "patch-001", "documentation-001"])
    image_profile = "0" * 64
    codira_profile = hashlib.sha256(
        Path("scripts/agent_efficiency/benchmark-codira.toml").read_bytes()
    ).hexdigest()
    assert image_profile != codira_profile
    specification["runtime_profile_fingerprint"] = image_profile

    with pytest.raises(
        CampaignFactoryError,
        match="does not match the benchmark Codira profile",
    ):
        build_campaign(specification, Path("benchmarks/agent-efficiency"))

    specification["runtime_profile_fingerprint"] = codira_profile
    manifest, _ = build_campaign(specification, Path("benchmarks/agent-efficiency"))
    assert manifest["runtime_profile_fingerprint"] == codira_profile


def test_factory_refuses_to_overwrite_artifacts(tmp_path: Path) -> None:
    """Keep generated campaign evidence immutable after first creation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary destination for generated campaign artifacts.

    Returns
    -------
    None
        Assertions cover first-write success and overwrite rejection.
    """

    manifest, plan = build_campaign(
        _spec("calibration", ["symbols-001"]), Path("benchmarks/agent-efficiency")
    )
    output = tmp_path / "factory-calibration-001"

    manifest_path, plan_path = write_campaign_artifacts(output, manifest, plan)

    assert manifest_path.is_file()
    assert plan_path.is_file()
    with pytest.raises(CampaignFactoryError, match="already exists"):
        write_campaign_artifacts(output, manifest, plan)
