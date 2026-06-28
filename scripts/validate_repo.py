#!/usr/bin/env python3
"""Run the standard repository validation through safe tool-state routing.

Responsibilities
----------------
- Provide one obvious command for local validation.
- Delegate all cache and temporary directory handling to
  ``scripts/run_repo_tool.py``.
- Stop at the first failing validation step and return its exit status.

Design principles
-----------------
This wrapper must not create repository-local cache or temporary directories.
The lower-level tool runner owns that policy.

Architectural role
------------------
This module belongs to the **developer tooling layer** and composes the
repository-owned tool runner.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_REPO_TOOL = REPO_ROOT / "scripts" / "run_repo_tool.py"
COMPLETE_SEMGREP_ARTIFACT_ROOT = REPO_ROOT / ".artifacts" / "analysis" / "semgrep"


@dataclass(frozen=True)
class ValidationStep:
    """One validation command routed through the repository tool runner."""

    name: str
    tool: str
    args: tuple[str, ...]


VALIDATION_STEPS: tuple[ValidationStep, ...] = (
    ValidationStep("ruff", "ruff", ("check", ".")),
    ValidationStep("ruff-format", "ruff", ("format", "--check", ".")),
    ValidationStep("mypy", "mypy", (".",)),
    ValidationStep("pre-commit-noncode", "pre-commit-noncode", ("run", "--all-files")),
    ValidationStep(
        "semgrep",
        "semgrep",
        (
            "scan",
            "--config",
            "semgrep/rules",
            "--metrics=off",
            "--disable-version-check",
            "--exclude",
            "fixtures",
            ".",
        ),
    ),
    ValidationStep(
        "coverage",
        "coverage",
        ("run", "-m", "pytest", "-q", "tests", "packages"),
    ),
    ValidationStep(
        "coverage-json",
        "coverage",
        (
            "json",
            "-o",
            ".coverage-report.json",
            "--omit=*/_remote_module_non_scriptable",
        ),
    ),
    ValidationStep(
        "coverage-summary",
        "python",
        ("scripts/coverage_summary.py",),
    ),
)


def build_complete_semgrep_step() -> ValidationStep:
    """
    Build the optional complete Semgrep validation step.

    Parameters
    ----------
    None

    Returns
    -------
    ValidationStep
        Semgrep step that writes a full registry-backed JSON report to the
        gitignored analysis artifact root.
    """

    return ValidationStep(
        "semgrep-complete",
        "semgrep",
        (
            "scan",
            "--json",
            "--output",
            str(complete_semgrep_output_path()),
            "--exclude",
            "fixtures",
            ".",
        ),
    )


def complete_semgrep_output_path(*, now: datetime | None = None) -> Path:
    """
    Build the timestamped artifact path for the complete Semgrep report.

    Parameters
    ----------
    now : datetime.datetime | None, optional
        Explicit UTC timestamp override for tests. When omitted, the current
        UTC time is used.

    Returns
    -------
    pathlib.Path
        Timestamped JSON artifact path below ``.artifacts/analysis/semgrep``.
    """

    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return COMPLETE_SEMGREP_ARTIFACT_ROOT / f"semgrep-complete-{timestamp}.json"


def relative_report_path(path: Path) -> str:
    """
    Return a repository-relative label for one saved report path.

    Parameters
    ----------
    path : pathlib.Path
        Absolute or repository-relative report path.

    Returns
    -------
    str
        Repository-relative path when possible, otherwise the original string
        form.
    """

    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser for the repository validator.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for repository validation options.
    """

    parser = argparse.ArgumentParser(
        description="Run the standard repository validation sequence.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print delegated validation commands without executing them.",
    )
    parser.add_argument(
        "--semgrep-complete",
        action="store_true",
        help=(
            "Append a broader Semgrep registry scan using the remote auto "
            "configuration."
        ),
    )
    return parser


def build_validation_steps(
    *,
    include_semgrep_complete: bool = False,
) -> tuple[ValidationStep, ...]:
    """
    Build the ordered validation steps for one validator invocation.

    Parameters
    ----------
    include_semgrep_complete : bool, optional
        Whether to append the broader Semgrep registry scan.

    Returns
    -------
    tuple[ValidationStep, ...]
        Ordered validation steps for the requested validator mode.
    """

    if not include_semgrep_complete:
        return VALIDATION_STEPS
    return (*VALIDATION_STEPS, build_complete_semgrep_step())


def build_validation_commands(
    *,
    python: str = sys.executable,
    include_semgrep_complete: bool = False,
) -> tuple[tuple[str, ...], ...]:
    """
    Build the standard validation commands.

    Parameters
    ----------
    python : str, optional
        Python executable used to invoke ``scripts/run_repo_tool.py``.
    include_semgrep_complete : bool, optional
        Whether to append the broader Semgrep registry scan.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Ordered command vectors for the validation steps.
    """

    return tuple(
        (
            python,
            str(RUN_REPO_TOOL),
            step.tool,
            *step.args,
        )
        for step in build_validation_steps(
            include_semgrep_complete=include_semgrep_complete
        )
    )


def run_validation(
    commands: tuple[tuple[str, ...], ...] | None = None,
) -> int:
    """
    Execute validation commands in order.

    Parameters
    ----------
    commands : tuple[tuple[str, ...], ...] | None, optional
        Explicit command vectors to run. When omitted, the standard validation
        commands are built with the current Python executable.

    Returns
    -------
    int
        Zero when all validation steps pass, otherwise the first non-zero child
        exit status.
    """

    selected_commands = (
        commands if commands is not None else build_validation_commands()
    )
    for command in selected_commands:
        if len(command) >= 8 and command[2] == "semgrep" and "--output" in command:
            output_index = command.index("--output") + 1
            Path(command[output_index]).parent.mkdir(parents=True, exist_ok=True)
        capture_output = (
            len(command) >= 5 and command[2] == "coverage" and command[3] == "report"
        )

        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=capture_output,
            text=capture_output,
        )

        if capture_output:
            output = completed.stdout.strip()

            if "--format=total" in command:
                print(f"TOTAL COVERAGE: {output}%")
            else:
                lines = output.splitlines()

                if len(lines) > 2:
                    print("\nWorst coverage files:")
                    for line in lines[2:7]:
                        print(line)

        if len(command) >= 8 and command[2] == "semgrep" and "--output" in command:
            output_index = command.index("--output") + 1
            report_label = relative_report_path(Path(command[output_index]))
            if completed.returncode != 0:
                print(f"Complete Semgrep report requires examination: {report_label}")
                return completed.returncode
            print(f"Saved Semgrep report: {report_label}")

        if completed.returncode != 0:
            return completed.returncode

    return 0


def render_validation_commands(commands: tuple[tuple[str, ...], ...]) -> str:
    """
    Render delegated validation commands for dry-run output.

    Parameters
    ----------
    commands : tuple[tuple[str, ...], ...]
        Command vectors that would be executed by the validator.

    Returns
    -------
    str
        One shell-quoted command per line.
    """

    return "\n".join(shlex.join(command) for command in commands)


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the standard repository validation sequence.

    Parameters
    ----------
    argv : collections.abc.Sequence[str] | None, optional
        Explicit command-line arguments. When omitted, ``sys.argv[1:]`` is
        used.

    Returns
    -------
    int
        Validation exit status.
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    commands = build_validation_commands(include_semgrep_complete=args.semgrep_complete)
    if args.dry_run:
        print(render_validation_commands(commands))
        return 0
    return run_validation(commands)


if __name__ == "__main__":
    raise SystemExit(main())
