"""Apply installer plans with fail-fast, safe resume, and atomic journals."""
# ruff: noqa: TRY003, EM101

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from codira_installer.models import ExecutionJournal, InstallPlan, StepResult
from codira_installer.plan import validate_plan

CommandRunner = Callable[[tuple[str, ...]], None]


class InstallationCancelled(RuntimeError):
    """Signal cooperative cancellation between completed installer steps.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """


def _run(command: tuple[str, ...]) -> None:
    """Execute a single shell-free command vector.

    Parameters
    ----------
    command : tuple[str, ...]
        Command arguments to execute.

    Returns
    -------
    None
    """
    if command:
        subprocess.run(command, check=True)


def load_journal(path: Path) -> ExecutionJournal | None:
    """Load a credential-free execution journal when it exists.

    Parameters
    ----------
    path : pathlib.Path
        Journal file path.

    Returns
    -------
    ExecutionJournal | None
        Existing journal or ``None``.
    """
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ExecutionJournal(
        fingerprint=str(payload["fingerprint"]),
        results=tuple(StepResult(**row) for row in payload["results"]),
    )


def write_journal(path: Path, journal: ExecutionJournal) -> None:
    """Atomically persist a resumable execution journal.

    Parameters
    ----------
    path : pathlib.Path
        Journal file path.
    journal : ExecutionJournal
        Journal state to write.

    Returns
    -------
    None
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(asdict(journal), sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def apply_plan(
    plan: InstallPlan,
    journal_path: Path,
    *,
    runner: CommandRunner = _run,
    cancelled: Callable[[], bool] | None = None,
) -> ExecutionJournal:
    """Apply incomplete steps, stopping on failure and preserving progress.

    Parameters
    ----------
    plan : InstallPlan
        Plan to apply.
    journal_path : pathlib.Path
        Safe resume record location.
    runner : CommandRunner, optional
        Injectable command runner.
    cancelled : collections.abc.Callable[[], bool] | None, optional
        Cooperative cancellation predicate checked before each incomplete step.

    Returns
    -------
    ExecutionJournal
        Complete journal after all postconditions have succeeded.

    Raises
    ------
    ValueError
        If the journal belongs to another plan.
    subprocess.CalledProcessError
        If an unfinished command fails.
    InstallationCancelled
        If cancellation is requested between atomic steps.
    """
    validate_plan(plan)
    journal = load_journal(journal_path) or ExecutionJournal(plan.fingerprint)
    if journal.fingerprint != plan.fingerprint:
        raise ValueError("journal fingerprint does not match plan")
    results = list(journal.results)
    completed = journal.completed_identifiers()
    for step in plan.steps:
        if step.identifier in completed:
            continue
        if cancelled is not None and cancelled():
            raise InstallationCancelled("installation cancelled before the next step")
        runner(step.command)
        results.append(StepResult(step.identifier, True, step.postcondition))
        journal = ExecutionJournal(plan.fingerprint, tuple(results))
        write_journal(journal_path, journal)
    return journal
