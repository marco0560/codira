#!/usr/bin/env python3
"""Install the repository's first-party package set.

Responsibilities
----------------
- Define the authoritative editable install set for first-party package-owned components.
- Run a deterministic editable-install plan for the current repository checkout.
- Keep bootstrap, CI, and maintainer workflows aligned to the same package list.

Design principles
-----------------
The script centralizes package ownership metadata so first-party install flows
do not drift across bootstrap commands, CI jobs, and local maintenance docs.

Architectural role
------------------
This script belongs to the **developer tooling layer** and enforces the
repository-local first-party package boundary accepted in ADR-007.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.first_party_packages import FIRST_PARTY_PACKAGE_DIRS

REPO_ROOT = Path(__file__).resolve().parents[1]
FIRST_PARTY_EDITABLE_PACKAGES = FIRST_PARTY_PACKAGE_DIRS
BUNDLE_PACKAGE_DIR = "packages/codira-bundle-official"


@dataclass(frozen=True)
class InstallCommandRequest:
    """
    Request parameters for first-party install command construction.

    Parameters
    ----------
    python : str
        Python interpreter used to run `pip`.
    repo_root : pathlib.Path
        Repository root containing the package directories.
    include_core : bool
        Whether to include the editable core ``codira`` package before the
        first-party package set.
    core_extras : tuple[str, ...]
        Optional extras requested on the editable core install.
    include_bundle : bool
        Whether to install the curated bundle meta-package in addition to the
        first-party analyzer and backend packages.
    package_root : pathlib.Path | None
        Optional directory containing split first-party repositories.
    """

    python: str
    repo_root: Path
    include_core: bool = False
    core_extras: tuple[str, ...] = ()
    include_bundle: bool = False
    package_root: Path | None = None


def editable_core_requirement(
    repo_root: Path,
    *,
    extras: tuple[str, ...] = (),
) -> str:
    """
    Return the editable requirement string for the core package.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root containing the core ``codira`` package.
    extras : tuple[str, ...], optional
        Optional extras requested on the core editable install.

    Returns
    -------
    str
        Editable requirement string for the core package, including extras when
        requested.
    """
    if not extras:
        return str(repo_root)
    return f"{repo_root}[{','.join(extras)}]"


def first_party_package_root(repo_root: Path, package_root: Path | None) -> Path:
    """
    Return the directory containing first-party package repositories.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root that owns the monorepo-local ``packages`` directory.
    package_root : pathlib.Path | None
        Optional directory containing split first-party repositories.

    Returns
    -------
    pathlib.Path
        Directory used to resolve first-party package checkouts.
    """
    if package_root is None:
        return repo_root / "packages"
    return package_root


def editable_package_paths(
    repo_root: Path,
    *,
    package_root: Path | None = None,
) -> tuple[Path, ...]:
    """
    Return the authoritative editable package paths for the repository.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root that owns the monorepo-local package defaults.
    package_root : pathlib.Path | None, optional
        Optional directory containing split first-party repositories.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Editable package directories in deterministic install order.
    """
    base = first_party_package_root(repo_root, package_root)
    return tuple(
        base / relative.removeprefix("packages/")
        for relative in FIRST_PARTY_PACKAGE_DIRS
    )


def bundle_package_path(
    repo_root: Path,
    *,
    package_root: Path | None = None,
) -> Path:
    """
    Return the editable bundle package path for the repository.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root that owns the monorepo-local package defaults.
    package_root : pathlib.Path | None, optional
        Optional directory containing split first-party repositories.

    Returns
    -------
    pathlib.Path
        Bundle package directory resolved from ``repo_root``.
    """
    base = first_party_package_root(repo_root, package_root)
    return base / BUNDLE_PACKAGE_DIR.removeprefix("packages/")


def non_bundle_package_paths(
    repo_root: Path,
    *,
    package_root: Path | None = None,
) -> tuple[Path, ...]:
    """
    Return editable first-party package paths excluding the bundle package.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root that owns the monorepo-local package defaults.
    package_root : pathlib.Path | None, optional
        Optional directory containing split first-party repositories.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Editable package directories except the curated bundle package.
    """
    bundle_path = bundle_package_path(repo_root, package_root=package_root)
    return tuple(
        package_path
        for package_path in editable_package_paths(
            repo_root,
            package_root=package_root,
        )
        if package_path != bundle_path
    )


def build_install_commands(
    request: InstallCommandRequest,
) -> tuple[tuple[str, ...], ...]:
    """
    Build the exact pip command plan for first-party packages.

    Parameters
    ----------
    request : InstallCommandRequest
        Install command construction request.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Deterministic pip commands for the source-tree package set.
    """
    editable_install_argv: list[str] = [request.python, "-m", "pip", "install"]
    if request.include_core:
        editable_install_argv.extend(
            (
                "-e",
                editable_core_requirement(
                    request.repo_root, extras=request.core_extras
                ),
            )
        )
    for package_path in non_bundle_package_paths(
        request.repo_root,
        package_root=request.package_root,
    ):
        editable_install_argv.extend(("-e", str(package_path)))

    commands: list[tuple[str, ...]] = []
    if request.include_bundle:
        commands.append(
            (
                request.python,
                "-m",
                "pip",
                "uninstall",
                "-y",
                "codira-bundle-official",
            )
        )
    commands.append(tuple(editable_install_argv))
    if request.include_bundle:
        commands.append(
            (
                request.python,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "-e",
                str(
                    bundle_package_path(
                        request.repo_root,
                        package_root=request.package_root,
                    )
                ),
            )
        )
    return tuple(commands)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments for the install helper.

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
        description="Install codira first-party packages from the local checkout."
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to run `pip install`.",
    )
    parser.add_argument(
        "--include-core",
        action="store_true",
        help="Include the editable core codira package in the install command.",
    )
    parser.add_argument(
        "--core-extra",
        dest="core_extras",
        action="append",
        default=[],
        help="Optional extra requested on the editable core install. Repeat as needed.",
    )
    parser.add_argument(
        "--include-bundle",
        action="store_true",
        help="Also install the curated bundle meta-package without its pinned deps.",
    )
    parser.add_argument(
        "--package-root",
        type=Path,
        help=(
            "Directory containing first-party split repositories. Defaults to "
            "the monorepo packages/ directory."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved command without executing it.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Install the first-party package set for the local checkout.

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
    commands = build_install_commands(
        InstallCommandRequest(
            python=args.python,
            repo_root=REPO_ROOT,
            include_core=args.include_core,
            core_extras=tuple(args.core_extras),
            include_bundle=args.include_bundle,
            package_root=args.package_root,
        )
    )
    for command in commands:
        print(" ".join(command))
    if args.dry_run:
        return 0
    for command in commands:
        subprocess.run(command, cwd=REPO_ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
