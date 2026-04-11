#!/usr/bin/env python3
"""Define post-split CI plans for the future first-party repositories.

Responsibilities
----------------
- Record the deterministic validation commands each future repository should run after the multirepo split.
- Keep the future-repo CI contract explicit before repository extraction begins.
- Provide one source of truth for CI planning docs and regression tests during the split preparation phase.

Design principles
-----------------
The helper stays declarative and deterministic so CI decomposition can be reviewed, tested, and copied into split repositories without inventing commands ad hoc.

Architectural role
------------------
This script belongs to the **developer tooling layer** and prepares the CI decomposition required by Phase 3 of the packaging migration.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FutureRepoCISpec:
    """
    Declarative CI contract for one future repository.

    Parameters
    ----------
    repository : str
        Future repository name.
    purpose : str
        Short description of what the repository owns.
    install : tuple[tuple[str, ...], ...]
        Deterministic install commands for CI setup.
    validate : tuple[tuple[str, ...], ...]
        Deterministic validation commands for CI execution.
    """

    repository: str
    purpose: str
    install: tuple[tuple[str, ...], ...]
    validate: tuple[tuple[str, ...], ...]


def future_repo_ci_specs() -> tuple[FutureRepoCISpec, ...]:
    """
    Return the accepted CI contracts for the future split repositories.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[FutureRepoCISpec, ...]
        Future repository CI specifications in deterministic split order.
    """
    package_validate = (
        ("python", "-m", "black", "--check", "src", "tests"),
        ("python", "-m", "ruff", "check", "src", "tests"),
        ("python", "-m", "mypy", "src", "tests"),
        ("python", "-m", "pytest", "-q", "tests"),
    )
    return (
        FutureRepoCISpec(
            repository="codira",
            purpose="core platform and cross-package integration",
            install=(
                ("python", "-m", "pip", "install", "--upgrade", "pip"),
                ("python", "-m", "pip", "install", "-e", ".[dev,docs,semantic]"),
            ),
            validate=(
                ("python", "-m", "pre_commit", "run", "--all-files"),
                ("python", "-m", "black", "--check", "src", "scripts", "tests"),
                ("python", "-m", "ruff", "check", "src", "scripts", "tests"),
                ("python", "-m", "mypy", "src", "scripts", "tests"),
                ("python", "-m", "pytest", "-q"),
            ),
        ),
        FutureRepoCISpec(
            repository="codira-analyzer-python",
            purpose="first-party Python analyzer plugin",
            install=(("python", "-m", "pip", "install", "-e", ".[test]"),),
            validate=package_validate,
        ),
        FutureRepoCISpec(
            repository="codira-analyzer-json",
            purpose="first-party JSON analyzer plugin",
            install=(("python", "-m", "pip", "install", "-e", ".[test]"),),
            validate=package_validate,
        ),
        FutureRepoCISpec(
            repository="codira-analyzer-c",
            purpose="first-party C analyzer plugin",
            install=(("python", "-m", "pip", "install", "-e", ".[test]"),),
            validate=package_validate,
        ),
        FutureRepoCISpec(
            repository="codira-analyzer-bash",
            purpose="first-party Bash analyzer plugin",
            install=(("python", "-m", "pip", "install", "-e", ".[test]"),),
            validate=package_validate,
        ),
        FutureRepoCISpec(
            repository="codira-backend-sqlite",
            purpose="first-party SQLite backend plugin",
            install=(("python", "-m", "pip", "install", "-e", ".[test]"),),
            validate=package_validate,
        ),
        FutureRepoCISpec(
            repository="codira-bundle-official",
            purpose="curated first-party bundle package",
            install=(("python", "-m", "pip", "install", "-e", ".[test]"),),
            validate=(
                ("python", "-m", "black", "--check", "tests"),
                ("python", "-m", "ruff", "check", "tests"),
                ("python", "-m", "mypy", "tests"),
                ("python", "-m", "pytest", "-q", "tests"),
            ),
        ),
    )
