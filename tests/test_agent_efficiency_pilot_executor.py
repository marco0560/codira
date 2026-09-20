"""Test deterministic factory-backed paired-pilot execution preparation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.agent_efficiency.campaign_factory import (
    build_campaign,
    write_campaign_artifacts,
)
from scripts.launch_agent_efficiency_pilot import (
    PilotLaunchError,
    load_launch,
    prepare_launch,
    runtime_state_root,
    tmux_command,
    verify_prepared_launch,
)


def _campaign_directory(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    """Create one generated pilot and placeholder admitted source mappings.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.

    Returns
    -------
    tuple[pathlib.Path, dict[str, pathlib.Path]]
        Generated campaign directory and three existing fixture-source paths.
    """

    specification: dict[str, object] = {
        "schema_version": "1.0",
        "campaign_id": "executor-pilot-001",
        "stage": "pilot",
        "task_ids": ["symbols-001", "patch-001", "documentation-001"],
        "seed": 20260920,
        "budgets": {
            "max_total_tokens": 240000,
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
            "max_estimated_attempt_spend_usd": 0.18,
            "max_estimated_pilot_spend_usd": 1.08,
            "max_response_requests_per_attempt": 10,
            "max_transport_attempts_per_response": 2,
            "max_total_tokens_scope": "whole-session",
        },
        "resource_controls": {
            "network": "none",
            "read_only_rootfs": True,
            "pids_limit": 512,
            "tmpfs_size_mib": 128,
        },
        "runtime_image": "localhost/test@sha256:" + "a" * 64,
        "runtime_profile_fingerprint": "b" * 64,
        "treatment_protocol": {
            "version": "mcp-required-v1",
            "codira_mcp_instruction": "Call Codira MCP before completing the task.",
        },
        "visibility": "public",
    }
    manifest, plan = build_campaign(specification, Path("benchmarks/agent-efficiency"))
    campaign_directory = tmp_path / "campaign"
    write_campaign_artifacts(campaign_directory, manifest, plan)
    sources = {}
    for fixture_id in ("click-public", "codira-public", "picomatch-public"):
        source = tmp_path / fixture_id
        source.mkdir()
        sources[fixture_id] = source
    return campaign_directory, sources


def _admit_fixture(*args: object, **kwargs: object) -> SimpleNamespace:
    """Return stable fixture identity for executor-only unit tests.

    Parameters
    ----------
    *args, **kwargs : object
        Ignored compatibility arguments from ``verify_fixture``.

    Returns
    -------
    types.SimpleNamespace
        Minimal verified fixture report used by receipt construction.
    """

    return SimpleNamespace(revision="a" * 40, tree_sha="b" * 40)


def test_prepare_claims_paths_and_builds_fixed_paid_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bind generated artifacts, fixtures, durable outputs, and SOPS command.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture-admission adapter for executor-only behavior.
    """

    monkeypatch.setattr(
        "scripts.launch_agent_efficiency_pilot.verify_fixture", _admit_fixture
    )
    campaign_directory, sources = _campaign_directory(tmp_path)
    execution_root = tmp_path / "execution"
    launch = load_launch(
        campaign_directory, execution_root, sources, "podman", 20260920
    )

    receipt = prepare_launch(launch)
    _, command = tmux_command(launch)

    assert receipt.is_file()
    assert runtime_state_root(launch).is_dir()
    assert len(str(runtime_state_root(launch) / "provider.sock").encode()) < 108
    assert str(execution_root / "logs" / "pilot.log") in command
    assert str(execution_root / "pilot.exit") in command
    assert "sops exec-env" in command
    assert command.count("--task-id") == 3
    assert command.count("--fixture-source") == 3


def test_executor_rejects_seed_that_differs_from_factory_plan(tmp_path: Path) -> None:
    """Reject an external seed unless it reproduces the immutable schedule.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.
    """

    campaign_directory, sources = _campaign_directory(tmp_path)

    with pytest.raises(PilotLaunchError, match="manifest or seed"):
        load_launch(campaign_directory, tmp_path / "execution", sources, "podman", 1)


def test_executor_rejects_reused_execution_root(tmp_path: Path) -> None:
    """Reject a root before prior paid evidence can be resumed or overwritten.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.
    """

    campaign_directory, sources = _campaign_directory(tmp_path)
    execution_root = tmp_path / "execution"
    execution_root.mkdir()

    with pytest.raises(PilotLaunchError, match="already exists"):
        load_launch(campaign_directory, execution_root, sources, "podman", 20260920)


def test_launch_mode_reverifies_prepared_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Permit launch only after source and receipt identity are revalidated.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary directory supplied by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture-admission adapter for executor-only behavior.
    """

    monkeypatch.setattr(
        "scripts.launch_agent_efficiency_pilot.verify_fixture", _admit_fixture
    )
    campaign_directory, sources = _campaign_directory(tmp_path)
    execution_root = tmp_path / "execution"
    prepared = load_launch(
        campaign_directory, execution_root, sources, "podman", 20260920
    )
    receipt = prepare_launch(prepared)
    launch = load_launch(
        campaign_directory,
        execution_root,
        sources,
        "podman",
        20260920,
        allow_prepared_root=True,
    )

    assert verify_prepared_launch(launch) == receipt

    document = json.loads(receipt.read_text(encoding="utf-8"))
    document["seed"] = 1
    receipt.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PilotLaunchError, match="differs"):
        verify_prepared_launch(launch)
