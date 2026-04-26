#!/usr/bin/env python3
"""Bootstrap the repository-local development environment.

Responsibilities
----------------
- Create the `.venv` virtual environment and install editable application plus dev/docs/first-party dependencies.
- Provision deterministic commands like the local embedding model and repo-local Git configuration.
- Optionally run validation steps such as pre-commit hooks and tooling checks.

Design principles
-----------------
Bootstrap steps are explicit, deterministic, and confined to repository-owned state without touching personal configuration.

Architectural role
------------------
This module belongs to the **developer tooling layer** and provides a portable, reproducible environment setup entrypoint for contributors.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VENV_DIR = ".venv"
REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CommandSpec:
    """
    Describe one bootstrap command.

    Parameters
    ----------
    description : str
        Human-readable description of the command step.
    argv : tuple[str, ...]
        Exact command arguments to execute.
    cwd : pathlib.Path
        Working directory for the command.
    """

    description: str
    argv: tuple[str, ...]
    cwd: Path


def venv_python(repo_root: Path) -> Path:
    """
    Return the expected Python interpreter inside the local virtual environment.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root containing the local virtual environment.

    Returns
    -------
    pathlib.Path
        Preferred Python interpreter path for the repository virtual
        environment.
    """

    candidates = [
        repo_root / DEFAULT_VENV_DIR / "bin" / "python",
        repo_root / DEFAULT_VENV_DIR / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def build_bootstrap_commands(
    *, repo_root: Path, python: str, skip_validation: bool
) -> list[CommandSpec]:
    """
    Build the ordered bootstrap command plan.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root where the commands must run.
    python : str
        Python interpreter used to create the virtual environment.
    skip_validation : bool
        Whether to skip the validation portion of the bootstrap plan.

    Returns
    -------
    list[CommandSpec]
        Ordered bootstrap command specifications.
    """

    python_bin = venv_python(repo_root)
    commands = [
        CommandSpec(
            "Create virtual environment",
            (python, "-m", "venv", str(repo_root / DEFAULT_VENV_DIR)),
            repo_root,
        ),
        CommandSpec(
            "Upgrade installer tooling",
            (
                str(python_bin),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "setuptools",
                "wheel",
            ),
            repo_root,
        ),
        CommandSpec(
            "Install editable core, development, documentation, and semantic dependencies",
            (
                str(python_bin),
                "-m",
                "pip",
                "install",
                "-e",
                ".[dev,docs,semantic]",
            ),
            repo_root,
        ),
        CommandSpec(
            "Install extracted first-party analyzer and backend packages",
            (
                str(python_bin),
                "scripts/install_first_party_packages.py",
                "--include-core",
                "--core-extra",
                "dev",
                "--core-extra",
                "docs",
                "--core-extra",
                "semantic",
            ),
            repo_root,
        ),
        CommandSpec(
            "Provision the local embedding model artifact",
            (str(python_bin), "scripts/provision_embedding_model.py"),
            repo_root,
        ),
        CommandSpec(
            "Install repo-local Git aliases and configuration",
            (str(python_bin), "scripts/install_repo_git_config.py"),
            repo_root,
        ),
    ]

    if not skip_validation:
        commands.extend(
            [
                CommandSpec(
                    "Run standard validation",
                    (str(python_bin), "scripts/validate_repo.py"),
                    repo_root,
                ),
            ]
        )
    return commands


def render_command(command: CommandSpec) -> str:
    """
    Render a command specification for console output.

    Parameters
    ----------
    command : CommandSpec
        Command specification to render.

    Returns
    -------
    str
        Shell-ready command preview.
    """

    return " ".join(shlex.quote(arg) for arg in command.argv)


def parse_args() -> argparse.Namespace:
    """
    Parse bootstrap command-line arguments.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.Namespace
        Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Create .venv, install dependencies, and configure local Git state."
        ),
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    """
    Run or display the bootstrap plan.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit code.
    """

    args = parse_args()
    commands = build_bootstrap_commands(
        repo_root=REPO_ROOT,
        python=args.python,
        skip_validation=args.skip_validation,
    )

    for command in commands:
        print(f"==> {command.description}")
        print(f"    {render_command(command)}")
        if args.dry_run:
            continue
        subprocess.run(command.argv, cwd=command.cwd, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
