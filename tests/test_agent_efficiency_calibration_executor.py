"""Test deterministic factory-backed calibration execution preparation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.agent_efficiency.campaign_factory import (
    build_campaign,
    write_campaign_artifacts,
)
from scripts.launch_agent_efficiency_calibration import (
    CalibrationLaunchError,
    load_launch,
    prepare_launch,
    runtime_state_root,
    tmux_command,
    verify_prepared_launch,
)


def _campaign_directory(
    tmp_path: Path, task_id: str = "symbols-001"
) -> tuple[Path, Path]:
    """Create one immutable generated calibration campaign for executor tests.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.
    task_id : str, optional
        Frozen calibration task whose fixture binding is exercised.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path]
        Generated campaign directory and an existing fixture-source directory.
    """

    specification: dict[str, object] = {
        "schema_version": "1.0",
        "campaign_id": "executor-calibration-001",
        "stage": "calibration",
        "task_ids": [task_id],
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
            "max_estimated_pilot_spend_usd": 0.15,
            "max_response_requests_per_attempt": 1,
        },
        "resource_controls": {
            "network": "none",
            "read_only_rootfs": True,
            "pids_limit": 512,
            "tmpfs_size_mib": 128,
        },
        "runtime_image": "localhost/test@sha256:" + "a" * 64,
        "runtime_profile_fingerprint": hashlib.sha256(
            Path("scripts/agent_efficiency/benchmark-codira.toml").read_bytes()
        ).hexdigest(),
        "treatment_protocol": {
            "version": "mcp-required-v1",
            "codira_mcp_instruction": "Call Codira MCP before completing the task.",
        },
        "visibility": "public",
    }
    manifest, plan = build_campaign(specification, Path("benchmarks/agent-efficiency"))
    campaign_directory = tmp_path / "campaign"
    write_campaign_artifacts(campaign_directory, manifest, plan)
    fixture_source = Path.cwd()
    return campaign_directory, fixture_source


def test_prepare_claims_paths_before_tmux_command(tmp_path: Path) -> None:
    """Create durable state and logs before constructing the tmux command.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions prove the former missing-directory launch failure is impossible.
    """

    campaign_directory, fixture_source = _campaign_directory(tmp_path)
    execution_root = tmp_path / "execution"
    launch = load_launch(campaign_directory, execution_root, fixture_source, "podman")

    receipt = prepare_launch(launch)
    _, command = tmux_command(launch)

    assert receipt.is_file()
    assert runtime_state_root(launch).is_dir()
    assert runtime_state_root(launch) == execution_root / "state"
    assert (execution_root / "logs").is_dir()
    assert str(execution_root / "logs" / "calibration.log") in command
    assert str(execution_root / "calibration.exit") in command
    assert "codira-public=" + str((execution_root / "fixture").resolve()) in command


def test_tmux_command_uses_the_manifest_fixture_binding(tmp_path: Path) -> None:
    """Pass the factory-bound fixture ID rather than a Codira-only default.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.

    Returns
    -------
    None
        Patch calibration is launched with its frozen Click fixture identity.
    """

    campaign_directory, fixture_source = _campaign_directory(
        tmp_path, task_id="patch-001"
    )
    execution_root = tmp_path / "execution"
    launch = load_launch(campaign_directory, execution_root, fixture_source, "podman")

    _, command = tmux_command(launch)

    assert "click-public=" + str((execution_root / "fixture").resolve()) in command
    assert "codira-public=" not in command


def test_executor_rejects_reused_execution_root(tmp_path: Path) -> None:
    """Reject a root before it can overwrite or resume prior evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.

    Returns
    -------
    None
        The existing root is a deterministic safe failure.
    """

    campaign_directory, fixture_source = _campaign_directory(tmp_path)
    execution_root = tmp_path / "execution"
    execution_root.mkdir()

    with pytest.raises(CalibrationLaunchError, match="already exists"):
        load_launch(campaign_directory, execution_root, fixture_source, "podman")


def test_executor_launch_mode_consumes_the_matching_prepared_receipt(
    tmp_path: Path,
) -> None:
    """Permit launch only after verifying the root created by prepare mode.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.

    Returns
    -------
    None
        The existing root is accepted only with its matching receipt.
    """

    campaign_directory, fixture_source = _campaign_directory(tmp_path)
    execution_root = tmp_path / "execution"
    prepared = load_launch(campaign_directory, execution_root, fixture_source, "podman")
    receipt = prepare_launch(prepared)
    launch = load_launch(
        campaign_directory,
        execution_root,
        fixture_source,
        "podman",
        allow_prepared_root=True,
    )

    assert verify_prepared_launch(launch) == receipt


def test_executor_rejects_tampered_factory_plan(tmp_path: Path) -> None:
    """Reject plan drift before creating an execution directory.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.

    Returns
    -------
    None
        A changed immutable plan cannot reach tmux preparation.
    """

    campaign_directory, fixture_source = _campaign_directory(tmp_path)
    plan_path = campaign_directory / "launch-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["scheduled_attempt_count"] = 2
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(CalibrationLaunchError, match="differs"):
        load_launch(
            campaign_directory, tmp_path / "execution", fixture_source, "podman"
        )
