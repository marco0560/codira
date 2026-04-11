#!/usr/bin/env python3
"""Shared first-party package inventory for repository-local tooling.

Responsibilities
----------------
- Define the authoritative repository-local first-party package list.
- Resolve first-party package directories from a repository root.
- Keep install, build-rehearsal, and bootstrap helpers aligned to one source of truth.

Design principles
-----------------
The helper stays small and deterministic so packaging workflows can share one
package inventory without duplicating ordering decisions.

Architectural role
------------------
This script belongs to the **developer tooling layer** and centralizes the
accepted first-party package boundary used across migration tooling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

FIRST_PARTY_PACKAGE_DIRS: tuple[str, ...] = (
    "packages/codira-analyzer-python",
    "packages/codira-analyzer-json",
    "packages/codira-analyzer-c",
    "packages/codira-analyzer-bash",
    "packages/codira-backend-sqlite",
    "packages/codira-bundle-official",
)


def package_paths(repo_root: Path) -> tuple[Path, ...]:
    """
    Return first-party package directories in deterministic order.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root containing the first-party packages.

    Returns
    -------
    tuple[pathlib.Path, ...]
        First-party package directories resolved from ``repo_root``.
    """
    return tuple(repo_root / relative for relative in FIRST_PARTY_PACKAGE_DIRS)
