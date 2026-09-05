"""Behavioral tests for declarative installer plans and resumable application."""
# ruff: noqa: TRY003, EM101

from __future__ import annotations

from pathlib import Path

import pytest
from codira_installer import cli
from codira_installer.execution import apply_plan, load_journal
from codira_installer.models import (
    EnvironmentKind,
    EnvironmentTarget,
    InstallationProfile,
    InstallerRequest,
    InstallSource,
    PackageManager,
    RuntimeKind,
    RuntimeOperation,
    RuntimeTarget,
    WorkspaceRegistration,
)
from codira_installer.plan import render_plan, resolve_plan, validate_plan


def test_target_only_cli_request_installs_into_selected_environment(
    tmp_path: Path,
) -> None:
    """Route documented target-only CLI requests to their selected environment.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary environment roots used in plan-only resolution.

    Returns
    -------
    None
        The test asserts new and existing target requests create or install via
        the environment passed to ``--environment``.
    """
    for target in (EnvironmentKind.NEW, EnvironmentKind.EXISTING):
        environment = tmp_path / target.value / ".venv"
        request = cli._request(
            cli._parser().parse_args(
                ["--target", target.value, "--environment", str(environment)]
            )
        )
        plan = resolve_plan(request, installed_packages=())
        install = next(
            step for step in plan.steps if step.identifier == "install-packages"
        )

        assert request.runtime == RuntimeTarget(RuntimeKind(target), environment)
        assert str(environment / "bin" / "python") in install.command


def test_cli_requests_support_receipt_scoped_runtime_operations(
    tmp_path: Path,
) -> None:
    """Build plans for every non-install operation through the CLI request path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary receipt location.

    Returns
    -------
    None
        The test asserts CLI parsing preserves the receipt for update, repair,
        and modify requests accepted by shared planning.
    """
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        '{"packages": [], "profile": "recommended", "source": "pypi", "version": "1"}',
        encoding="utf-8",
    )

    for operation in (
        RuntimeOperation.UPDATE,
        RuntimeOperation.REPAIR,
        RuntimeOperation.MODIFY,
    ):
        request = cli._request(
            cli._parser().parse_args(
                ["--operation", operation.value, "--receipt", str(receipt)]
            )
        )

        plan = resolve_plan(request, installed_packages=())

        assert plan.request.operation is operation
        assert plan.request.receipt_path == receipt


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


def test_explicit_faiss_selection_is_a_catalog_install_target() -> None:
    """Include the optional FAISS distribution in a selected-feature plan.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the installer emits the coordinated FAISS package pin.
    """

    plan = resolve_plan(
        InstallerRequest(
            target=EnvironmentTarget(EnvironmentKind.CURRENT),
            packages=("codira-similarity-index-faiss",),
        ),
        installed_packages=(),
    )

    install_step = next(
        step for step in plan.steps if step.identifier == "install-packages"
    )
    assert "codira-similarity-index-faiss==2.0.0" in install_step.command


def test_managed_runtime_is_independent_of_workspace_repository(tmp_path: Path) -> None:
    """Install a managed runtime without selecting the repository environment.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary runtime and analyzed repository roots.

    Returns
    -------
    None
        The test asserts runtime installation and workspace registration differ.
    """
    runtime = tmp_path / "runtime"
    repository = tmp_path / "python-3-8-repository"
    repository.mkdir()
    plan = resolve_plan(
        InstallerRequest(
            target=EnvironmentTarget(EnvironmentKind.EXISTING, repository / ".venv"),
            runtime=RuntimeTarget(RuntimeKind.MANAGED, runtime),
            workspace=WorkspaceRegistration("sample", repository),
        ),
        installed_packages=(),
    )

    install = next(step for step in plan.steps if step.identifier == "install-packages")
    workspace = next(
        step for step in plan.steps if step.identifier == "register-workspace"
    )
    assert str(runtime / "bin" / "python") in install.command
    assert "codira-installer==2.0.0" in install.command
    assert str(repository / ".venv") not in install.command
    assert workspace.command == (
        "codira",
        "workspace",
        "add",
        "sample",
        "--path",
        str(repository),
    )


def test_runtime_update_requires_matching_receipt(tmp_path: Path) -> None:
    """Reject update requests that could silently change runtime provenance.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary receipt location.

    Returns
    -------
    None
        The test asserts receipt presence and source/profile matching.
    """
    with pytest.raises(ValueError, match="require a runtime receipt"):
        resolve_plan(
            InstallerRequest(
                target=EnvironmentTarget(EnvironmentKind.CURRENT),
                operation=RuntimeOperation.UPDATE,
            ),
            installed_packages=(),
        )
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        '{"packages": [], "profile": "recommended", "source": "pypi", "version": "1.55.0"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="forbids changing"):
        resolve_plan(
            InstallerRequest(
                target=EnvironmentTarget(EnvironmentKind.CURRENT),
                operation=RuntimeOperation.UPDATE,
                source=InstallSource.LOCAL_CHECKOUT,
                checkout=Path("/clone"),
                receipt_path=receipt,
            ),
            installed_packages=(),
        )


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
