"""Shared request resolution and execution boundary for installer front ends."""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira_installer.execution import apply_plan
from codira_installer.plan import resolve_plan, validate_plan

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from codira_installer.execution import CommandRunner
    from codira_installer.models import ExecutionJournal, InstallerRequest, InstallPlan


class InstallerController:
    """Resolve and apply plans without depending on a user-interface framework.

    Parameters
    ----------
    request : codira_installer.models.InstallerRequest
        Initial installer choices shared by the TUI and command-line front ends.
    journal_path : pathlib.Path
        Credential-free resume record destination.
    runner : codira_installer.execution.CommandRunner, optional
        Injectable command executor used by production and tests.
    """

    def __init__(
        self,
        request: InstallerRequest,
        journal_path: Path,
        *,
        runner: CommandRunner | None = None,
    ) -> None:
        """Store one front-end-independent installer session.

        Parameters
        ----------
        request : codira_installer.models.InstallerRequest
            Initial installer choices.
        journal_path : pathlib.Path
            Resume record destination.
        runner : codira_installer.execution.CommandRunner | None, optional
            Optional command executor.

        Returns
        -------
        None
        """
        self.request = request
        self.journal_path = journal_path
        self.runner = runner
        self.plan: InstallPlan | None = None

    def resolve(self) -> InstallPlan:
        """Resolve and validate the request into the session plan.

        Parameters
        ----------
        None

        Returns
        -------
        codira_installer.models.InstallPlan
            Validated plan used by every installer front end.
        """
        plan = resolve_plan(self.request)
        validate_plan(plan)
        self.plan = plan
        return plan

    def update_request(self, request: InstallerRequest) -> None:
        """Replace choices and invalidate any plan resolved for older choices.

        Parameters
        ----------
        request : codira_installer.models.InstallerRequest
            Newly collected installer choices.

        Returns
        -------
        None
        """
        self.request = request
        self.plan = None

    def apply(self, *, cancelled: Callable[[], bool] | None = None) -> ExecutionJournal:
        """Apply the resolved plan and preserve the resumable journal.

        Parameters
        ----------
        cancelled : collections.abc.Callable[[], bool] | None, optional
            Cooperative cancellation predicate checked between atomic steps.

        Returns
        -------
        codira_installer.models.ExecutionJournal
            Journal containing all completed steps.

        Raises
        ------
        RuntimeError
            If no validated plan has been resolved for the session.
        """
        if self.plan is None:
            message = "resolve a validated plan before applying it"
            raise RuntimeError(message)
        if self.runner is None:
            return apply_plan(self.plan, self.journal_path, cancelled=cancelled)
        return apply_plan(
            self.plan,
            self.journal_path,
            runner=self.runner,
            cancelled=cancelled,
        )
