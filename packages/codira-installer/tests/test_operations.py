"""Tests for optional installer model, calibration, and service operations."""
# ruff: noqa: TRY003, EM101

from __future__ import annotations

from pathlib import Path

import pytest
from codira_installer.operations import (
    ServiceKind,
    apply_calibration,
    calibration_proposal,
    model_provision_plan,
    provision_model,
    recommend_hardware,
    service_plan,
    verify_service,
)


def test_model_provisioning_plan_targets_one_environment() -> None:
    """Keep model provisioning idempotent and scoped to the target Python.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    plan = model_provision_plan(Path("/target/bin/python"))

    assert plan.command[:2] == ("/target/bin/python", "-c")
    assert "provision_embedding_model" in plan.command[2]
    commands: list[tuple[str, ...]] = []
    assert not provision_model(plan, is_ready=lambda: True, runner=commands.append)
    assert provision_model(plan, is_ready=lambda: False, runner=commands.append)
    assert commands == [plan.command]


def test_calibration_requires_second_confirmation() -> None:
    """Keep recommendation and configuration write confirmation separate.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    proposal = calibration_proposal(recommend_hardware(cpu_count=12))
    writes: list[object] = []

    with pytest.raises(ValueError, match="second explicit confirmation"):
        apply_calibration(proposal, confirmed=False, apply=writes.append)
    apply_calibration(proposal, confirmed=True, apply=writes.append)

    assert proposal.recommendation.cpu_count == 12
    assert writes == [proposal.config_delta]


def test_service_plans_are_platform_and_repository_scoped(tmp_path: Path) -> None:
    """Keep service command roots explicit without privilege escalation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository and output roots.

    Returns
    -------
    None
    """
    plan = service_plan(
        ServiceKind.QUERY,
        tmp_path / "repo",
        tmp_path / "output",
        "install",
        platform="darwin",
    )

    assert plan.platform == "darwin"
    assert "sudo" not in plan.command
    assert plan.command[:3] == ("codira", "query-daemon", "install")
    assert plan.config_delta == {"query_daemon": {"enabled": True}}


def test_service_failure_is_isolated_with_remediation(tmp_path: Path) -> None:
    """Return status remediation instead of propagating daemon failures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository and output roots.

    Returns
    -------
    None
    """
    plan = service_plan(
        ServiceKind.INDEXING, tmp_path, tmp_path, "status", platform="linux"
    )

    def unavailable(command: tuple[str, ...]) -> None:
        """Raise the status error used by this isolated verification test.

        Parameters
        ----------
        command : tuple[str, ...]
            Attempted status command.

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            Always, to model an unavailable daemon.
        """
        raise RuntimeError("not running")

    verification = verify_service(plan, unavailable)

    assert not verification.healthy
    assert "linux user-service logs" in verification.detail
