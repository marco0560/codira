#!/usr/bin/env python3
"""Validate first-party package boundaries through local wheel builds.

Responsibilities
----------------
- Define the deterministic wheel-build rehearsal for every first-party package directory.
- Print or execute the exact `python -m pip wheel` commands for the current checkout.
- Give the migration branch one local split-readiness gate before repositories are split.

Design principles
-----------------
The helper reuses the shared first-party package inventory, avoids network
assumptions, and stays explicit about command construction so package-boundary
drift is easy to detect.

Architectural role
------------------
This script belongs to the **developer tooling layer** and supports Phase 3
multirepo readiness rehearsals.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.first_party_packages import package_paths

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WHEEL_DIR = REPO_ROOT / ".artifacts" / "first-party-wheels"


def build_build_argv(
    *,
    python: str,
    package_path: Path,
    wheel_dir: Path,
) -> tuple[str, ...]:
    """
    Build the exact wheel-validation command for one first-party package.

    Parameters
    ----------
    python : str
        Python interpreter used to run `build`.
    package_path : pathlib.Path
        First-party package directory to validate.
    wheel_dir : pathlib.Path
        Output directory receiving the built wheel artifact.

    Returns
    -------
    tuple[str, ...]
        Deterministic command arguments for the wheel build step.
    """
    return (
        python,
        "-m",
        "pip",
        "wheel",
        "--no-build-isolation",
        "--no-deps",
        "--wheel-dir",
        str(wheel_dir),
        str(package_path),
    )


def build_all_argv(
    *,
    python: str,
    repo_root: Path,
    wheel_dir: Path,
) -> tuple[tuple[str, ...], ...]:
    """
    Build the wheel-validation plan for every first-party package.

    Parameters
    ----------
    python : str
        Python interpreter used to run `build`.
    repo_root : pathlib.Path
        Repository root containing the package directories.
    wheel_dir : pathlib.Path
        Output directory receiving the built wheel artifacts.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Wheel-build commands in deterministic first-party package order.
    """
    return tuple(
        build_build_argv(
            python=python,
            package_path=package_path,
            wheel_dir=wheel_dir,
        )
        for package_path in package_paths(repo_root)
    )


def cleanup_build_artifacts(package_path: Path) -> None:
    """
    Remove package-local build artifacts created by wheel validation.

    Parameters
    ----------
    package_path : pathlib.Path
        First-party package directory whose transient build artifacts should be removed.

    Returns
    -------
    None
        Known build directories are removed when they exist.
    """
    shutil.rmtree(package_path / "build", ignore_errors=True)
    for egg_info_dir in sorted(package_path.rglob("*.egg-info")):
        shutil.rmtree(egg_info_dir, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments for the build rehearsal helper.

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
        description="Validate codira first-party package boundaries with local wheel builds."
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to run `python -m pip wheel`.",
    )
    parser.add_argument(
        "--wheel-dir",
        type=Path,
        default=DEFAULT_WHEEL_DIR,
        help="Directory receiving built wheels for the validation pass.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved build commands without executing them.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Validate the first-party package set for the local checkout.

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
    args.wheel_dir.mkdir(parents=True, exist_ok=True)
    commands = build_all_argv(
        python=args.python,
        repo_root=REPO_ROOT,
        wheel_dir=args.wheel_dir,
    )
    for command in commands:
        print(" ".join(command))
    if args.dry_run:
        return 0
    for package_path, command in zip(package_paths(REPO_ROOT), commands, strict=True):
        cleanup_build_artifacts(package_path)
        subprocess.run(command, cwd=REPO_ROOT, check=True)
        cleanup_build_artifacts(package_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
