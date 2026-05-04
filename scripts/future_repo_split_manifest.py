#!/usr/bin/env python3
"""Define file-ownership manifests for the future multirepo split.

Responsibilities
----------------
- Record the deterministic path ownership for each future repository in the accepted split topology.
- Keep the actual repository extraction step grounded in a reviewed file manifest rather than an informal checklist.
- Provide one source of truth for split planning docs and regression tests.

Design principles
-----------------
The manifest stays declarative, path-based, and explicit so repository extraction can be reviewed and executed mechanically.

Architectural role
------------------
This script belongs to the **developer tooling layer** and prepares the concrete file movement needed for Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FutureRepoSplitManifest:
    """
    Declarative path manifest for one future repository.

    Parameters
    ----------
    repository : str
        Future repository name.
    owned_paths : tuple[str, ...]
        Repository-relative paths that should move into the future repository.
    stays_in_core : tuple[str, ...]
        Repository-relative paths that remain owned by the core repo but are
        operationally relevant to the future repository.
    """

    repository: str
    owned_paths: tuple[str, ...]
    stays_in_core: tuple[str, ...]


def future_repo_split_manifests() -> tuple[FutureRepoSplitManifest, ...]:
    """
    Return the accepted path manifests for the future split repositories.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[FutureRepoSplitManifest, ...]
        Split manifests in deterministic repository order.
    """
    return (
        FutureRepoSplitManifest(
            repository="codira",
            owned_paths=(
                ".gitignore",
                ".github/workflows/ci.yml",
                ".github/workflows/commit-message-check.yml",
                ".github/workflows/docs.yml",
                ".github/workflows/release.yml",
                ".pre-commit-config.yaml",
                ".releaserc.json",
                "CHANGELOG.md",
                "LICENSE",
                "README.md",
                "docs/",
                "examples/",
                "mkdocs.yml",
                "package-lock.json",
                "package.json",
                "pyproject.toml",
                "scripts/",
                "src/codira/",
                "tests/",
            ),
            stays_in_core=(),
        ),
        FutureRepoSplitManifest(
            repository="codira-analyzer-python",
            owned_paths=(
                "packages/codira-analyzer-python/README.md",
                "packages/codira-analyzer-python/pyproject.toml",
                "packages/codira-analyzer-python/src/",
                "packages/codira-analyzer-python/tests/",
            ),
            stays_in_core=(
                "src/codira/analyzers/python.py",
                "tests/test_plugins.py",
            ),
        ),
        FutureRepoSplitManifest(
            repository="codira-analyzer-json",
            owned_paths=(
                "packages/codira-analyzer-json/README.md",
                "packages/codira-analyzer-json/pyproject.toml",
                "packages/codira-analyzer-json/src/",
                "packages/codira-analyzer-json/tests/",
            ),
            stays_in_core=(
                "src/codira/analyzers/json.py",
                "tests/test_plugins.py",
            ),
        ),
        FutureRepoSplitManifest(
            repository="codira-analyzer-c",
            owned_paths=(
                "packages/codira-analyzer-c/README.md",
                "packages/codira-analyzer-c/pyproject.toml",
                "packages/codira-analyzer-c/src/",
                "packages/codira-analyzer-c/tests/",
            ),
            stays_in_core=(
                "src/codira/analyzers/c.py",
                "tests/test_plugins.py",
            ),
        ),
        FutureRepoSplitManifest(
            repository="codira-analyzer-bash",
            owned_paths=(
                "packages/codira-analyzer-bash/README.md",
                "packages/codira-analyzer-bash/pyproject.toml",
                "packages/codira-analyzer-bash/src/",
                "packages/codira-analyzer-bash/tests/",
            ),
            stays_in_core=(
                "src/codira/analyzers/bash.py",
                "tests/test_plugins.py",
            ),
        ),
        FutureRepoSplitManifest(
            repository="codira-backend-sqlite",
            owned_paths=(
                "packages/codira-backend-sqlite/README.md",
                "packages/codira-backend-sqlite/pyproject.toml",
                "packages/codira-backend-sqlite/src/",
                "packages/codira-backend-sqlite/tests/",
            ),
            stays_in_core=(
                "src/codira/indexer.py",
                "src/codira/sqlite_backend_support.py",
                "tests/test_plugins.py",
            ),
        ),
        FutureRepoSplitManifest(
            repository="codira-backend-duckdb",
            owned_paths=(
                "packages/codira-backend-duckdb/README.md",
                "packages/codira-backend-duckdb/pyproject.toml",
                "packages/codira-backend-duckdb/src/",
                "packages/codira-backend-duckdb/tests/",
            ),
            stays_in_core=("tests/test_plugins.py",),
        ),
        FutureRepoSplitManifest(
            repository="codira-bundle-official",
            owned_paths=(
                "packages/codira-bundle-official/README.md",
                "packages/codira-bundle-official/pyproject.toml",
                "packages/codira-bundle-official/tests/",
            ),
            stays_in_core=("tests/test_plugins.py",),
        ),
    )
