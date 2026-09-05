"""Headless coverage for the Textual installer and shared CLI controller."""
# ruff: noqa: TRY003, EM101, TC003

from __future__ import annotations

import asyncio
import json
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

from codira_installer.app import (
    InstallerApp,
    LifecycleScreen,
    ReviewScreen,
    SourceScreen,
)
from codira_installer.cli import main
from codira_installer.controller import InstallerController
from codira_installer.execution import InstallationCancelled, load_journal
from codira_installer.models import (
    EnvironmentKind,
    EnvironmentTarget,
    ExecutionJournal,
    InstallerRequest,
    InstallPlan,
    RuntimeOperation,
)
from codira_installer.plan import load_plan, resolve_plan

if TYPE_CHECKING:
    import pytest
from textual.widgets import Button, Input


def _request() -> InstallerRequest:
    """Return a deterministic request shared by TUI and headless checks.

    Parameters
    ----------
    None

    Returns
    -------
    codira_installer.models.InstallerRequest
        Current-environment request with no installed package observation.
    """
    return InstallerRequest(target=EnvironmentTarget(EnvironmentKind.CURRENT))


def test_tui_and_headless_controller_resolve_identical_plans(tmp_path: Path) -> None:
    """Keep Textual and command-line requests on the one resolver boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary journal location.

    Returns
    -------
    None
    """
    controller = InstallerController(_request(), tmp_path / "journal.json")

    assert controller.resolve().fingerprint == resolve_plan(_request()).fingerprint


def test_plan_export_and_headless_apply_share_validated_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Export and apply the exact portable plan consumed by automation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary plan and journal directory.
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture that replaces headless application with a safe recorder.

    Returns
    -------
    None
    """
    plan_path = tmp_path / "plan.json"
    journal_path = tmp_path / "journal.json"

    assert main(["--plan", str(plan_path)]) == 0
    plan = load_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    assert plan.fingerprint == resolve_plan(_request()).fingerprint
    captured: list[Path] = []

    def apply_without_subprocess(plan: InstallPlan, journal: Path) -> ExecutionJournal:
        """Capture CLI application without executing an installation command.

        Parameters
        ----------
        plan : codira_installer.models.InstallPlan
            Plan parsed from exported JSON.
        journal : pathlib.Path
            Requested resume journal destination.

        Returns
        -------
        codira_installer.models.ExecutionJournal
            Empty test journal with the parsed fingerprint.
        """
        captured.append(journal)
        return ExecutionJournal(plan.fingerprint)

    monkeypatch.setattr("codira_installer.cli.apply_plan", apply_without_subprocess)

    assert main(["--apply", str(plan_path), "--journal", str(journal_path)]) == 0
    assert captured == [journal_path]


def test_headless_apply_failure_then_resume_succeeds(tmp_path: Path) -> None:
    """Preserve the journal on a failed apply and resume only remaining steps.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary journal location.

    Returns
    -------
    None
    """
    calls: list[tuple[str, ...]] = []
    failures = 1

    def runner(command: tuple[str, ...]) -> None:
        """Fail once on the non-empty package install command.

        Parameters
        ----------
        command : tuple[str, ...]
            Current shell-free execution vector.

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            Once, when the package install command is first reached.
        """
        nonlocal failures
        calls.append(command)
        if command and failures:
            failures -= 1
            raise RuntimeError("expected install failure")

    controller = InstallerController(
        _request(), tmp_path / "journal.json", runner=runner
    )
    controller.resolve()
    try:
        controller.apply()
    except RuntimeError as error:
        assert str(error) == "expected install failure"
    else:
        raise AssertionError("the first apply must fail")

    journal = controller.apply()
    assert controller.plan is not None
    assert len(journal.results) == len(controller.plan.steps)
    assert calls.count(()) == 1


def test_cancellation_preserves_completed_journal(tmp_path: Path) -> None:
    """Cancel only between commands after completed work has been journaled.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary journal location.

    Returns
    -------
    None
    """
    controller = InstallerController(
        _request(), tmp_path / "journal.json", runner=lambda command: None
    )
    controller.resolve()
    calls = 0

    def cancelled() -> bool:
        """Request cancellation after the preflight step completes.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            Whether cancellation should happen before the next step.
        """
        nonlocal calls
        calls += 1
        return calls > 1

    try:
        controller.apply(cancelled=cancelled)
    except InstallationCancelled:
        pass
    else:
        raise AssertionError("cancellation must stop before the next step")

    journal = load_journal(tmp_path / "journal.json")
    assert journal is not None
    assert journal.completed_identifiers() == frozenset({"preflight"})


def test_headless_textual_navigation_and_review_confirmation(tmp_path: Path) -> None:
    """Navigate every screen headlessly and enable Apply only after validation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary journal location.

    Returns
    -------
    None
    """

    async def exercise() -> None:
        """Drive the UI with Textual's headless test pilot.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        app = InstallerApp(InstallerController(_request(), tmp_path / "journal.json"))
        async with app.run_test() as pilot:
            assert isinstance(app.screen, SourceScreen)
            app.screen.query_one("#source", Input).value = "local-checkout"
            app.screen.query_one("#checkout", Input).value = "/clone/codira"
            await pilot.click("#next")
            app.screen.query_one("#target", Input).value = "existing"
            app.screen.query_one("#environment", Input).value = "/target/.venv"
            await pilot.click("#next")
            for _ in range(8):
                await pilot.click("#next")
            assert isinstance(app.screen, ReviewScreen)
            assert not app.screen.query_one("#apply", Button).disabled
            assert app.controller.plan is not None
            assert app.controller.plan.request.checkout == Path("/clone/codira")
            assert app.controller.plan.request.target.path == Path("/target/.venv")

    asyncio.run(exercise())


def test_tui_commits_receipt_scoped_runtime_operation(tmp_path: Path) -> None:
    """Commit a non-install lifecycle choice through the Textual front end.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary receipt and journal location.

    Returns
    -------
    None
        The test asserts the lifecycle screen updates the shared request with
        the selected operation and receipt path.
    """
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        '{"packages": [], "profile": "recommended", "source": "pypi", "version": "1"}',
        encoding="utf-8",
    )

    async def exercise() -> None:
        """Drive the lifecycle screen through Textual's headless pilot.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The screen transition commits the lifecycle values.
        """
        app = InstallerApp(InstallerController(_request(), tmp_path / "journal.json"))
        async with app.run_test() as pilot:
            await pilot.click("#next")
            await pilot.click("#next")
            assert isinstance(app.screen, LifecycleScreen)
            app.screen.query_one("#operation", Input).value = "repair"
            app.screen.query_one("#receipt", Input).value = str(receipt)
            await pilot.click("#next")

            assert app.controller.request.operation is RuntimeOperation.REPAIR
            assert app.controller.request.receipt_path == receipt

    asyncio.run(exercise())
