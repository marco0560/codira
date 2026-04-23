#!/usr/bin/env python3
"""Verify exported split repositories against the local core checkout.

Responsibilities
----------------
- Build the deterministic pre-publish validation plan for exported split repositories.
- Ensure package repos install against the local core checkout rather than an unrelated published `codira`.
- Validate the exported bundle repository only after the local first-party package set is installed.

Design principles
-----------------
The helper is explicit about command order so pre-publish split validation stays
reproducible and does not accidentally resolve against PyPI.

Architectural role
------------------
This script belongs to the **developer tooling layer** and supports multirepo
split rehearsal before publication.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PACKAGE_REPOS: tuple[str, ...] = (
    "codira-analyzer-python",
    "codira-analyzer-json",
    "codira-analyzer-c",
    "codira-analyzer-bash",
    "codira-backend-sqlite",
)
BUNDLE_REPO = "codira-bundle-official"


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


def split_repo_names() -> tuple[str, ...]:
    """
    Return the exported split repositories that should be verified.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[str, ...]
        Exported package repository names in deterministic validation order.
    """
    return (*PACKAGE_REPOS, BUNDLE_REPO)


def build_repo_validation_commands(
    *,
    python: str,
    exported_repo_root: Path,
    core_repo_root: Path,
) -> tuple[tuple[str, ...], ...]:
    """
    Build the validation command plan for one exported split repository.

    Parameters
    ----------
    python : str
        Python interpreter used to run validation commands.
    exported_repo_root : pathlib.Path
        Exported split repository directory to validate.
    core_repo_root : pathlib.Path
        Local core checkout used to satisfy the `codira` dependency.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Validation commands in deterministic order.
    """
    install_commands: list[tuple[str, ...]] = [
        (python, "-m", "pip", "install", "--upgrade", "pip"),
        (
            python,
            "-m",
            "pip",
            "install",
            "-e",
            f"{_path_text(core_repo_root)}[semantic]",
        ),
    ]
    if exported_repo_root.name == BUNDLE_REPO:
        for repo_name in PACKAGE_REPOS:
            install_commands.append(
                (
                    python,
                    "-m",
                    "pip",
                    "install",
                    "-e",
                    _path_text(exported_repo_root.parent / repo_name),
                )
            )
    install_commands.append(
        (
            python,
            "-m",
            "pip",
            "install",
            "-e",
            f"{_path_text(exported_repo_root)}[test]",
        )
    )

    if exported_repo_root.name == BUNDLE_REPO:
        validate_commands: tuple[tuple[str, ...], ...] = (
            (python, "-m", "black", "--check", "tests"),
            (python, "-m", "ruff", "check", "tests"),
            (python, "-m", "mypy", "tests"),
            (python, "-m", "pytest", "-q", "tests"),
        )
    else:
        validate_commands = (
            (python, "-m", "black", "--check", "src", "tests"),
            (python, "-m", "ruff", "check", "src", "tests"),
            (python, "-m", "mypy", "src", "tests"),
            (python, "-m", "pytest", "-q", "tests"),
        )

    return (*install_commands, *validate_commands)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments for exported split-repo verification.

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
            "Verify exported split repositories against the local codira core "
            "checkout before publication."
        )
    )
    parser.add_argument(
        "export_root",
        type=Path,
        help="Directory containing the exported split repositories.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to run verification commands.",
    )
    parser.add_argument(
        "--core-repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Local codira checkout used to satisfy the core dependency.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved commands without executing them.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Run exported split-repo verification.

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
    for repo_name in split_repo_names():
        repo_root = args.export_root / repo_name
        print(f"== {repo_name} ==")
        commands = build_repo_validation_commands(
            python=args.python,
            exported_repo_root=repo_root,
            core_repo_root=args.core_repo_root,
        )
        for command in commands:
            print(" ".join(command))
        if args.dry_run:
            continue
        for command in commands:
            subprocess.run(command, cwd=repo_root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
