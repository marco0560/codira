#!/usr/bin/env python3
"""Plan and optionally execute release artifact builds for codira.

Responsibilities
----------------
- Define the deterministic `python -m build` plan for the core package and every
  first-party distribution.
- Define the matching `python -m twine check` validation plan for built artifacts.
- Keep release-artifact rehearsal explicit before the real multirepo publish.

Design principles
-----------------
The helper stays declarative, repository-local, and deterministic. It prints
the exact commands in release order and can execute them when the required
build tools are available in the active environment.

Architectural role
------------------
This script belongs to the **developer tooling layer** and supports Phase 5
release preparation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.first_party_packages import package_paths

REPO_ROOT = Path(__file__).resolve().parents[1]


def _path_text(path: Path) -> str:
    """
    Render a path with deterministic forward-slash separators.

    Parameters
    ----------
    path : pathlib.Path
        Path to render for command arguments.

    Returns
    -------
    str
        POSIX-style path text.
    """
    text = str(path)
    if text.startswith("\\") and not text.startswith("\\\\"):
        return path.as_posix()
    return text


def release_package_paths(repo_root: Path) -> tuple[Path, ...]:
    """
    Return the core package and first-party packages in release order.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root containing the core and first-party packages.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Release package roots starting with the core repository root.
    """
    return (repo_root, *package_paths(repo_root))


def build_artifact_argv(*, python: str, package_path: Path) -> tuple[str, ...]:
    """
    Build the exact `python -m build` command for one package root.

    Parameters
    ----------
    python : str
        Python interpreter used to run `build`.
    package_path : pathlib.Path
        Package root whose wheel and sdist should be built.

    Returns
    -------
    tuple[str, ...]
        Deterministic command arguments for the build step.
    """
    return (
        python,
        "-m",
        "build",
        "--wheel",
        "--sdist",
        _path_text(package_path),
    )


def artifact_check_argv(*, python: str, package_path: Path) -> tuple[str, ...]:
    """
    Build the exact `python -m twine check` command for one package root.

    Parameters
    ----------
    python : str
        Python interpreter used to run `twine`.
    package_path : pathlib.Path
        Package root whose built artifacts should be validated.

    Returns
    -------
    tuple[str, ...]
        Deterministic command arguments for the artifact-check step.
    """
    return (
        python,
        "-m",
        "twine",
        "check",
        _path_text(package_path / "dist" / "*"),
    )


def build_release_plan(
    *,
    python: str,
    repo_root: Path,
) -> tuple[tuple[str, ...], ...]:
    """
    Build the ordered release-artifact command plan for all distributions.

    Parameters
    ----------
    python : str
        Python interpreter used to run the build and validation tools.
    repo_root : pathlib.Path
        Repository root containing the release package set.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Ordered build and artifact-check commands for the release rehearsal.
    """
    commands: list[tuple[str, ...]] = []
    for package_path in release_package_paths(repo_root):
        commands.append(build_artifact_argv(python=python, package_path=package_path))
    for package_path in release_package_paths(repo_root):
        commands.append(artifact_check_argv(python=python, package_path=package_path))
    return tuple(commands)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments for the release-artifact helper.

    Parameters
    ----------
    argv : list[str] | None, optional
        Optional argument override.

    Returns
    -------
    argparse.Namespace
        Parsed helper arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Plan or execute release-artifact builds and twine validation for "
            "codira and the first-party packages."
        )
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to run build and twine.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved commands without executing them.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Run the release-artifact build helper.

    Parameters
    ----------
    argv : list[str] | None, optional
        Optional argument override.

    Returns
    -------
    int
        Process exit code.
    """
    args = parse_args(argv)
    commands = build_release_plan(python=args.python, repo_root=REPO_ROOT)
    for command in commands:
        print(" ".join(command))
    if args.dry_run:
        return 0
    for command in commands:
        subprocess.run(command, cwd=REPO_ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
