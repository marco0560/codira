"""Behavioral tests for declarative installer plans and resumable application."""
# ruff: noqa: TRY003, EM101

from __future__ import annotations

from pathlib import Path

import pytest
from codira_installer.execution import apply_plan, load_journal
from codira_installer.models import (
    EnvironmentKind,
    EnvironmentTarget,
    InstallationProfile,
    InstallerRequest,
    InstallSource,
    PackageManager,
)
from codira_installer.plan import render_plan, resolve_plan, validate_plan


def test_equivalent_requests_render_byte_identical_plans() -> None:
    """Render equivalent requests deterministically.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    request = InstallerRequest(
        target=EnvironmentTarget(EnvironmentKind.EXISTING, Path("/env")),
        profile=InstallationProfile.FULL_OFFICIAL,
    )

    first = resolve_plan(request, installed_packages=())
    second = resolve_plan(request, installed_packages=())

    assert render_plan(first) == render_plan(second)
    validate_plan(first)


def test_pip_rejects_new_and_local_checkout_targets() -> None:
    """Keep pip support bounded to coordinated PyPI existing targets.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    with pytest.raises(ValueError, match="cannot create"):
        resolve_plan(
            InstallerRequest(
                target=EnvironmentTarget(EnvironmentKind.NEW, Path("/new")),
                manager=PackageManager.PIP,
            )
        )
    with pytest.raises(ValueError, match="cannot install from local"):
        resolve_plan(
            InstallerRequest(
                target=EnvironmentTarget(EnvironmentKind.CURRENT),
                source=InstallSource.LOCAL_CHECKOUT,
                checkout=Path("/checkout"),
                manager=PackageManager.PIP,
            )
        )


def test_local_checkout_uses_explicit_cloned_root() -> None:
    """Use the cloned Codira root as a command argument, never a shell string.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    plan = resolve_plan(
        InstallerRequest(
            target=EnvironmentTarget(EnvironmentKind.EXISTING, Path("/target")),
            source=InstallSource.LOCAL_CHECKOUT,
            checkout=Path("/clone/codira"),
        ),
        installed_packages=(),
    )

    install_step = next(
        step for step in plan.steps if step.identifier == "install-packages"
    )
    assert "/clone/codira" in install_step.command
    assert "/clone/codira/packages/codira-backend-sqlite" in install_step.command
    assert install_step.command[:3] == ("uv", "pip", "install")


def test_deselected_installed_packages_are_retained_and_reported() -> None:
    """Report deselections without generating uninstall operations.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    plan = resolve_plan(
        InstallerRequest(target=EnvironmentTarget(EnvironmentKind.CURRENT)),
        installed_packages=("codira-analyzer-c", "codira-analyzer-python"),
    )

    assert plan.deselected_packages == ("codira-analyzer-c",)
    assert all("uninstall" not in step.command for step in plan.steps)


def test_successful_resume_is_a_no_op(tmp_path: Path) -> None:
    """Skip every previously successful step on a matching journal resume.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary journal directory.

    Returns
    -------
    None
    """
    plan = resolve_plan(
        InstallerRequest(target=EnvironmentTarget(EnvironmentKind.CURRENT)),
        installed_packages=(),
    )
    journal_path = tmp_path / "journal.json"
    commands: list[tuple[str, ...]] = []

    apply_plan(plan, journal_path, runner=commands.append)
    apply_plan(plan, journal_path, runner=commands.append)

    assert len(commands) == len(plan.steps)
    assert load_journal(journal_path) is not None


def test_failed_apply_preserves_completed_steps_for_safe_resume(tmp_path: Path) -> None:
    """Persist completed work and fail before subsequent steps execute.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary journal directory.

    Returns
    -------
    None
    """
    plan = resolve_plan(
        InstallerRequest(target=EnvironmentTarget(EnvironmentKind.CURRENT)),
        installed_packages=(),
    )
    journal_path = tmp_path / "journal.json"
    calls = 0

    def failing_runner(command: tuple[str, ...]) -> None:
        """Fail when the package-install command is reached.

        Parameters
        ----------
        command : tuple[str, ...]
            Command currently being applied.

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            When the package installation step is reached.
        """
        nonlocal calls
        calls += 1
        if command:
            raise RuntimeError("install failed")

    with pytest.raises(RuntimeError, match="install failed"):
        apply_plan(plan, journal_path, runner=failing_runner)

    journal = load_journal(journal_path)
    assert calls == 2
    assert journal is not None
    assert journal.completed_identifiers() == frozenset({"preflight"})
